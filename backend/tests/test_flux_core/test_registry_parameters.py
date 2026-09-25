# test_registry_parameters.py — command registry keys + parameter casting.

from __future__ import annotations

import unittest

from flux_core import parameters as params
from flux_core.parameters import ParameterCastError
from flux_core.registry import (
    CommandNotFound,
    _clear_registry,
    get_command,
    is_registered,
    register,
)

from tests.test_flux_core._registry_guard import setUpModule, tearDownModule  # noqa: F401


class RegistryTests(unittest.TestCase):
    def setUp(self):
        _clear_registry()

    def test_register_and_get_by_key(self):
        @register("demo_cmd")
        class Demo:
            pass

        self.assertTrue(is_registered("demo_cmd"))
        self.assertIs(get_command("demo_cmd"), Demo)
        self.assertEqual(Demo.command_key, "demo_cmd")

    def test_unknown_key_raises(self):
        with self.assertRaises(CommandNotFound):
            get_command("nope")

    def test_duplicate_key_rejected(self):
        @register("dup")
        class A:
            pass

        with self.assertRaises(ValueError):
            @register("dup")
            class B:
                pass


class ParameterCastTests(unittest.TestCase):
    def test_scalar_casts(self):
        self.assertEqual(params.cast_value("int", "5"), 5)
        self.assertEqual(params.cast_value("float", "2.5"), 2.5)
        self.assertEqual(params.cast_value("str", 12), "12")
        self.assertTrue(params.cast_value("bool", "yes"))
        self.assertFalse(params.cast_value("bool", "0"))

    def test_list_and_dict(self):
        self.assertEqual(params.cast_value("list", (1, 2)), [1, 2])
        self.assertEqual(params.cast_value("dict", {"a": 1}), {"a": 1})

    def test_bad_cast_raises(self):
        with self.assertRaises(ParameterCastError):
            params.cast_value("int", "abc")

    def test_unknown_type_raises(self):
        with self.assertRaises(ParameterCastError):
            params.cast_value("color", "red")


if __name__ == "__main__":
    unittest.main()
