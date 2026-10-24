# P7 (2026-10-24): page <-> flow links by id, rename propagated, W_PAGE_LINK_BROKEN (04_PAGES_TOOL §4).

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from flux_flows import page_links, page_store, pages, store, validate
from flux_flows.model import parse_flow
from flux_flows.store import FlowStoreError


def _page(page_id: str = "daily_render", button: str = "render", flow: str = "daily_render",
          param: str = "dest_folder") -> pages.Page:
    return pages.parse_page({"page": 1, "id": page_id, "label": page_id.title(), "layout": [
        {"row": [{"id": "dest_folder", "kind": "dir", "label": "Dossier", "bind": {"flow": flow, "param": param}}]},
        {"row": [{"id": button, "kind": "button", "label": "Lancer", "on_click": {"flow": flow, "button_id": button}}]}]})


def _flow(buttons=("render",), param: str = "dest_folder", ptype: str = "dir"):
    return parse_flow({"flux_flow": 2, "name": "daily_render",
                       "interface": [{"id": param, "type": ptype, "default": "x"}],
                       "nodes": {f"b{i}": {"type": "event.button", "params": {"button_id": b}}
                                 for i, b in enumerate(buttons)}})


class Links(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_page_links_"))
        self.pages = {"shipped": self.tmp / "shipped", "team": self.tmp / "ext" / "pages", "project": None}
        self.flows = {"shipped": self.tmp / "shipped_flows", "team": self.tmp / "ext" / "flows",
                      "project": None, "perso": None}
        self.flows["shipped"].mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _save(self, page: pages.Page) -> None:
        page_store.save_page(self.pages, "team", page, user="ADAM")

    def test_index_and_buttons(self) -> None:
        self._save(_page())
        idx = page_links.index(self.pages)
        roles = sorted((l["role"], l["widget"]) for l in idx["daily_render"])
        self.assertEqual(roles, [("bind", "dest_folder"), ("button", "render")])
        self.assertEqual(page_links.buttons(self.pages)[0]["button_id"], "render")

    def test_orphan_button(self) -> None:
        info = pages.FlowInfo("team", _flow(("render", "nightly")), active=True)
        issues = page_links.orphan_issues(_page(), lambda n: info, [])
        self.assertEqual([i.code for i in issues], ["P_BUTTON_ORPHAN"])
        self.assertIn("nightly", issues[0].message_fr)
        other = [{"role": "button", "flow": "daily_render", "button_id": "nightly"}]
        self.assertEqual(page_links.orphan_issues(_page(), lambda n: info, other), [])

    def test_flow_change_breaks_the_page(self) -> None:
        self._save(_page())
        links = page_links.all_links(self.pages)
        env = validate.Env(page_links=links)
        codes = [i.code for i in validate.validate(_flow(), env)]
        self.assertNotIn("W_PAGE_LINK_BROKEN", codes)
        broken = [i for i in validate.validate(_flow(("go",), param="out_dir"), env) if i.code == "W_PAGE_LINK_BROKEN"]
        self.assertEqual(len(broken), 2)
        self.assertIn("Daily_Render", broken[0].message_fr)
        typed = [i for i in validate.validate(_flow(ptype="int"), env) if i.code == "W_PAGE_LINK_BROKEN"]
        self.assertEqual(len(typed), 1)

    def test_link_button_adds_the_node_once(self) -> None:
        store.save_flow(self.flows, "team", _flow(()), user="ADAM")
        done = page_links.ensure_button_node(self.flows, "daily_render", "render", user="ADAM")
        self.assertTrue(done["created"])
        self.assertEqual(done["version"], 1)
        flow = store.read_flow(self.flows, "team", "daily_render")["flow"]
        self.assertEqual(page_links.button_ids(flow), ["render"])
        again = page_links.ensure_button_node(self.flows, "daily_render", "render", user="ADAM")
        self.assertEqual((again["created"], again["node"]), (False, done["node"]))
        with self.assertRaises(FlowStoreError):
            page_links.ensure_button_node(self.flows, "missing_flow", "render", user="ADAM")

    def test_rename_button_changes_page_and_flow(self) -> None:
        store.save_flow(self.flows, "team", _flow(), user="ADAM")
        self._save(_page())
        plan = page_links.plan_widget_rename(self.pages, self.flows, "team", "daily_render", "render", "go")
        self.assertEqual([f["kind"] for f in plan["files"]], ["page", "flow"])
        self.assertEqual(plan["flows"][0]["next_version"], 1)
        page_links.apply_widget_rename(self.pages, self.flows, "team", "daily_render", "render", "go", user="ADAM")
        page = page_store.read_page(self.pages, "team", "daily_render")["page"]
        button = [w for w in pages.iter_widgets(page) if w.kind == "button"][0]
        self.assertEqual((button.id, button.on_click.button_id), ("go", "go"))
        flow = store.read_flow(self.flows, "team", "daily_render")["flow"]
        self.assertEqual(page_links.button_ids(flow), ["go"])
        self.assertEqual(store.read_flow(self.flows, "team", "daily_render")["state"]["current"], 1)

    def test_rename_refuses_bad_or_taken_ids(self) -> None:
        self._save(_page())
        for new in ("Go", "dest_folder"):
            with self.assertRaises(FlowStoreError):
                page_links.plan_widget_rename(self.pages, self.flows, "team", "daily_render", "render", new)

    def test_rename_param_follows_in_every_page(self) -> None:
        self._save(_page())
        self._save(_page("other_page", button="again"))
        plan = page_links.plan_param_rename(self.pages, "daily_render", "dest_folder", "out_dir")
        self.assertEqual([f["id"] for f in plan["files"]], ["daily_render", "other_page"])
        with self.assertRaises(FlowStoreError) as no:
            page_links.apply_param_rename(self.pages, "daily_render", "dest_folder", "out_dir", user="ADAM",
                                          scopes_allowed=lambda s: False)
        self.assertEqual(no.exception.status, 403)
        page_links.apply_param_rename(self.pages, "daily_render", "dest_folder", "out_dir", user="ADAM")
        params = {l["param"] for l in page_links.all_links(self.pages) if l["role"] == "bind"}
        self.assertEqual(params, {"out_dir"})


if __name__ == "__main__":
    unittest.main()
