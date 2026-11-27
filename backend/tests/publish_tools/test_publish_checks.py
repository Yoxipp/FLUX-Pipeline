"""Tests for tools/publish/checks.py and pre_push.py (public repo publication guard)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[3] / "tools" / "publish"
sys.path.insert(0, str(_TOOLS))

import checks  # noqa: E402
import pre_push  # noqa: E402

GOOD = ("Alice", "alice@example.com")
BAD = ("Mallory", "mallory@example.com")


def _git(repo: Path, *args: str, author=GOOD) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME=author[0], GIT_AUTHOR_EMAIL=author[1],
               GIT_COMMITTER_NAME=author[0], GIT_COMMITTER_EMAIL=author[1])
    proc = subprocess.run(["git", *args], cwd=str(repo), env=env, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.stdout.decode().strip()


class PublishChecksTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.repo = root / "repo"
        self.remote = root / "remote.git"
        self.repo.mkdir()
        _git(root, "init", "--quiet", "--bare", self.remote.as_posix())
        _git(self.repo, "init", "--quiet", "-b", "main")
        _git(self.repo, "remote", "add", "origin", self.remote.as_posix())
        private = self.repo / "PRIVATE"
        (private / "publish").mkdir(parents=True)
        (private / "kit").mkdir()
        (private / "publish" / "private_paths.txt").write_text("# comment\nPRIVATE/*\nsecret_notes/*\n",
                                                               encoding="utf-8")
        (private / "publish" / "allowed_authors.txt").write_text(f"{GOOD[0]} <{GOOD[1]}>\n", encoding="utf-8")
        (private / "publish" / "strings_source.txt").write_text("kit/replace.txt\n", encoding="utf-8")
        (private / "kit" / "replace.txt").write_bytes(
            "\\\\server42==>\\\\server\nregex:(?i)codename_[a-z]+==>x\nglob:room*b==>room\nBrévallec\n".encode())
        (self.repo / ".gitignore").write_text("PRIVATE/\n", encoding="utf-8")
        (self.repo / "app.py").write_text("print('ok')\n", encoding="utf-8")
        _git(self.repo, "add", ".gitignore", "app.py")
        _git(self.repo, "commit", "--quiet", "-m", "feat: start")
        _git(self.repo, "push", "--quiet", "origin", "main")
        self.rules = checks.load_rules(private)

    def tearDown(self):
        self._tmp.cleanup()

    def _commit(self, name: str, text: str, message: str = "feat: change", author=GOOD) -> str:
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        _git(self.repo, "add", "-f", name, author=author)
        _git(self.repo, "commit", "--quiet", "-m", message, author=author)
        return _git(self.repo, "rev-parse", "HEAD")

    def _pushed(self, tip: str) -> list[checks.Finding]:
        remote_sha = _git(self.repo, "rev-parse", "origin/main")
        rev_args = checks.range_args(tip, remote_sha, self.repo)
        commits = checks.commits_in(rev_args, self.repo)
        return checks.check_paths(tip, self.repo, self.rules) + checks.check_commits(commits, self.repo, self.rules)

    def test_rules_parse_every_syntax(self):
        self.assertEqual(len(self.rules.content), 4)
        self.assertEqual(self.rules.path_globs[0][0], "PRIVATE/*")

    def test_clean_commit_passes(self):
        tip = self._commit("lib/util.py", "VALUE = 1\n")
        self.assertEqual(self._pushed(tip), [])

    def test_private_path_refused(self):
        tip = self._commit("Secret_Notes/plan.md", "nothing\n")
        kinds = [f.kind for f in self._pushed(tip)]
        self.assertEqual(kinds, ["path"])

    def test_literal_regex_glob_and_unicode_strings_refused(self):
        for text in ("root = r'\\\\server42\\share'\n", "name = 'CODENAME_blue'\n",
                     "where = 'room12b'\n", "who = 'Brévallec'\n"):
            with self.subTest(text=text):
                _git(self.repo, "reset", "--quiet", "--hard", "origin/main")  # temp test repo only
                tip = self._commit("lib/conf.py", text)
                findings = self._pushed(tip)
                self.assertEqual([f.kind for f in findings], ["content"])
                self.assertNotIn(text.strip(), str(findings[0]))  # never echo the private string

    def test_message_and_author_refused(self):
        tip = self._commit("lib/a.py", "A = 1\n", message="feat: codename_red work", author=BAD)
        kinds = sorted(f.kind for f in self._pushed(tip))
        self.assertEqual(kinds, ["author", "author", "message"])

    def test_already_pushed_content_not_rescanned(self):
        tip = self._commit("lib/conf.py", "name = 'codename_old'\n")
        _git(self.repo, "push", "--quiet", "origin", "main")
        tip = self._commit("lib/b.py", "B = 2\n")
        self.assertEqual(self._pushed(tip), [])

    def test_new_branch_range_excludes_remote_commits(self):
        _git(self.repo, "checkout", "--quiet", "-b", "dev")
        tip = self._commit("lib/c.py", "C = 3\n")
        rev_args = checks.range_args(tip, checks.ZERO_SHA, self.repo)
        self.assertEqual(checks.commits_in(rev_args, self.repo), [tip])

    def test_missing_rule_file_is_an_error(self):
        (self.repo / "PRIVATE" / "publish" / "allowed_authors.txt").unlink()
        with self.assertRaises(checks.CheckError):
            checks.load_rules(self.repo / "PRIVATE")

    def test_hook_refuses_without_gitleaks(self):
        tip = self._commit("lib/d.py", "D = 4\n")
        cwd = os.getcwd()
        old_which = checks.shutil.which
        try:
            os.chdir(self.repo)
            checks.shutil.which = lambda name: None
            stdin = f"refs/heads/main {tip} refs/heads/main {_git(self.repo, 'rev-parse', 'origin/main')}\n"
            self.assertEqual(pre_push.main(["origin"], stdin), 1)
        finally:
            checks.shutil.which = old_which
            os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
