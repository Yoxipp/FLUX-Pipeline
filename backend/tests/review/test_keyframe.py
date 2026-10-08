# test_keyframe.py - Keyframe Pro external API client and fallbacks (retake 09).
#
# A fake server speaks the real wire format (10-character length header + JSON)
# observed on Keyframe Pro 2026-10-08; nothing launches the real application.

from __future__ import annotations

import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from features.review import keyframe


class _FakeKeyframe(threading.Thread):
    def __init__(self, licensed: bool = True):
        super().__init__(daemon=True)
        self.licensed = licensed
        self.calls: list[dict] = []
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(5)
        self.port = self.srv.getsockname()[1]
        self._next = 0

    def _id(self) -> str:
        self._next += 1
        return f"id{self._next}"

    def reply(self, cmd: dict) -> dict:
        name = cmd["cmd"]
        if name == "initialize":
            return {"cmd": name, "success": self.licensed, "result": 0 if self.licensed else 1,
                    "msg": "" if self.licensed else "Keyframe Pro is not licensed"}
        out = {"cmd": name, "success": True, "msg": ""}
        if name == "add_timeline":
            out["timeline"] = {"id": self._id(), "name": cmd["name"]}
        elif name == "add_folder":
            out["folder"] = {"id": self._id(), "name": cmd["name"]}
        elif name == "import_file":
            out["source"] = {"id": self._id(), "name": cmd["name"]}
        return out

    def run(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            with conn:
                while True:
                    try:
                        head = conn.recv(10)
                    except OSError:
                        break
                    if not head:
                        break
                    size = int(head.decode())
                    body = b""
                    while len(body) < size:
                        body += conn.recv(size - len(body))
                    cmd = json.loads(body)
                    self.calls.append(cmd)
                    data = json.dumps(self.reply(cmd)).encode()
                    conn.sendall(f"{len(data):10d}".encode() + data)

    def stop(self):
        self.srv.close()


class KeyframeTests(unittest.TestCase):
    def setUp(self):
        # Never reach a real Keyframe: no launch, no executable lookup.
        for name, value in (("_launch", mock.DEFAULT), ("find_executable", None)):
            patcher = mock.patch.object(keyframe, name, return_value=value) if value is None else mock.patch.object(keyframe, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "anim" / "ref"
        self.dir.mkdir(parents=True)
        for name in ("v001.mp4", "v002.mp4", "LAST.mp4", "notes.txt"):
            (self.dir / name).write_bytes(b"x")

    def tearDown(self):
        self._tmp.cleanup()

    def _serve(self, licensed: bool):
        srv = _FakeKeyframe(licensed)
        srv.start()
        self.addCleanup(srv.stop)
        port = mock.patch.object(keyframe, "API_PORT", srv.port)
        port.start()
        self.addCleanup(port.stop)
        return srv

    def test_folder_videos_skip_last_copy(self):
        self.assertEqual([f.name for f in keyframe.folder_videos(self.dir)], ["v001.mp4", "v002.mp4"])

    def test_split_reports_missing_and_unsupported(self):
        ok, skipped = keyframe.split_items([
            {"path": str(self.dir / "v002.mp4")}, {"path": str(self.dir / "notes.txt")},
            {"path": str(self.dir / "v009.mp4")}])
        self.assertEqual(len(ok), 1)
        self.assertEqual([s["reason"][:6] for s in skipped], ["format", "introu"])

    def test_licensed_api_builds_the_edit_in_order(self):
        srv = self._serve(True)
        res = keyframe.open_media([
            {"path": str(self.dir / "v002.mp4"), "label": "SHOT020 · ANIM · v002"},
            {"path": str(self.dir / "v001.mp4"), "label": "SHOT010 · ANIM · v001"}], "SEQ010")
        self.assertEqual(res["mode"], "api")
        self.assertEqual(res["siblings"], 0)              # both videos of the folder already asked
        self.assertEqual(srv.calls[0]["cmd"], "initialize")
        imports = [c for c in srv.calls if c["cmd"] == "import_file"]
        self.assertEqual([c["name"] for c in imports], ["SHOT020 · ANIM · v002", "SHOT010 · ANIM · v001"])
        self.assertEqual(len([c for c in srv.calls if c["cmd"] == "insert_element_in_timeline"]), 2)
        self.assertIn("set_active_in_viewer", [c["cmd"] for c in srv.calls])

    def test_single_video_brings_its_folder(self):
        srv = self._serve(True)
        res = keyframe.open_media([{"path": str(self.dir / "v002.mp4")}])
        self.assertEqual(res["siblings"], 1)
        folder_imports = [c for c in srv.calls if c["cmd"] == "import_file" and c["parent_id"]]
        self.assertEqual(Path(folder_imports[0]["file_path"]).name, "v001.mp4")
        # The sibling is available in the project, not in the timeline.
        self.assertEqual(len([c for c in srv.calls if c["cmd"] == "insert_element_in_timeline"]), 1)

    def test_demo_mode_falls_back_to_command_line(self):
        self._serve(False)
        exe = Path(self._tmp.name) / "KeyframePro.exe"
        exe.write_bytes(b"")
        with mock.patch.object(keyframe, "find_executable", return_value=exe), \
             mock.patch.object(keyframe, "_launch") as launch:
            res = keyframe.open_media([{"path": str(self.dir / "v002.mp4")}])
        self.assertEqual(res["mode"], "cli")
        self.assertEqual(res["api"], "not_licensed")
        launch.assert_called_once_with(exe, str(self.dir / "v002.mp4"))
        self.assertIn("première vidéo", res["message"])

    def test_status_reports_demo(self):
        self._serve(False)
        with mock.patch.object(keyframe, "find_executable", return_value=None):
            st = keyframe.status()
        self.assertEqual((st["installed"], st["api"]), (False, "not_licensed"))

    def test_not_installed(self):
        with mock.patch.object(keyframe, "_port_open", return_value=False), \
             mock.patch.object(keyframe, "find_executable", return_value=None):
            with self.assertRaises(keyframe.KeyframeError) as ctx:
                keyframe.open_media([{"path": str(self.dir / "v002.mp4")}])
        self.assertEqual(ctx.exception.code, "not_installed")

    def test_launch_error(self):
        exe = Path(self._tmp.name) / "KeyframePro.exe"
        with mock.patch.object(keyframe, "_port_open", return_value=False), \
             mock.patch.object(keyframe, "find_executable", return_value=exe), \
             mock.patch.object(keyframe, "_launch", side_effect=OSError("denied")):
            with self.assertRaises(keyframe.KeyframeError) as ctx:
                keyframe.open_media([{"path": str(self.dir / "v002.mp4")}])
        self.assertEqual(ctx.exception.code, "launch_failed")

    def test_nothing_openable(self):
        with self.assertRaises(keyframe.KeyframeError) as ctx:
            keyframe.open_media([{"path": str(self.dir / "notes.txt")}])
        self.assertEqual(ctx.exception.code, "nothing_to_open")


if __name__ == "__main__":
    unittest.main()
