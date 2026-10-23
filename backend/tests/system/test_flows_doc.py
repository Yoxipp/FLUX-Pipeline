"""The Flows manual (resources/manual/FLUX_Flows.html, Settings > Doc > Flows) is built
from docs/flows/*.md by features/system/flows_doc.py: the committed HTML must match."""

import unittest

from features.system import flows_doc


@unittest.skipUnless(flows_doc.DOCS_DIR.is_dir(), "docs/flows/ not shipped (frozen build)")
class FlowsDoc(unittest.TestCase):
    def test_html_is_up_to_date(self):
        self.assertTrue(
            flows_doc.OUT.read_text(encoding="utf-8") == flows_doc.build_html(),
            "docs/flows changed: run `python -m features.system.flows_doc` from backend/ and commit the HTML")

    def test_every_node_section_has_a_card(self):
        page = flows_doc.build_html()
        md = (flows_doc.DOCS_DIR / "03_INDEX_NODES.md").read_text(encoding="utf-8")
        types = [m.group(1) for m in map(flows_doc.NODE_HEADING.match, md.splitlines()) if m]
        self.assertGreater(len(types), 0)
        for node_type in types:
            self.assertIn(f'id="n-{node_type}"', page)
            self.assertIn(f'href="#n-{node_type}"', page)

    def test_inline_and_lists(self):
        self.assertEqual(flows_doc._inline("a `<b>` **c** [d](02_DISPO_ET_A_VENIR.md) [e](x.md)"),
                         'a <code>&lt;b&gt;</code> <b>c</b> <a href="#dispo">d</a> e')
        self.assertEqual(flows_doc._list(["1. one", "   * sub", "2. two"]),
                         "<ol><li>one<ul><li>sub</li></ul></li><li>two</li></ol>")


if __name__ == "__main__":
    unittest.main()
