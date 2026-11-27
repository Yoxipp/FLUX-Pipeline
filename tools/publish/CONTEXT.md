# tools/publish

Guard for the public repository. Stdlib Python 3.10+, run with the `python` of the PATH.

| File | Role |
|---|---|
| `checks.py` | Shared checks: private paths tracked at a branch tip, private strings in added lines and commit messages, allowed authors and committers, secrets (gitleaks). |
| `publish.py` | `PUBLISH_GITHUB_PUBLIC.bat`: for `main` and `dev`, checks, then backend tests on a temporary worktree of the tip (`verdict: PASS`), then `git push --atomic origin main dev`, then the private checkout (commit if dirty, push). Refuses non fast-forward pushes. `--dry-run` pushes and commits nothing. |
| `pre_push.py` | Body of the git pre-push hook: same checks without the tests, on the commits being pushed. |
| `install_hook.py` | Writes `.git/hooks/pre-push` (shared by worktrees): `pre_push.py`, then the workspace guard if one is found (`--ws-py`), then Git LFS. Keeps a foreign hook as `pre-push.bak`. |

Rules are not in this public folder. They are read from the maintainers' private checkout (`PRIVATE/`, ignored):
`publish/private_paths.txt`, `publish/allowed_authors.txt`, `publish/strings_source.txt` (path of the
git-filter-repo `--replace-text` file), optional `publish/gitleaksignore` (reviewed fingerprints).
gitleaks is looked up in the PATH, then `PRIVATE/bin/`; missing means refused, nothing is downloaded.
Without `PRIVATE/` the hook only runs the secret scan, and `publish.py` refuses.

Limits: binary files are not scanned for strings (only gitleaks sees them); a finding names the rule file and
line, never the private string. Tests: `backend/tests/publish_tools/`.
