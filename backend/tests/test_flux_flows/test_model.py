# P1 (2026-10-22): Flow v2 schema and stable YAML emission (01_ARCHITECTURE §2, ADR 0058).

from __future__ import annotations

import copy
import unittest

import yaml

from flux_flows import model
from flux_flows.model import FlowSchemaError, dump_flow, load_flow_text, parse_flow


def _doc() -> dict:
    return {
        "flux_flow": 2, "name": "daily_render", "label": "Daily render",
        "interface": [{"id": "dest_folder", "type": "dir", "label": "Dossier", "default": "$FLUX/DAILY"}],
        "variables": [{"name": "copied", "type": "int", "default": 0}],
        "nodes": {
            "n1": {"type": "event.schedule", "pos": [0, 0], "params": {"time": "22:00", "days": ["mon"]}},
            "n2": {"type": "action.copy", "pos": [320.5, 0], "params": {"dest": "${dest_folder}/x"}, "bypass": True},
        },
        "links": [{"from": "n2.then", "to": "n1.exec"}, {"from": "n1.then", "to": "n2.exec"}],
    }


class Schema(unittest.TestCase):
    def test_valid_document(self) -> None:
        flow = parse_flow(_doc())
        self.assertEqual(flow.interface.inputs[0].id, "dest_folder")
        self.assertTrue(flow.nodes["n2"].bypass)
        self.assertEqual(flow.run_policy, "skip_if_running")

    def test_unknown_field_is_refused_with_its_path(self) -> None:
        doc = _doc()
        doc["nodes"]["n1"]["lavel"] = "x"
        with self.assertRaises(FlowSchemaError) as ctx:
            parse_flow(doc)
        self.assertIn("nodes.n1.lavel", str(ctx.exception))

    def test_derived_fields_are_ignored_on_read(self) -> None:
        doc = dict(_doc(), scope="team", version=7, active=True)
        flow = parse_flow(doc)
        self.assertIsNone(flow.scope)
        self.assertIsNone(flow.version)
        self.assertIsNone(flow.active)

    def test_v1_action_gets_a_migration_message(self) -> None:
        with self.assertRaises(FlowSchemaError) as ctx:
            parse_flow({"name": "publish_maya", "steps": {}})
        self.assertIn("migration", str(ctx.exception))

    def test_bad_values(self) -> None:
        cases = [
            ("flux_flow", 1), ("name", "Bad-Name"), ("name", "catalog"), ("name", "a"),
            ("label", "x" * 81), ("run_policy", "parallel"), ("node_type", "nodot"),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value), self.assertRaises(FlowSchemaError):
                parse_flow(dict(_doc(), **{key: value}))

    def test_reserved_and_duplicate_variable_names(self) -> None:
        for name in ("user", "date", "dest_folder"):
            doc = _doc()
            doc["variables"] = [{"name": name, "type": "str"}]
            with self.subTest(name=name), self.assertRaises(FlowSchemaError):
                parse_flow(doc)

    def test_interface_map_form_with_outputs(self) -> None:
        doc = _doc()
        doc["interface"] = {"inputs": doc["interface"], "outputs": [{"id": "count", "type": "int"}]}
        flow = parse_flow(doc)
        self.assertEqual(flow.interface.outputs[0].id, "count")
        self.assertEqual(load_flow_text(dump_flow(flow)), flow)

    def test_select_needs_options(self) -> None:
        doc = _doc()
        doc["interface"] = [{"id": "soft", "type": "select"}]
        with self.assertRaises(FlowSchemaError):
            parse_flow(doc)
        doc["interface"][0]["options"] = ["maya", "houdini"]
        self.assertEqual(parse_flow(doc).interface.inputs[0].options, ["maya", "houdini"])

    def test_bad_ids_and_link_refs(self) -> None:
        doc = _doc()
        doc["nodes"]["N1"] = doc["nodes"].pop("n1")
        with self.assertRaises(FlowSchemaError):
            parse_flow(doc)
        doc = _doc()
        doc["links"].append({"from": "n1", "to": "n2.exec"})
        with self.assertRaises(FlowSchemaError):
            parse_flow(doc)

    def test_dangling_or_odd_links_are_left_to_validation(self) -> None:
        # ADR 0058, 5: an incompatible link is stored; P4 reports it.
        doc = _doc()
        doc["links"].append({"from": "n9.out", "to": "n2.source"})
        doc["nodes"]["n3"] = {"type": "unknown.node", "pos": [0, 0]}
        self.assertEqual(len(parse_flow(doc).links), 3)

    def test_subnet_holds_its_own_network(self) -> None:
        doc = _doc()
        doc["nodes"]["s1"] = {"type": "subnet", "pos": [0, 300], "nodes": {
            "n1": {"type": "data.value", "pos": [0, 0], "params": {"value": 3}}},
            "links": [{"from": "n1.value", "to": "n1.x"}]}
        flow = parse_flow(doc)
        self.assertIn("n1", flow.nodes["s1"].nodes)
        self.assertEqual(len(list(model.iter_nodes(flow))), 4)
        self.assertEqual(load_flow_text(dump_flow(flow)), flow)

    def test_network_fields_only_on_subnet(self) -> None:
        doc = _doc()
        doc["nodes"]["n1"]["nodes"] = {}
        with self.assertRaises(FlowSchemaError):
            parse_flow(doc)

    def test_size_limits(self) -> None:
        doc = _doc()
        doc["nodes"] = {f"n{i}": {"type": "data.value"} for i in range(model.MAX_NODES + 1)}
        doc["links"] = []
        with self.assertRaises(FlowSchemaError):
            parse_flow(doc)
        with self.assertRaises(FlowSchemaError):
            load_flow_text("x" * (model.MAX_BYTES + 1))

    def test_farm_mode_is_stored_and_reported(self) -> None:
        doc = _doc()
        doc["nodes"]["i1"] = {"type": "session.hou_instance", "params": {"mode": "farm"}}
        doc["nodes"]["f1"] = {"type": "operator.foreach_begin", "params": {"mode": "parallel"}}
        issues = model.v1_limit_issues(parse_flow(doc))
        self.assertEqual([i["node"] for i in issues], ["i1"])


class Emission(unittest.TestCase):
    def test_round_trip_and_stability(self) -> None:
        flow = parse_flow(_doc())
        text = dump_flow(flow)
        self.assertEqual(load_flow_text(text), flow)
        self.assertEqual(dump_flow(load_flow_text(text)), text)

    def test_links_are_sorted(self) -> None:
        text = dump_flow(parse_flow(_doc()))
        self.assertLess(text.index("n1.then"), text.index("n2.then"))

    def test_key_order_and_derived_fields(self) -> None:
        text = dump_flow(parse_flow(_doc()), scope="team", version=3, active=False)
        keys = [ln.split(":")[0] for ln in text.splitlines() if ln and not ln.startswith(" ")]
        self.assertEqual(keys, ["flux_flow", "name", "label", "scope", "version", "active",
                                "run_policy", "interface", "variables", "nodes", "links"])
        self.assertNotIn("&", text)
        self.assertNotIn("!!", text)

    def test_tricky_scalars_survive(self) -> None:
        values = ["yes", "No", "null", "22:00", "a: b", "#x", "- y", "  pad", "multi\nline",
                  "été", "", 1e20, 0.1, -3, True, None, "1.5", "{x}", "[a]"]
        doc = _doc()
        doc["nodes"]["n1"]["params"] = {f"k{i}": v for i, v in enumerate(values)}
        flow = parse_flow(copy.deepcopy(doc))
        reread = yaml.safe_load(dump_flow(flow))
        self.assertEqual(reread["nodes"]["n1"]["params"], doc["nodes"]["n1"]["params"])

    def test_canonical_text_ignores_link_order(self) -> None:
        a = parse_flow(_doc())
        doc = _doc()
        doc["links"].reverse()
        self.assertEqual(dump_flow(a), dump_flow(parse_flow(doc)))


if __name__ == "__main__":
    unittest.main()
