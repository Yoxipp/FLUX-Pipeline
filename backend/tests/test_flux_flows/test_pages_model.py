# P7 (2026-10-24): TOOL page format and its validation (04_PAGES_TOOL §2, §3, §8, ADR 0066).

from __future__ import annotations

import unittest

from flux_flows import pages
from flux_flows.model import parse_flow
from flux_flows.pages import FlowInfo, PageEnv, PageSchemaError


def _daily(**extra) -> dict:
    return {"page": 1, "id": "daily_render", "label": "Daily render", "icon": "film", **extra,
            "layout": [{"folder": {"id": "main", "label": "Copie"}, "children": [
                {"row": [{"id": "dest_folder", "kind": "dir", "label": "Dossier", "default": "$FLUX/DAILY",
                          "bind": {"flow": "daily_render", "param": "dest_folder"}}]},
                {"row": [{"id": "render", "kind": "button", "label": "Lancer maintenant",
                          "on_click": {"flow": "daily_render", "button_id": "render"}}]}]}]}


def _team() -> dict:
    return {"page": 1, "id": "team", "label": "Team", "icon": "users",
            "data": [{"id": "messages", "fields": [{"id": "text", "type": "text"},
                                                   {"id": "channel", "type": "select",
                                                    "options": [{"value": "general"}, {"value": "lighting"}]}]},
                     {"id": "events", "fields": [{"id": "title", "type": "str"}, {"id": "when", "type": "datetime"}]},
                     {"id": "wall", "kind": "board"}],
            "layout": [{"row": [{"id": "chat", "kind": "feed", "source": {"data": "messages"}, "group_by": "channel"},
                                {"id": "who", "kind": "members"}]},
                       {"row": [{"id": "agenda", "kind": "calendar", "source": {"data": "events"}, "title": "title"}]},
                       {"row": [{"id": "board", "kind": "board", "source": {"data": "wall"}}]}]}


def _flow(inputs=None, button="render", outputs=None) -> FlowInfo:
    doc = {"flux_flow": 2, "name": "daily_render",
           "interface": {"inputs": inputs if inputs is not None else
                         [{"id": "dest_folder", "type": "dir", "default": "$FLUX/DAILY"}],
                         "outputs": outputs or []},
           "nodes": {"b": {"type": "event.button", "params": {"button_id": button}}}}
    return FlowInfo(scope="team", flow=parse_flow(doc), active=True, valid=True)


def _codes(doc: dict, env: PageEnv = None) -> list:
    return [i.code for i in pages.validate_page(pages.parse_page(doc), env)]


class Format(unittest.TestCase):
    def test_round_trip_is_stable(self) -> None:
        for doc in (_daily(), _team()):
            page = pages.parse_page(doc)
            text = pages.dump_page(page)
            self.assertEqual(pages.load_page_text(text), page)
            self.assertEqual(pages.dump_page(pages.load_page_text(text)), text)

    def test_scope_is_written_and_ignored(self) -> None:
        text = pages.dump_page(pages.parse_page(_daily()), scope="team")
        self.assertIn("scope: team", text)
        self.assertIsNone(pages.load_page_text(text).scope)

    def test_prop_of_another_kind_is_refused(self) -> None:
        doc = _daily()
        doc["layout"][0]["children"][1]["row"][0]["min"] = 3
        with self.assertRaisesRegex(PageSchemaError, "min"):
            pages.parse_page(doc)

    def test_unknown_key_and_kind_are_refused(self) -> None:
        with self.assertRaises(PageSchemaError):
            pages.parse_page({**_daily(), "colour": "red"})
        doc = _daily()
        doc["layout"][0]["children"][0]["row"][0]["kind"] = "slider"
        with self.assertRaisesRegex(PageSchemaError, "slider"):
            pages.parse_page(doc)

    def test_page_id_rules(self) -> None:
        for bad in ("Daily", "validate", "x"):
            with self.assertRaises(PageSchemaError):
                pages.parse_page({**_daily(), "id": bad})

    def test_board_collection_has_fixed_fields(self) -> None:
        doc = _team()
        doc["data"][2]["fields"] = [{"id": "x", "type": "int"}]
        with self.assertRaisesRegex(PageSchemaError, "board"):
            pages.parse_page(doc)

    def test_source_is_exactly_one(self) -> None:
        doc = _team()
        doc["layout"][0]["row"][0]["source"] = {"data": "messages", "builtin": "users"}
        with self.assertRaisesRegex(PageSchemaError, "source"):
            pages.parse_page(doc)

    def test_members_defaults_to_users(self) -> None:
        page = pages.parse_page(_team())
        who = next(w for w in pages.iter_widgets(page) if w.id == "who")
        self.assertEqual(who.source.builtin, "users")
        self.assertNotIn("source", pages.widget_doc(who))

    def test_suggest_id(self) -> None:
        self.assertEqual(pages.suggest_id("Dossier de destination"), "dossier_de_destination")
        self.assertEqual(pages.suggest_id("Durée (s)"), "duree_s")
        self.assertEqual(pages.suggest_id("render", {"render"}), "render_2")
        self.assertEqual(pages.suggest_id("2 copies"), "w_2_copies")


class Validation(unittest.TestCase):
    def test_daily_render_is_clean(self) -> None:
        self.assertEqual(_codes(_daily(), PageEnv("team", lambda n: _flow())), [])

    def test_team_page_is_clean(self) -> None:
        self.assertEqual(_codes(_team(), PageEnv("team", lambda n: None)), [])

    def test_ids(self) -> None:
        doc = _daily()
        doc["layout"][0]["children"][0]["row"][0]["id"] = "Mon Dossier"
        doc["layout"][0]["children"][1]["row"].append({"id": "render", "kind": "label", "text": "x"})
        issues = pages.validate_page(pages.parse_page(doc))
        bad = next(i for i in issues if i.code == "P_ID_INVALID")
        self.assertEqual(bad.fix["args"]["to"], "mon_dossier")
        self.assertIn("P_ID_DUPLICATE", [i.code for i in issues])

    def test_row_too_wide_and_board_alone(self) -> None:
        doc = _daily()
        doc["layout"][0]["children"][0]["row"] += [{"id": f"l{i}", "kind": "label"} for i in range(4)]
        self.assertIn("P_ROW_TOO_WIDE", _codes(doc))
        team = _team()
        team["layout"][2]["row"].append({"id": "l1", "kind": "label"})
        self.assertIn("P_BOARD_ROW", _codes(team))

    def test_old_flow_links_are_dropped(self) -> None:
        # ADR 0068: on_click and bind of older files are read then dropped; no link check left.
        page = pages.parse_page(_daily())
        text = pages.dump_page(page)
        self.assertNotIn("on_click", text)
        self.assertNotIn("bind", text)
        self.assertEqual(_codes(_daily(), PageEnv("team", lambda n: None)), [])

    def test_scope_mismatch_of_a_source(self) -> None:
        info = _flow(outputs=[{"id": "files", "type": "list[str]"}])
        info.scope = "project"
        doc = _daily()
        doc["layout"].append({"row": [{"id": "files", "kind": "table", "source": {"flow": "daily_render", "output": "files"}}]})
        self.assertIn("P_SCOPE_MISMATCH", _codes(doc, PageEnv("team", lambda n: info)))
        self.assertNotIn("P_SCOPE_MISMATCH", _codes(doc, PageEnv("project", lambda n: info)))

    def test_no_button(self) -> None:
        doc = _daily()
        doc["layout"][0]["children"].pop()
        self.assertIn("P_NO_BUTTON", _codes(doc))

    def test_sources(self) -> None:
        doc = _team()
        doc["layout"][0]["row"][0]["source"] = {"data": "mesages"}
        issues = pages.validate_page(pages.parse_page(doc))
        miss = next(i for i in issues if i.code == "P_SOURCE_NOT_FOUND")
        self.assertEqual(miss.fix["args"]["data"], "messages")
        doc = _team()
        doc["layout"][2]["row"][0]["source"] = {"data": "messages"}
        self.assertIn("P_SOURCE_KIND", _codes(doc))
        doc = _team()
        doc["layout"][1]["row"][0]["date"] = "title"
        self.assertIn("P_FIELD_TYPE", _codes(doc))
        doc = _team()
        doc["layout"][0]["row"][0]["group_by"] = "chanel"
        self.assertIn("P_FIELD_NOT_FOUND", _codes(doc))

    def test_flow_output_source(self) -> None:
        doc = _team()
        doc["layout"][1]["row"][0] = {"id": "last", "kind": "table", "source": {"flow": "daily_render", "output": "files"}}
        self.assertIn("P_OUTPUT_NOT_FOUND", _codes(doc, PageEnv("team", lambda n: _flow())))
        ok = _flow(outputs=[{"id": "files", "type": "list[path]"}])
        self.assertNotIn("P_OUTPUT_NOT_FOUND", _codes(doc, PageEnv("team", lambda n: ok)))

    def test_data_checks(self) -> None:
        doc = _team()
        doc["data"].append({"id": "notes", "fields": []})
        codes = _codes(doc)
        self.assertIn("P_FIELDS_EMPTY", codes)
        self.assertIn("P_DATA_UNUSED", codes)


if __name__ == "__main__":
    unittest.main()
