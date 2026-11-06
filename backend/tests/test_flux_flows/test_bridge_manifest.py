# P6c (2026-10-23): bridge.yml of the extension bridges (01 §12 "Bridge d'extension"):
# strict manifest, conflicts refused with the reason, a broken bridge isolated, softs
# registry fallback.

from __future__ import annotations

import unittest
from pathlib import Path

from flux_flows.bridges import extension, primitives, softs
from tests.test_flux_flows._ext_helpers import MAX_YML, ExtFolder


def _yml(**over: str) -> str:
    text = MAX_YML.format(target="~/max/scripts")
    for key, value in over.items():
        lines = [ln for ln in text.splitlines() if not ln.startswith(f"{key}:")]
        text = "\n".join(lines) + f"\n{key}: {value}\n"
    return text


class Manifest(unittest.TestCase):
    def test_valid(self) -> None:
        m = extension.parse_manifest(_yml())
        self.assertEqual((m.soft, m.prefix, m.transport, list(m.ports)), ("max", "max", "tcp_json",
                                                                         [7100, 7101, 7102, 7103]))
        self.assertIsNone(m.mailbox)

    def test_unknown_key_and_transport_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "colour"):
            extension.parse_manifest(_yml(colour="red"))
        with self.assertRaisesRegex(ValueError, "transport"):
            extension.parse_manifest(_yml(transport="smoke"))

    def test_bad_values(self) -> None:
        for over, word in (({"prefix": "MAX"}, "prefix"), ({"soft": "3ds"}, "soft"),
                           ({"port_range": "[80, 2]"}, "port_range"), ({"port_range": "[7100, 40]"}, "port_range"),
                           ({"mailbox": "'../x'"}, "mailbox")):
            with self.subTest(over=over), self.assertRaisesRegex(ValueError, word):
                extension.parse_manifest(_yml(**over))

    def test_install_files_stay_in_dcc_side(self) -> None:
        for bad in ("../evil.py", "/etc/x.py", "a/../../b.py"):
            text = _yml().replace("[flux_max_bridge.py]", f"['{bad}']")
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "relatif"):
                extension.parse_manifest(text)

    def test_mailbox_default(self) -> None:
        m = extension.parse_manifest(_yml(transport="file_mailbox"))
        self.assertEqual(m.mailbox, "flux_max_bridge")

    def test_yaml_errors(self) -> None:
        with self.assertRaisesRegex(ValueError, "dictionnaire"):
            extension.parse_manifest("- a\n- b\n")
        with self.assertRaisesRegex(ValueError, "YAML"):
            extension.parse_manifest("soft: [\n")


class Registry(unittest.TestCase):
    def test_conflicts_are_isolated(self) -> None:
        with ExtFolder() as ext:
            ext.add("max", _yml())
            ext.add("xsi", _yml(soft="xsi", prefix="max", port_range="[7102, 2]"))
            ext.add("maya", _yml(soft="maya", prefix="mya", port_range="[7200, 2]"))
            ext.add("ps", _yml(soft="ps", prefix="ps", port_range="[7300, 2]"))
            ext.add("nk2", _yml(soft="nk2", prefix="nkk", port_range="[7400, 2]"))
            ext.add("wrong", _yml(soft="other", prefix="oth", port_range="[7500, 2]"))
            ext.add("broken", "soft: [\n")
            found = {e.soft: e for e in extension.load_all()}
        self.assertTrue(found["max"].ok, found["max"].errors)
        xsi = " ".join(found["xsi"].errors)
        self.assertIn("deja pris par l'extension max", xsi)
        self.assertIn("chevauchent ceux de l'extension max", xsi)
        self.assertIn("deja livre", " ".join(found["maya"].errors))
        self.assertIn("reserve", " ".join(found["ps"].errors))
        self.assertTrue(found["nk2"].ok, found["nk2"].errors)
        self.assertIn("different du nom du dossier", " ".join(found["wrong"].errors))
        self.assertFalse(found["broken"].ok)
        self.assertIsNone(found["broken"].to_dict()["manifest"])

    def test_overlap_with_shipped_ranges(self) -> None:
        from core.constants import DCC_PORT_RANGES

        base = next(iter(DCC_PORT_RANGES.values()))[0]
        with ExtFolder() as ext:
            ext.add("max", _yml(port_range=f"[{base}, 2]"))
            (only,) = extension.load_all()
        self.assertIn("chevauchent", " ".join(only.errors))

    def test_softs_registry_falls_back_to_valid_extensions(self) -> None:
        with ExtFolder() as ext:
            ext.add("max", _yml())
            spec = softs.get("max")
            self.assertEqual((spec.extension, spec.prefix, spec.dcc_key, spec.ping),
                             (True, "max", "ext:max", {"cmd": "ping"}))
            self.assertEqual(list(softs.port_range("max")), [7100, 7101, 7102, 7103])
            self.assertFalse(softs.get("maya").extension)
            ext.add("max", _yml(prefix="hou"))
            with self.assertRaisesRegex(ValueError, "inconnu"):
                softs.get("max")

    def test_scan_pings_each_port_of_the_range(self) -> None:
        from unittest import mock

        with ExtFolder() as ext:
            ext.add("max", _yml())
            with mock.patch.object(primitives, "ping", side_effect=lambda s, p=None: {"ok": p == 7102}):
                self.assertEqual(primitives.scan_ports("max"),
                                 [{"id": "max:7102", "dcc": "max", "port": 7102, "pid": None}])

    def test_find_exe(self) -> None:
        with ExtFolder() as ext:
            exe = ext.tmp / "Autodesk" / "3ds Max 2026" / "3dsmax.exe"
            exe.parent.mkdir(parents=True)
            exe.write_text("", encoding="utf-8")
            ext.add("max", _yml(exe_hints=f"['{ext.tmp.as_posix()}/Autodesk/3ds Max */3dsmax.exe']"))
            self.assertEqual(Path(extension.find_exe(extension.get("max"))), exe)


if __name__ == "__main__":
    unittest.main()
