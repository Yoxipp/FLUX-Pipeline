"""Checks run before anything reaches the public FLUX repository.

Shared by publish.py (one-step publication) and pre_push.py (git pre-push hook).
Stdlib only, Python 3.10+.

Rules are not stored in this public file: they are read from the maintainers' private
checkout (``PRIVATE/`` at the repo root, ignored by git):

* ``PRIVATE/publish/private_paths.txt``: fnmatch globs of paths that must never be tracked.
* ``PRIVATE/publish/allowed_authors.txt``: "Name <email>" allowed as author and committer.
* ``PRIVATE/publish/strings_source.txt``: one line, the path (relative to ``PRIVATE/``) of the
  strings file used by the history purge, in git-filter-repo ``--replace-text`` syntax (literal,
  ``regex:``, ``glob:``, optional ``==>``). The same strings must not come back in new commits.

A finding never prints the private string itself, only the rule file and line number.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ZERO_SHA = "0" * 40

PRIVATE_DIR_NAME = "PRIVATE"
PATHS_FILE = Path("publish") / "private_paths.txt"
AUTHORS_FILE = Path("publish") / "allowed_authors.txt"
STRINGS_SOURCE_FILE = Path("publish") / "strings_source.txt"


class CheckError(RuntimeError):
    """A check could not run (missing tool, git failure). Always refuses the push."""


@dataclass
class Finding:
    kind: str          # "path", "content", "message", "author", "secret"
    where: str         # file path or commit
    detail: str        # rule reference, never the private string

    def __str__(self) -> str:
        return f"[{self.kind}] {self.where}: {self.detail}"


@dataclass
class ContentRule:
    source: str        # "replace_text.txt:12"
    regex: re.Pattern


@dataclass
class Rules:
    path_globs: list[tuple[str, str]] = field(default_factory=list)   # (glob, source)
    content: list[ContentRule] = field(default_factory=list)
    authors: set[str] = field(default_factory=set)


# --------------------------------------------------------------------------- git

def git(args: list[str], cwd: Path, *, input_bytes: bytes | None = None, check: bool = True) -> bytes:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), input=input_bytes,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        raise CheckError(f"git {' '.join(args)} failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout


def git_text(args: list[str], cwd: Path) -> str:
    return git(args, cwd).decode("utf-8", "replace").strip()


def sha_exists(sha: str, repo: Path) -> bool:
    proc = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=str(repo),
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc.returncode == 0


def range_args(local_sha: str, remote_sha: str, repo: Path, remote: str = "origin") -> list[str]:
    """rev-list arguments selecting the commits a push of local_sha would send."""
    if remote_sha and remote_sha != ZERO_SHA and sha_exists(remote_sha, repo):
        return [local_sha, f"^{remote_sha}"]
    return [local_sha, "--not", f"--remotes={remote}"]


def commits_in(rev_args: list[str], repo: Path) -> list[str]:
    out = git_text(["rev-list", *rev_args], repo)
    return out.split() if out else []


# --------------------------------------------------------------------------- rules

def _read_lines(path: Path) -> list[tuple[int, bytes]]:
    rows = []
    for number, raw in enumerate(path.read_bytes().splitlines(), start=1):
        rows.append((number, raw.rstrip(b"\r")))
    return rows


def parse_replace_text(path: Path) -> list[ContentRule]:
    """Left side of each git-filter-repo --replace-text line, compiled to a bytes regex."""
    rules = []
    for number, line in _read_lines(path):
        if not line:
            continue
        old = line.rsplit(b"==>", 1)[0] if b"==>" in line else line
        if not old:
            continue
        if old.startswith(b"regex:"):
            pattern = old[len(b"regex:"):]
        elif old.startswith(b"glob:"):
            pattern = re.escape(old[len(b"glob:"):]).replace(rb"\*", b".*").replace(rb"\?", b".")
        else:
            pattern = re.escape(old)
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            raise CheckError(f"{path.name}:{number}: invalid regex ({exc})") from exc
        rules.append(ContentRule(source=f"{path.name}:{number}", regex=regex))
    return rules


def load_rules(private_dir: Path) -> Rules:
    rules = Rules()
    paths_file = private_dir / PATHS_FILE
    authors_file = private_dir / AUTHORS_FILE
    source_file = private_dir / STRINGS_SOURCE_FILE
    for required in (paths_file, authors_file, source_file):
        if not required.is_file():
            raise CheckError(f"rule file missing: {required}")
    strings_file = private_dir / source_file.read_text(encoding="utf-8").strip()
    if not strings_file.is_file():
        raise CheckError(f"strings file missing: {strings_file}")
    for number, line in _read_lines(paths_file):
        text = line.decode("utf-8").strip()
        if text and not text.startswith("#"):
            rules.path_globs.append((text, f"{paths_file.name}:{number}"))
    for number, line in _read_lines(authors_file):
        text = line.decode("utf-8").strip()
        if text and not text.startswith("#"):
            rules.authors.add(text)
    rules.content = parse_replace_text(strings_file)
    return rules


# --------------------------------------------------------------------------- checks

def check_paths(tip: str, repo: Path, rules: Rules) -> list[Finding]:
    """Every file tracked at `tip` against the private path globs."""
    findings = []
    names = git(["ls-tree", "-r", "-z", "--name-only", tip], repo).split(b"\0")
    for raw in names:
        if not raw:
            continue
        name = raw.decode("utf-8", "replace")
        low = name.lower()
        for glob, source in rules.path_globs:
            if fnmatch.fnmatchcase(low, glob.lower()):
                findings.append(Finding("path", name, f"private path ({source})"))
                break
    return findings


def _first_rule(data: bytes, rules: Rules) -> ContentRule | None:
    for rule in rules.content:
        if rule.regex.search(data):
            return rule
    return None


def check_commits(commits: list[str], repo: Path, rules: Rules) -> list[Finding]:
    """Authors, committers, messages and added lines of the given commits."""
    findings: list[Finding] = []
    if not commits:
        return findings
    stdin = ("\n".join(commits) + "\n").encode()

    # Identities and messages (merges included).
    sep = "\x1e"
    log = git(["log", "--no-walk=unsorted", "--stdin",
               f"--format=%H%x1f%an <%ae>%x1f%cn <%ce>%x1f%B{sep}"], repo, input_bytes=stdin)
    for record in log.split(sep.encode()):
        record = record.strip(b"\n")
        if not record:
            continue
        sha, author, committer, message = record.split(b"\x1f", 3)
        short = sha.decode()[:9]
        for role, ident in (("author", author), ("committer", committer)):
            if ident.decode("utf-8", "replace") not in rules.authors:
                findings.append(Finding("author", short, f"{role} not in allowed_authors.txt"))
        rule = _first_rule(message, rules)
        if rule:
            findings.append(Finding("message", short, f"private string ({rule.source})"))

    # Added lines (merge commits skipped: their content comes from the merged commits).
    diff = git(["log", "--no-walk=unsorted", "--stdin", "--no-merges", "-p", "-U0",
                "--no-color", "--no-ext-diff", "--no-textconv", "--format=\x1fCOMMIT %H"],
               repo, input_bytes=stdin)
    sha = path = ""
    seen: set[tuple[str, str, str]] = set()
    for line in diff.split(b"\n"):
        if line.startswith(b"\x1fCOMMIT "):
            sha = line[8:].decode()[:9]
            path = ""
        elif line.startswith(b"+++ "):
            target = line[4:].decode("utf-8", "replace")
            path = target[2:] if target.startswith("b/") else target
        elif line.startswith(b"+") and path:
            rule = _first_rule(line[1:], rules)
            if rule and (sha, path, rule.source) not in seen:
                seen.add((sha, path, rule.source))
                findings.append(Finding("content", f"{sha} {path}", f"private string ({rule.source})"))
    return findings


# --------------------------------------------------------------------------- gitleaks

def find_gitleaks(private_dir: Path | None) -> Path | None:
    found = shutil.which("gitleaks")
    if found:
        return Path(found)
    if private_dir:
        for name in ("gitleaks.exe", "gitleaks"):
            candidate = private_dir / "bin" / name
            if candidate.is_file():
                return candidate
    return None


GITLEAKS_HINT = (
    "gitleaks not found (PATH, then PRIVATE/bin/). Get the release from "
    "https://github.com/gitleaks/gitleaks/releases, check its SHA256 against the release "
    "checksums.txt, and put gitleaks.exe in PRIVATE/bin/."
)


def gitleaks_ignore_file(private_dir: Path | None) -> Path | None:
    """Reviewed false positives, one gitleaks fingerprint (commit:file:rule:line) per line."""
    if private_dir:
        candidate = private_dir / "publish" / "gitleaksignore"
        if candidate.is_file():
            return candidate
    return None


def run_gitleaks(exe: Path, rev_args: list[str], repo: Path, ignore_file: Path | None = None) -> list[Finding]:
    """Scan the commits selected by rev_args. Exit 2 = leaks, other non-zero = error."""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        cmd = [str(exe), "git", str(repo), "--log-opts", " ".join(rev_args), "--redact",
               "--no-banner", "--exit-code", "2", "--report-format", "json",
               "--report-path", str(report)]
        if ignore_file:
            cmd += ["--gitleaks-ignore-path", str(ignore_file)]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode == 0:
            return []
        if proc.returncode != 2:
            err = proc.stderr.decode("utf-8", "replace").strip()[-500:]
            raise CheckError(f"gitleaks failed (exit {proc.returncode}): {err}")
        leaks = json.loads(report.read_text(encoding="utf-8") or "[]")
    return [Finding("secret", f"{leak.get('Commit', '')[:9]} {leak.get('File', '')}:{leak.get('StartLine', '')}",
                    f"gitleaks rule {leak.get('RuleID', '?')}, fingerprint {leak.get('Fingerprint', '?')}")
            for leak in leaks]


# --------------------------------------------------------------------------- helpers

def repo_root(start: Path | None = None) -> Path:
    return Path(git_text(["rev-parse", "--show-toplevel"], start or Path.cwd()))


def private_dir_of(repo: Path) -> Path | None:
    candidate = repo / PRIVATE_DIR_NAME
    return candidate if candidate.is_dir() else None


def print_findings(findings: list[Finding], limit: int = 50) -> None:
    for finding in findings[:limit]:
        print(f"  {finding}")
    if len(findings) > limit:
        print(f"  ... {len(findings) - limit} more")


def utf8_stdout() -> None:
    for stream in ("stdout", "stderr"):
        try:
            getattr(__import__("sys"), stream).reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
