# ADR 0081 (2026-10-30): commands typed in the Team chat (`/zip "<folder>"`) start the
# active flows with a TeamCommand node, on the backend of the author. TeamReply answers in
# the thread, signed FLUX; a failed run gets a FLUX answer by itself.
from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from features.activity import chat_manager
from features.team import team_meta
from flux_flows import locations, rights, runs, scheduler, store, team_commands
from flux_flows.model import parse_flow
from routers import flows as flows_router


def _flow(name: str = "zip_cmd", command: str = "zip", channels: str = "", reply: bool = True) -> dict:
    nodes = {"cmd": {"type": "event.team_command", "params": {"name": command, "help": "zippe", "channels": channels}}}
    links = []
    if reply:
        nodes["reply"] = {"type": "flux.team_reply"}
        links = [{"from": "cmd.then", "to": "reply.exec"}, {"from": "cmd.arg", "to": "reply.text"}]
    return {"flux_flow": 2, "name": name, "nodes": nodes, "links": links}


def _zip_flow(name: str = "zip_fail") -> dict:
    return {"flux_flow": 2, "name": name,
            "nodes": {"cmd": {"type": "event.team_command", "params": {"name": "zip"}},
                      "z": {"type": "action.zip_folder"}},
            "links": [{"from": "cmd.then", "to": "z.exec"}, {"from": "cmd.dir", "to": "z.folder"},
                      {"from": "cmd.parent", "to": "z.dest"}]}


class Parse(unittest.TestCase):
    def test_quoted_windows_path_keeps_backslashes(self) -> None:
        name, args, rest = team_commands.parse('/Zip "\\\\serveur\\projet\\SEQ010\\" extra')
        self.assertEqual(name, "zip")
        self.assertEqual(args, ["\\\\serveur\\projet\\SEQ010", "extra"])
        self.assertEqual(rest, '"\\\\serveur\\projet\\SEQ010\\" extra')

    def test_not_a_command(self) -> None:
        self.assertIsNone(team_commands.parse("hello /zip"))
        self.assertIsNone(team_commands.parse("/"))
        self.assertEqual(team_commands.parse("/zip")[1], [])
        self.assertEqual(team_commands.parse("/zip C:\\")[1], ["C:\\"])     # a drive root stays a root

    def test_channels_param(self) -> None:
        self.assertTrue(team_commands.channel_allowed({}, "rendu"))
        self.assertTrue(team_commands.channel_allowed({"channels": "#rendu, anim*"}, "anim_fx"))
        self.assertFalse(team_commands.channel_allowed({"channels": "rendu"}, "general"))


class Run(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_team_cmd_"))
        self.roots = {"shipped": locations.shipped_dir(), "team": self.tmp / "ext" / "flows",
                      "project": self.tmp / "proj" / "flows", "perso": self.tmp / "user" / "flows"}
        self.posted: list = []

        def post(user, message, project=None, path=None, **kw):
            self.posted.append({"user": user, "message": message, "project": project, **kw})
            return f"m{len(self.posted)}"

        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        self._patches = [
            mock.patch.object(locations, "roots_for", side_effect=lambda **_: dict(self.roots)),
            mock.patch.object(rights, "current_rights", side_effect=lambda: rights.rights_from_data("BOB", {})),
            mock.patch.object(runs, "runs_dir", side_effect=lambda scope, **_: self.tmp / scope / "runs"),
            mock.patch.object(scheduler, "_SCHEDULER", None),
            mock.patch.object(chat_manager, "post_message", side_effect=post),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(app).__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _wait(self, run_id: str) -> dict:
        for _ in range(300):
            rec = self.client.get(f"/flows/runs/{run_id}").json()
            if rec["status"] not in ("queued", "running"):
                return rec
            time.sleep(0.01)
        self.fail("run never ended")

    def _active(self, scope: str, doc: dict) -> None:
        store.increment_flow(self.roots, scope, doc["name"], user="ADAM", flow=parse_flow(doc))
        store.set_active(self.roots, scope, doc["name"], True, user="ADAM")

    def _settle(self, count: int) -> None:
        for _ in range(300):
            if len(self.posted) >= count:
                return
            time.sleep(0.01)
        self.fail(f"{count} messages attendus, {len(self.posted)} postes")

    def test_list_and_run_with_reply_in_thread(self) -> None:
        body = {"project": "DEMO", "text": '/zip "D:/proj/SEQ010"'}
        r = self.client.post("/flows/team-commands/run", json=body)
        self.assertEqual(r.status_code, 409)                         # nobody declares /zip yet
        self.assertEqual(self.posted, [])                            # and nothing is posted
        self._active("team", _flow())
        self._active("project", _flow("only_rendu", channels="rendu"))
        store.increment_flow(self.roots, "team", "not_active", user="ADAM", flow=parse_flow(_flow("not_active")))
        got = self.client.get("/flows/team-commands", params={"project": "DEMO"}).json()["commands"]
        self.assertEqual([(c["name"], c["flow"]) for c in got], [("zip", "zip_cmd")])
        self.assertEqual(got[0]["help"], "zippe")
        got = self.client.get("/flows/team-commands", params={"project": "DEMO", "channel": "rendu"}).json()
        self.assertEqual(sorted(c["flow"] for c in got["commands"]), ["only_rendu", "zip_cmd"])

        r = self.client.post("/flows/team-commands/run", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["message_id"], "m1")
        rec = self._wait(r.json()["runs"][0]["run_id"])
        self.assertEqual(rec["status"], "ok", rec)
        self._settle(2)
        command, reply = self.posted
        self.assertEqual((command["user"], command["message"], command["channel"]), ("BOB", body["text"], "general"))
        self.assertEqual((reply["user"], reply["message"]), ("FLUX", "D:/proj/SEQ010"))
        self.assertEqual((reply["reply_to"], reply["via"], reply["channel"]), ("m1", "BOB", "general"))

    def test_reply_stays_in_the_thread_of_the_command(self) -> None:
        self._active("perso", _flow())
        r = self.client.post("/flows/team-commands/run",
                             json={"project": "DEMO", "text": "/zip x", "reply_to": "root1"})
        self._wait(r.json()["runs"][0]["run_id"])
        self._settle(2)
        self.assertEqual(self.posted[0]["reply_to"], "root1")
        self.assertEqual(self.posted[1]["reply_to"], "root1")

    def test_failed_run_answers_by_itself(self) -> None:
        self._active("team", _zip_flow())
        r = self.client.post("/flows/team-commands/run",
                             json={"project": "DEMO", "text": f'/zip "{(self.tmp / "missing").as_posix()}"'})
        rec = self._wait(r.json()["runs"][0]["run_id"])
        self.assertEqual(rec["status"], "error")
        self._settle(2)
        self.assertEqual(self.posted[1]["user"], "FLUX")
        self.assertIn("zip_fail n'a pas abouti", self.posted[1]["message"])
        self.assertEqual(self.posted[1]["reply_to"], "m1")

    def test_zip_lands_next_to_the_folder(self) -> None:
        seq = self.tmp / "proj" / "SEQ010"
        seq.mkdir(parents=True)
        (seq / "shot.txt").write_text("x", encoding="utf-8")
        self._active("team", _zip_flow("zip_ok"))
        r = self.client.post("/flows/team-commands/run", json={"project": "DEMO", "text": f'/zip "{seq}\\"'})
        rec = self._wait(r.json()["runs"][0]["run_id"])
        self.assertEqual(rec["status"], "ok", rec)
        self.assertTrue((self.tmp / "proj" / "SEQ010.zip").is_file())

    def test_shipped_example_zips_and_answers(self) -> None:
        import yaml

        doc = yaml.safe_load((locations.shipped_dir() / "example_team_zip.flow.yml").read_text(encoding="utf-8"))
        self._active("team", {**doc, "name": "team_zip"})
        seq = self.tmp / "proj" / "SEQ020"
        seq.mkdir(parents=True)
        (seq / "a.txt").write_text("x", encoding="utf-8")
        r = self.client.post("/flows/team-commands/run", json={"project": "DEMO", "text": f'/zip "{seq}"'})
        rec = self._wait(r.json()["runs"][0]["run_id"])
        self.assertEqual(rec["status"], "ok", rec)
        self.assertTrue((self.tmp / "proj" / "SEQ020.zip").is_file())
        self._settle(2)
        self.assertEqual(self.posted[1]["message"], f"Zip pret : {seq}.zip")

    def test_hidden_channel_is_refused(self) -> None:
        self._active("team", _flow())
        with mock.patch.object(team_meta, "read", return_value={"records": []}), \
                mock.patch.object(team_meta, "hidden_channels", return_value={"secret"}):
            r = self.client.post("/flows/team-commands/run",
                                 json={"project": "DEMO", "text": "/zip x", "channel": "secret"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.posted, [])

    def test_not_a_command_is_400(self) -> None:
        r = self.client.post("/flows/team-commands/run", json={"project": "DEMO", "text": "zip x"})
        self.assertEqual(r.status_code, 400)


class ManualRun(unittest.TestCase):
    def test_reply_outside_a_command_posts_nothing(self) -> None:
        from flux_flows import engine
        from flux_flows.nodes.contract import NodeContext
        from flux_flows.nodes import flux as flux_nodes

        run = mock.Mock(payload={}, context={"project": "DEMO"})
        with mock.patch.object(chat_manager, "post_message") as post:
            flux_nodes.team_reply(NodeContext(run, "reply"), {"text": "ok"}, {})
        post.assert_not_called()
        run.node_log.assert_called_once()
        self.assertIn("event.team_command", engine.START_EVENTS)


if __name__ == "__main__":
    unittest.main()
