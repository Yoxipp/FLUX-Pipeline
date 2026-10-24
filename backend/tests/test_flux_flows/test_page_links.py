# P7 / ADR 0068 (2026-10-24): the only page -> flow link left is a data widget reading an
# interface output of a flow (source: flow + output); W_PAGE_LINK_BROKEN when it goes.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from flux_flows import page_links, page_store, pages, validate
from flux_flows.model import parse_flow


def _page() -> pages.Page:
    return pages.parse_page({"page": 1, "id": "daily_render", "label": "Daily", "layout": [
        {"row": [{"id": "files", "kind": "table", "source": {"flow": "daily_render", "output": "files"}}]},
        {"row": [{"id": "render", "kind": "button", "label": "Lancer"}]}]})


def _flow(output: str = "files"):
    return parse_flow({"flux_flow": 2, "name": "daily_render",
                       "interface": {"inputs": [], "outputs": [{"id": output, "type": "list[str]"}]},
                       "nodes": {"m": {"type": "event.manual"}}})


class Links(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_page_links_"))
        self.pages = {"shipped": self.tmp / "shipped", "team": self.tmp / "ext" / "pages", "project": None}

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_index_lists_sources_only(self) -> None:
        page_store.save_page(self.pages, "team", _page(), user="ADAM")
        index = page_links.index(self.pages)
        self.assertEqual([(l["widget"], l["role"], l["output"]) for l in index["daily_render"]],
                         [("files", "source", "files")])

    def test_flow_change_breaks_the_page(self) -> None:
        links = [{"page": "daily_render", "page_label": "Daily", **l} for l in page_links.page_links(_page())]
        self.assertEqual(page_links.broken_by(_flow(), links), [])
        broken = page_links.broken_by(_flow("other"), links)
        self.assertEqual([b["widget"] for b in broken], ["files"])
        codes = [i.code for i in validate.validate(_flow("other"), validate.Env(page_links=links))]
        self.assertIn("W_PAGE_LINK_BROKEN", codes)
