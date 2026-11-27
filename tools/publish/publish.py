"""One-step publication of FLUX to the public GitHub repository, then of the private checkout.

Run through PUBLISH_GITHUB_PUBLIC.bat at the repo root. It refuses, without fixing anything, when:
  * a private path is tracked by a branch to publish,
  * a commit to push carries a private string, an unknown author, or a secret (gitleaks),
  * the backend test suite of a branch tip is not "verdict: PASS",
  * a push would not be a fast-forward (never forces).
Then: ``git push --atomic origin <branches>``, then the private checkout (``PRIVATE/``): commit
everything if dirty, push.

Usage: python tools/publish/publish.py [--branches main dev] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import checks  # noqa: E402

REMOTE = "origin"


def step(text: str) -> None:
    print(f"\n== {text}")


def run_backend_tests(repo: Path, sha: str) -> bool:
    """Backend suite on a detached temporary worktree of `sha`."""
    tmp_root = Path(tempfile.mkdtemp(prefix="flux_publish_"))
    tree = tmp_root / "tree"
    checks.git(["worktree", "add", "--detach", str(tree), sha], repo)
    log_path = tmp_root / "run_tests.log"
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        with log_path.open("wb") as log:
            proc = subprocess.run([sys.executable, "tests/run_tests.py"], cwd=str(tree / "backend"),
                                  stdout=log, stderr=subprocess.STDOUT, env=env)
        output = log_path.read_text(encoding="utf-8", errors="replace")
        verdict = [line for line in output.splitlines() if "verdict:" in line]
        print(f"  {verdict[-1].strip() if verdict else 'no verdict line'} (exit {proc.returncode})")
        passed = proc.returncode == 0 and bool(verdict) and "PASS" in verdict[-1]
        if not passed:
            print(f"  full log: {log_path}")
        return passed
    finally:
        checks.git(["worktree", "remove", "--force", str(tree)], repo, check=False)


def private_commit_and_push(private_dir: Path, dry_run: bool) -> bool:
    status = checks.git_text(["status", "--porcelain"], private_dir)
    if status:
        print(f"  {len(status.splitlines())} changed path(s) in the private checkout")
        if dry_run:
            print("  dry run: no commit")
        else:
            today = datetime.date.today().isoformat()
            checks.git(["add", "-A"], private_dir)
            checks.git(["commit", "-m", f"chore: sync private notes {today}"], private_dir)
            print("  committed")
    branch = checks.git_text(["rev-parse", "--abbrev-ref", "HEAD"], private_dir)
    if dry_run:
        print(f"  dry run: would push {branch}")
        return True
    proc = subprocess.run(["git", "push", REMOTE, branch], cwd=str(private_dir))
    return proc.returncode == 0


def main(argv: list[str] | None = None) -> int:
    checks.utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--branches", nargs="+", default=["main", "dev"])
    parser.add_argument("--dry-run", action="store_true", help="run every check, push and commit nothing")
    args = parser.parse_args(argv)

    try:
        repo = checks.repo_root(Path(__file__).resolve().parent)
        private_dir = checks.private_dir_of(repo)
        if private_dir is None:
            print("REFUSED: PRIVATE/ not found at the repo root (the maintainers' private checkout).")
            return 1
        rules = checks.load_rules(private_dir)
        gitleaks = checks.find_gitleaks(private_dir)
        if gitleaks is None:
            print(f"REFUSED: {checks.GITLEAKS_HINT}")
            return 1

        step(f"fetch {REMOTE}")
        checks.git(["fetch", REMOTE, "--prune"], repo)

        to_push: list[str] = []
        tested: dict[str, bool] = {}
        refused = False
        for branch in args.branches:
            step(f"branch {branch}")
            local = checks.git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], repo,
                               check=False).decode().strip()
            if not local:
                print(f"  REFUSED: no local branch {branch}")
                refused = True
                continue
            remote = checks.git(["rev-parse", "--verify", "--quiet", f"refs/remotes/{REMOTE}/{branch}"],
                                repo, check=False).decode().strip()
            if remote == local:
                print("  up to date, nothing to push")
                continue
            if remote and subprocess.run(["git", "merge-base", "--is-ancestor", remote, local],
                                         cwd=str(repo)).returncode != 0:
                print(f"  REFUSED: {REMOTE}/{branch} is not an ancestor (no forced push from this script)")
                refused = True
                continue
            rev_args = checks.range_args(local, remote or checks.ZERO_SHA, repo, REMOTE)
            commits = checks.commits_in(rev_args, repo)
            print(f"  {len(commits)} commit(s) to push")
            findings = checks.check_paths(local, repo, rules)
            findings += checks.check_commits(commits, repo, rules)
            if commits:
                findings += checks.run_gitleaks(gitleaks, rev_args, repo, checks.gitleaks_ignore_file(private_dir))
            if findings:
                print(f"  REFUSED: {len(findings)} finding(s)")
                checks.print_findings(findings)
                refused = True
                continue
            print("  paths, strings, authors, secrets: OK")
            if local not in tested:
                print("  backend tests (temporary worktree)...")
                tested[local] = run_backend_tests(repo, local)
            if not tested[local]:
                print("  REFUSED: backend tests did not pass")
                refused = True
                continue
            to_push.append(branch)

        if refused:
            print("\nREFUSED: nothing pushed. Fix the findings above, commit, run again.")
            return 1

        step("push public")
        if not to_push:
            print("  nothing to push")
        elif args.dry_run:
            print(f"  dry run: would run git push --atomic {REMOTE} {' '.join(to_push)}")
        else:
            if subprocess.run(["git", "push", "--atomic", REMOTE, *to_push], cwd=str(repo)).returncode != 0:
                print("FAILED: public push refused (see above). The private checkout was not pushed.")
                return 1

        step("private checkout")
        if not private_commit_and_push(private_dir, args.dry_run):
            print("FAILED: private push refused (see above). The public push is done.")
            return 1
    except checks.CheckError as exc:
        print(f"REFUSED: {exc}")
        return 1

    print("\nDONE" + (" (dry run, nothing pushed)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
