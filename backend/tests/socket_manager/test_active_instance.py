# Several Houdini / Maya open: the instance chosen in FLUX is remembered by the
# backend and followed by the Houdini client (no port in its 57 call sites).

from __future__ import annotations

import unittest

from core import dcc_instances as di
from dcc.houdini.client import HOUDINI_HTTP_PORT, HoudiniClient


class ActiveInstance(unittest.TestCase):
    def tearDown(self) -> None:
        di.set_active_port("Houdini", None)

    def test_houdini_client_follows_the_active_port(self) -> None:
        client = HoudiniClient()
        self.assertEqual(client.port, HOUDINI_HTTP_PORT)
        di.set_active_port("Houdini", HOUDINI_HTTP_PORT + 1)
        self.assertEqual(client.base, f"http://127.0.0.1:{HOUDINI_HTTP_PORT + 1}")
        di.set_active_port("Houdini", None)
        self.assertEqual(client.port, HOUDINI_HTTP_PORT)

    def test_explicit_port_wins(self) -> None:
        di.set_active_port("Houdini", HOUDINI_HTTP_PORT + 2)
        self.assertEqual(HoudiniClient(port=HOUDINI_HTTP_PORT + 5).port, HOUDINI_HTTP_PORT + 5)

    def test_bad_values_refused(self) -> None:
        with self.assertRaises(ValueError):
            di.set_active_port("Houdini", 7001)
        with self.assertRaises(ValueError):
            di.set_active_port("NotADcc", 1)


if __name__ == "__main__":
    unittest.main()
