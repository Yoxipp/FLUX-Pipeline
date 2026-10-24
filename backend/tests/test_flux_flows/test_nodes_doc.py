# docs/flows/03_INDEX_NODES.md is the doc shown by the (i) button of a node in the
# Flows editor (app/src/pages/flow_editor/nodeDoc.tsx). Each FLUX node type must have
# exactly one section "### <type> : <Label>" with a description and an example, and
# no section may name a type the registry does not know (renamed or removed node).

from __future__ import annotations

import re
import unittest
from pathlib import Path

from flux_flows.nodes import registry

DOC = Path(__file__).resolve().parents[3] / "docs" / "flows" / "03_INDEX_NODES.md"
# Same heading as NODE_HEADING in nodeDoc.tsx.
HEADING = re.compile(r"^###\s+([a-z][a-z0-9_]*\.[a-z0-9_]+)\s*:\s*(\S+)")


def _sections() -> dict:
    out, current = {}, None
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if re.match(r"^#{1,3}\s", line):
            m = HEADING.match(line)
            current = m.group(1) if m else None
            if current:
                if current in out:
                    raise AssertionError(f"two sections for {current}")
                out[current] = {"label": m.group(2), "body": []}
        elif current:
            out[current]["body"].append(line)
    return out


class NodesDoc(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        registry.ensure_builtin()
        cls.specs = {s.type: s for s in registry.all_nodes() if s.source == "flux"}
        cls.sections = _sections()

    def test_every_flux_node_has_a_section(self) -> None:
        missing = sorted(set(self.specs) - set(self.sections))
        self.assertEqual(missing, [], "add a section to docs/flows/03_INDEX_NODES.md")

    def test_no_section_for_an_unknown_type(self) -> None:
        unknown = sorted(set(self.sections) - set(self.specs))
        self.assertEqual(unknown, [])

    def test_label_matches_the_registry(self) -> None:
        for node_type, sec in self.sections.items():
            if node_type in self.specs:
                self.assertEqual(sec["label"], self.specs[node_type].label, node_type)

    def test_each_section_has_a_description_and_an_example(self) -> None:
        for node_type, sec in self.sections.items():
            body = "\n".join(sec["body"]).strip()
            self.assertTrue(body and not body.startswith("*"), f"{node_type}: description first")
            self.assertIn("Exemple :", body, node_type)


if __name__ == "__main__":
    unittest.main()


# R1 retake 6: the tooltip of a param or port label is its registry doc (doc_fr / doc_en,
# plus type, choices, default and example added by the editor). Every FLUX port and param
# must have one. Exceptions are listed here explicitly, to be emptied.
DOC_EXCEPTIONS: set = set()


class PortsDoc(unittest.TestCase):
    def test_every_port_and_param_has_a_doc(self) -> None:
        registry.ensure_builtin()
        missing, total = [], 0
        for spec in registry.all_nodes():
            if spec.source != "flux":
                continue
            for kind, ports in (("in", spec.inputs), ("out", spec.outputs), ("param", spec.params)):
                for p in ports:
                    total += 1
                    key = f"{spec.type}:{kind}:{p.name}"
                    if key not in DOC_EXCEPTIONS and not (p.doc_fr.strip() and p.doc_en.strip()):
                        missing.append(key)
        self.assertGreater(total, 1000)
        self.assertEqual(missing, [], "add doc_fr / doc_en to these ports (registry port())")

    def test_exec_ports_get_a_default_doc(self) -> None:
        then = next(p for p in registry.get_node("flux.notify").outputs if p.name == "then")
        self.assertIn("Suite", then.doc_fr)
