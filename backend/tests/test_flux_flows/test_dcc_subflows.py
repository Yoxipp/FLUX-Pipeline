# P6a (2026-10-23): DCC nodes shipped as locked subflows (node_type, 01 §12, 03 §8,
# decisions 18 / 19): catalogue specs from the interface, core leaves hidden, the team copy
# (unlock) replaces the shipped node, Revenir au defaut (delete) brings it back.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import dcc_nodes, locations, rights, store
from flux_flows.nodes import registry
from routers import flows as flows_router
from tests.test_flux_flows import _flow_helpers as h

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816


class Specs(unittest.TestCase):
    def setUp(self) -> None:
        dcc_nodes.reset_cache()

    def test_shipped_dcc_nodes_and_their_ports(self) -> None:
        with mock.patch.object(dcc_nodes, "_team_dir", return_value=None):
            idx = dcc_nodes.index()
            prefixes = ("hou", "may", "nk", "sp", "sd", "mvd", "zb", "mari")
            self.assertEqual(sorted(idx), sorted([f"dcc.{p}_publish" for p in prefixes]
                                                 + [f"session.{p}_instance" for p in prefixes]))
            spec = registry.get_node("session.hou_instance")
        self.assertEqual(spec.label, "HoudiniInstance")
        self.assertEqual([p.name for p in spec.params], ["mode", "pick"])
        self.assertEqual(spec.params[0].choices[:2], ("live_connect_or_open", "live_connect_only"))
        self.assertIn("session", [p.name for p in spec.outputs])
        self.assertEqual(spec.licence, {"param": "mode", "equals": "headless"})
        self.assertEqual(spec.subflow, {"name": "hou_instance", "scope": "shipped", "locked": True, "shipped": True})
        publish = registry.get_node("dcc.hou_publish")
        self.assertEqual((publish.session, publish.live_only, publish.effect), ("houdini", True, True))
        self.assertTrue(registry.get_node("dcc.hou_publish_core").internal)

    def test_shipped_flows_are_valid_and_not_listed_in_open(self) -> None:
        from flux_flows import validate

        roots = {"shipped": locations.shipped_dir()}
        for entry in dcc_nodes.index().values():
            self.assertEqual(validate.errors(validate.validate(entry.flow, validate.Env())), [], entry.name)
            self.assertEqual(store.resolve(roots, entry.name), "shipped")
        listed = {e["name"] for e in store.list_flows(roots)}
        self.assertNotIn("hou_instance", listed)
        self.assertIn("publish_houdini", listed)


class Unlock(unittest.TestCase):
    def setUp(self) -> None:
        dcc_nodes.reset_cache()
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_dcc_unlock_"))
        self.team = self.tmp / "ext" / "flows"
        self.roots = {"shipped": locations.shipped_dir(), "team": self.team, "project": None, "perso": None}
        self.boxes = {"flows_team_td": True}
        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        self.client = TestClient(app)
        self._p = [mock.patch.object(locations, "roots_for", side_effect=lambda **_: dict(self.roots)),
                   mock.patch.object(rights, "current_rights",
                                     side_effect=lambda: rights.rights_from_data("ADAM", self.boxes)),
                   mock.patch.object(dcc_nodes, "_team_dir", side_effect=lambda: self.team)]
        for p in self._p:
            p.start()

    def tearDown(self) -> None:
        for p in self._p:
            p.stop()
        dcc_nodes.reset_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unlock_replaces_the_node_and_delete_brings_it_back(self) -> None:
        got = self.client.get("/flows/hou_publish").json()
        self.assertEqual((got["scope"], got["dcc"]), ("shipped", {"node_type": "dcc.hou_publish", "locked": True,
                                                                  "team_copy": False}))
        self.boxes = {"flows_td": True}
        self.assertEqual(self.client.post("/flows/hou_publish/unlock", json={"scope": "team"}).status_code, 403)
        self.boxes = {"flows_team_td": True}
        r = self.client.post("/flows/hou_publish/unlock", json={"scope": "team"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(registry.get_node("dcc.hou_publish").subflow["scope"], "team")
        got = self.client.get("/flows/hou_publish").json()
        self.assertEqual(got["dcc"], {"node_type": "dcc.hou_publish", "locked": False, "team_copy": True})
        # The team edits its copy (a check before the publish): the node follows.
        doc = got["flow"]
        doc["label"] = "houPublish"
        doc["description"] = "copie d'equipe"
        r = self.client.put("/flows/hou_publish", json={"flow": doc, "scope": "team", "base_revision": 1})
        self.assertEqual(r.status_code, 200, r.text)
        dcc_nodes.reset_cache()
        self.assertEqual(registry.get_node("dcc.hou_publish").doc_fr, "copie d'equipe")
        self.assertEqual(self.client.delete("/flows/hou_publish", params={"scope": "team"}).status_code, 200)
        self.assertEqual(registry.get_node("dcc.hou_publish").subflow["scope"], "shipped")

    def test_catalog_lists_dcc_nodes_and_marks_cores(self) -> None:
        nodes = {n["type"]: n for n in self.client.get("/flows/catalog").json()["nodes"]}
        self.assertEqual(nodes["session.hou_instance"]["subflow"]["locked"], True)
        self.assertTrue(nodes["session.hou_instance_core"]["internal"])
        self.assertFalse(nodes["dcc.hou_find_nodes"]["internal"])


if __name__ == "__main__":
    unittest.main()
