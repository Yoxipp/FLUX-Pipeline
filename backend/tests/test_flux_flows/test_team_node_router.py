# P4 (2026-10-23): POST /flows/nodes, the team Python node written by the editor's
# NodeWriterDialog (Team TD, marker required, load error reported, file kept).

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import locations, rights
from flux_flows.nodes import registry
from routers import flows as flows_router


class TeamNodeRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_team_node_"))
        self.boxes = {"flows_team_td": True}
        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        self.client = TestClient(app)
        self._patches = [
            mock.patch.object(locations, "team_nodes_dir", return_value=self.tmp / "nodes"),
            mock.patch.object(rights, "current_rights", side_effect=lambda: rights.rights_from_data("ADAM", self.boxes)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        registry.load_team_nodes(None)   # forget the broken file
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_needs_team_td(self) -> None:
        self.boxes = {"flows_td": True}
        r = self.client.post("/flows/nodes", json={"name": "my_node", "code": "# @flow_node"})
        self.assertEqual(r.status_code, 403)

    def test_refuses_bad_name_and_missing_marker(self) -> None:
        self.assertEqual(self.client.post("/flows/nodes", json={"name": "Bad-Name", "code": "# @flow_node"}).status_code, 400)
        self.assertEqual(self.client.post("/flows/nodes", json={"name": "my_node", "code": "x = 1"}).status_code, 400)
        self.assertFalse((self.tmp / "nodes" / "my_node.py").exists())

    def test_broken_file_is_kept_and_reported(self) -> None:
        r = self.client.post("/flows/nodes", json={"name": "broken_node", "code": "# @flow_node\ndef (:\n"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue((self.tmp / "nodes" / "broken_node.py").is_file())
        self.assertTrue(r.json()["error"])


if __name__ == "__main__":
    unittest.main()
