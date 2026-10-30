# test_team.py - Team page (ADR 0077): channels / reactions / pins journals, presence
# files, attachments copied by the backend, chat messages with channel / thread / files.

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.json_manager as jm
from features.activity import chat_manager as cm
from features.team import files, presence, team_meta
from flux_flows.store import FlowStoreError
from routers import team as team_router

# Pin the JSON backend so a dev config flipped to sqlite does not fail these tests.
from tests.repository._backend import setUpModule, tearDownModule  # noqa: E402,F401


class TeamMeta(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_team_"))
        p = mock.patch.object(team_meta, "folder", lambda project: self.tmp / project / "team")
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _w(self, ops, user="ADAM", lead=False):
        return team_meta.write("ALPHA", ops, user=user, is_lead=lead)

    def test_channels_are_for_leads(self) -> None:
        with self.assertRaises(FlowStoreError) as no:
            self._w([{"op": "put", "fields": {"kind": "channel", "name": "lighting"}}])
        self.assertEqual(no.exception.status, 403)
        rid = self._w([{"op": "put", "fields": {"kind": "channel", "name": "lighting", "call_link": "https://meet.google.com/abc-defg-hij"}}],
                      lead=True)["rids"][0]
        for bad in ({"kind": "channel", "name": "Lighting!"}, {"kind": "channel", "name": "lighting"}):
            with self.assertRaises(FlowStoreError):
                self._w([{"op": "put", "fields": bad}], lead=True)
        for link in ("http://meet.google.com/x", "javascript:alert(1)", "https://a b"):
            with self.assertRaises(FlowStoreError):
                self._w([{"op": "put", "rid": rid, "fields": {"call_link": link}}], lead=True)
        self._w([{"op": "put", "rid": rid, "fields": {"archived": True}}], lead=True)
        rec = team_meta.read("ALPHA")["records"][0]
        self.assertEqual((rec["name"], rec["archived"]), ("lighting", True))

    def test_reactions_by_author_pins_by_leads(self) -> None:
        bob = self._w([{"op": "put", "fields": {"kind": "reaction", "target": "m1", "emoji": "like"}}], user="BOB")["rids"][0]
        self._w([{"op": "put", "fields": {"kind": "reaction", "target": "m1", "emoji": "like"}}], user="ADAM")
        with self.assertRaises(FlowStoreError) as other:
            self._w([{"op": "del", "rid": bob}], user="ADAM")
        self.assertEqual(other.exception.status, 403)
        self._w([{"op": "del", "rid": bob}], user="BOB")
        with self.assertRaises(FlowStoreError):
            self._w([{"op": "put", "fields": {"kind": "pin", "target": "m1"}}])
        self._w([{"op": "put", "fields": {"kind": "pin", "target": "m1"}}], lead=True)
        with self.assertRaises(FlowStoreError):
            self._w([{"op": "put", "fields": {"kind": "reaction", "emoji": "like"}}])
        kinds = sorted(r["kind"] for r in team_meta.read("ALPHA")["records"])
        self.assertEqual(kinds, ["pin", "reaction"])

    def test_channel_access_who_sees_what(self) -> None:
        # 2026-10-30: a channel for some people / roles / departments; leads see all.
        rig = json.dumps({"users": ["bob"], "departments": ["RIG"]})
        self._w([{"op": "put", "fields": {"kind": "channel", "name": "rig", "access": rig}},
                 {"op": "put", "fields": {"kind": "channel", "name": "leads", "access": json.dumps({"roles": ["lead"]})}},
                 {"op": "put", "fields": {"kind": "channel", "name": "open", "access": json.dumps({})}}], lead=True)
        for bad in ('{"roles": ["boss"]}', "not json", '{"users": ["a b"]}'):
            with self.assertRaises(FlowStoreError):
                self._w([{"op": "put", "fields": {"kind": "channel", "name": "x", "access": bad}}], lead=True)
        with self.assertRaises(FlowStoreError):
            self._w([{"op": "put", "fields": {"kind": "channel", "name": "general", "access": rig}}], lead=True)
        roles = {"created_by": None, "members": {"LEA": "lead", "SUP": "supervisor"},
                 "departments": {"EVA": ["RIG"]}, "legacy": False}
        with mock.patch("features.roles.project_roles.read_roles", return_value=roles):
            hidden = {u: team_meta.hidden_channels("ALPHA", u) for u in ("BOB", "EVA", "CLEO", "LEA", "SUP")}
        self.assertEqual(hidden["BOB"], {"leads"})            # named in #rig
        self.assertEqual(hidden["EVA"], {"leads"})            # RIG department
        self.assertEqual(hidden["CLEO"], {"rig", "leads"})
        self.assertEqual((hidden["LEA"], hidden["SUP"]), (set(), set()))


class Presence(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_presence_"))
        for u in ("ADAM", "BOB", "CLEO"):
            (self.tmp / u).mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_own_file_and_online_window(self) -> None:
        presence.write("ADAM", "meeting", "revue lighting", root=self.tmp)
        old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="seconds")
        (self.tmp / "BOB" / presence.FILE).write_text(json.dumps({"status": "available", "at": old}), encoding="utf-8")
        people = {p["user"]: p for p in presence.read_all(root=self.tmp)}
        self.assertEqual((people["ADAM"]["status"], people["ADAM"]["online"], people["ADAM"]["text"]), ("meeting", True, "revue lighting"))
        self.assertEqual((people["BOB"]["status"], people["BOB"]["online"]), ("offline", False))
        self.assertNotIn("CLEO", people)
        with self.assertRaises(ValueError):
            presence.write("ADAM", "busy", root=self.tmp)
        with self.assertRaises(FileNotFoundError):
            presence.write("NOBODY", "away", root=self.tmp)


class Attachments(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_attach_"))
        self.store = self.tmp / "team_files"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_copy_by_content_and_refusals(self) -> None:
        src = self.tmp / "Ref Lighting.PNG"
        src.write_bytes(b"\x89PNG fake")
        got = files.attach(self.store, str(src))
        self.assertEqual((got["name"], got["image"], got["size"]), ("Ref Lighting.PNG", True, 9))
        self.assertRegex(got["file"], r"^[0-9a-f]{20}\.png$")
        self.assertEqual(files.attach(self.store, str(src))["file"], got["file"])
        self.assertEqual(files.file_path(self.store, got["file"]).read_bytes(), b"\x89PNG fake")
        bad = self.tmp / "tool.exe"
        bad.write_bytes(b"MZ")
        for path in (str(bad), str(self.tmp / "missing.pdf")):
            with self.assertRaises(files.AttachError):
                files.attach(self.store, path)
        with self.assertRaises(files.AttachError):
            files.file_path(self.store, "../../secret.png")


class ChatFields(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "ALPHA").mkdir()
        self.mentions = self.tmp / "chatMentions.json"
        jm.invalidate_cache()
        self.notified = []
        for p in (mock.patch.object(cm, "get_project_chat_path", lambda name: self.tmp / name / "teamChat.json"),
                  mock.patch.object(cm, "get_mentions_path", lambda: self.mentions),
                  mock.patch.object(cm, "get_user_list", lambda: ["ADAM", "BOB", "CLEO"]),
                  mock.patch("features.notify.hooks.on_mentions", side_effect=lambda *a: self.notified.append(a))):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_channel_thread_files_and_call_notify(self) -> None:
        cm.send_message("ADAM", "hello", project="ALPHA")
        att = [{"name": "ref.png", "file": "0123456789abcdef0123.png", "size": 3, "image": True}]
        cm.send_message("BOB", "voir ref", project="ALPHA", channel="lighting", attachments=att)
        first = cm.get_messages(project="ALPHA")[0]["id"]
        cm.send_message("CLEO", "ok", project="ALPHA", channel="lighting", reply_to=first)
        cm.send_message("ADAM", "Reunion https://meet.jit.si/flux-alpha", project="ALPHA", notify_all=True)
        msgs = cm.get_messages(project="ALPHA")
        self.assertNotIn("channel", msgs[0])       # general: stored as before, the home chat reads the same file
        self.assertEqual((msgs[1]["channel"], msgs[1]["attachments"][0]["file"]), ("lighting", att[0]["file"]))
        self.assertEqual(msgs[2]["reply_to"], first)
        call = [n for n in self.notified if n[4] == "appel"]
        self.assertEqual(len(call), 1)
        self.assertEqual(sorted(call[0][1]), ["BOB", "CLEO"])

    def test_restricted_channel_mentions_only_its_audience(self) -> None:
        sees = {"ADAM", "BOB"}.__contains__
        cm.send_message("ADAM", "@BOB @CLEO regardez", project="ALPHA", channel="rig", audience=sees)
        cm.send_message("ADAM", "appel", project="ALPHA", channel="rig", notify_all=True, audience=sees)
        mention = [n for n in self.notified if n[2] == "ALPHA" and n[4] != "appel"]
        self.assertEqual(mention[0][1], ["BOB"])
        call = [n for n in self.notified if n[4] == "appel"]
        self.assertEqual(call[0][1], ["BOB"])


class Routes(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_team_routes_"))
        app = FastAPI()
        app.include_router(team_router.router, prefix="/team")
        self.client = TestClient(app)
        self.lead = False
        for p in (mock.patch.object(team_router, "_project_ok", lambda project: None),
                  mock.patch.object(team_meta, "folder", lambda project: self.tmp / "team"),
                  mock.patch.object(files, "files_dir", lambda project: self.tmp / "team_files"),
                  mock.patch("core.config.get_current_user", return_value="ADAM"),
                  mock.patch("features.roles.project_roles.can", side_effect=lambda *a, **k: self.lead)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_meta_rights_and_files(self) -> None:
        r = self.client.post("/team/ALPHA/meta", json={"ops": [{"op": "put", "fields": {"kind": "channel", "name": "comp"}}]})
        self.assertEqual(r.status_code, 403)
        self.lead = True
        self.assertEqual(self.client.post("/team/ALPHA/meta", json={"ops": [{"op": "put", "fields": {"kind": "channel", "name": "comp"}}]}).status_code, 200)
        got = self.client.get("/team/ALPHA/meta").json()
        self.assertEqual((got["records"][0]["name"], got["lead"]), ("comp", True))
        src = self.tmp / "note.pdf"
        src.write_bytes(b"%PDF-1.4")
        att = self.client.post("/team/ALPHA/files", json={"path": str(src)}).json()
        self.assertEqual(self.client.get(f"/team/ALPHA/files/{att['file']}").content, b"%PDF-1.4")
        self.assertEqual(self.client.post("/team/ALPHA/files", json={"path": str(self.tmp / "x.bat")}).status_code, 422)

    def test_hidden_channel_left_out_of_chat_and_meta(self) -> None:
        from routers import activity as activity_router
        app = FastAPI()
        app.include_router(activity_router.router, prefix="/activity")
        client = TestClient(app)
        (self.tmp / "ALPHA").mkdir()
        (self.tmp / "USER").mkdir()
        jm.invalidate_cache()
        roles = {"created_by": None, "members": {}, "departments": {}, "legacy": False}
        for p in (mock.patch.object(cm, "get_project_chat_path", lambda name: self.tmp / name / "teamChat.json"),
                  mock.patch.object(cm, "get_mentions_path", lambda: self.tmp / "chatMentions.json"),
                  mock.patch.object(cm, "get_user_list", lambda: ["ADAM", "BOB"]),
                  mock.patch.object(activity_router, "get_users_dir", lambda: self.tmp / "USER"),
                  mock.patch("features.roles.project_roles.read_roles", return_value=roles),
                  mock.patch("features.notify.hooks.on_mentions")):
            p.start()
            self.addCleanup(p.stop)
        self.lead = True
        only_bob = json.dumps({"users": ["BOB"]})
        self.client.post("/team/ALPHA/meta", json={"ops": [{"op": "put", "fields": {"kind": "channel", "name": "secret", "access": only_bob}}]})
        self.assertEqual(client.post("/activity/chat", json={"project": "ALPHA", "message": "lead", "channel": "secret"}).status_code, 200)
        cm.send_message("BOB", "pour bob", project="ALPHA", channel="secret")
        cm.send_message("BOB", "tout le monde", project="ALPHA")
        self.assertEqual(len(client.get("/activity/chat", params={"project": "ALPHA"}).json()["messages"]), 3)
        self.lead = False                                   # ADAM, a plain artist, not in #secret
        got = client.get("/activity/chat", params={"project": "ALPHA"}).json()["messages"]
        self.assertEqual([m["message"] for m in got], ["tout le monde"])
        self.assertEqual(self.client.get("/team/ALPHA/meta").json()["records"], [])
        r = client.post("/activity/chat", json={"project": "ALPHA", "message": "hop", "channel": "secret"})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
