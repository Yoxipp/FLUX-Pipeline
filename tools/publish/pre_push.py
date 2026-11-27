"""git pre-push hook body for FLUX (installed by install_hook.py).

Reads the pushed refs on stdin ("<local ref> <local sha> <remote ref> <remote sha>" per line) and
refuses the push when a private path, a private string, an unknown author or a secret would leave.
Without PRIVATE/ (a plain public clone) only the secret scan runs. Exit 0 = allow, 1 = refuse.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import checks  # noqa: E402


def main(argv: list[str], stdin_text: str) -> int:
    checks.utf8_stdout()
    remote = argv[0] if argv else "origin"
    try:
        repo = checks.repo_root()
        private_dir = checks.private_dir_of(repo)
        rules = checks.load_rules(private_dir) if private_dir else None
        if rules is None:
            print("flux hook: PRIVATE/ not found, only the secret scan runs", file=sys.stderr)
        gitleaks = checks.find_gitleaks(private_dir)
        if gitleaks is None:
            print(f"flux hook: push refused. {checks.GITLEAKS_HINT}", file=sys.stderr)
            return 1
        findings: list[checks.Finding] = []
        for line in stdin_text.splitlines():
            parts = line.split()
            if len(parts) != 4:
                continue
            _local_ref, local_sha, _remote_ref, remote_sha = parts
            if local_sha == checks.ZERO_SHA:
                continue  # branch deletion
            rev_args = checks.range_args(local_sha, remote_sha, repo, remote)
            commits = checks.commits_in(rev_args, repo)
            if rules:
                findings += checks.check_paths(local_sha, repo, rules)
                findings += checks.check_commits(commits, repo, rules)
            if commits:
                findings += checks.run_gitleaks(gitleaks, rev_args, repo, checks.gitleaks_ignore_file(private_dir))
    except checks.CheckError as exc:
        print(f"flux hook: push refused. {exc}", file=sys.stderr)
        return 1
    if findings:
        print(f"flux hook: push refused, {len(findings)} finding(s):", file=sys.stderr)
        sys.stdout = sys.stderr
        checks.print_findings(findings)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], sys.stdin.read()))
