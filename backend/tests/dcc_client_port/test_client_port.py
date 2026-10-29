# P6b refactor (2026-10-23): the Nuke, Painter, Designer and Mari clients take a port (one
# instance of the range, Flows session); without it they keep the base port.

from __future__ import annotations

import unittest
from unittest import mock

from core.constants import DCC_PORTS


class ClientPort(unittest.TestCase):
    def _sent_ports(self, module_path: str, make, call) -> list:
        with mock.patch(f"{module_path}.send_json_line", return_value={"ok": True}) as send:
            call(make(None))
            call(make(7032))
        return [c.args[1] for c in send.call_args_list]

    def test_nuke(self) -> None:
        from dcc.nuke.client import NukeClient

        ports = self._sent_ports("dcc.nuke.client", lambda p: NukeClient(port=p), lambda c: c.run("x"))
        self.assertEqual(ports, [DCC_PORTS["Nuke"], 7032])

    def test_painter_designer(self) -> None:
        from dcc.substance_designer.client import SubstanceDesignerClient
        from dcc.substance_painter.client import SubstancePainterClient

        self.assertEqual(self._sent_ports("dcc.substance_painter.client", lambda p: SubstancePainterClient(port=p),
                                          lambda c: c.info()), [DCC_PORTS["SubstanceP"], 7032])
        self.assertEqual(self._sent_ports("dcc.substance_designer.client", lambda p: SubstanceDesignerClient(port=p),
                                          lambda c: c.export({})), [DCC_PORTS["SubstanceD"], 7032])

    def test_mari(self) -> None:
        from dcc.mari.client import MariClient

        self.assertEqual(self._sent_ports("dcc.mari.client", lambda p: MariClient(port=p), lambda c: c.ping()),
                         [DCC_PORTS["Mari"], 7032])


if __name__ == "__main__":
    unittest.main()
