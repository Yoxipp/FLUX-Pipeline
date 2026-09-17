# ADR 0019: one department table, shared by the backend and the Publisher.

from __future__ import annotations

import unittest

from features.usd_export import departments as dp


class DepartmentTable(unittest.TestCase):
    def test_publisher_table_matches_the_backend_rules(self) -> None:
        table = dp.publisher_table()
        self.assertEqual(sorted(table), sorted(dp.LIGHT_EXPORT_TYPES))
        for task, info in table.items():
            expected = dp.ASSET_DEPARTMENTS.get(task, "clip")
            self.assertEqual(info["department"], expected)
            self.assertEqual(sorted(info["include"]), ["anim", "geo", "skel", "uv", "weights"])
            self.assertTrue(info["what"])
        # A clip is not an asset department; every asset department has an order.
        self.assertEqual(table["ANIM"]["department"], "clip")
        for dept in dp.ASSET_DEPARTMENTS.values():
            self.assertIn(dept, dp.DEPARTMENT_ORDER)

    def test_light_export_content_covers_what_it_accepts(self) -> None:
        for task in dp.LIGHT_EXPORT_TYPES:
            self.assertIn(task, dp.LIGHT_EXPORT_CONTENT)


if __name__ == "__main__":
    unittest.main()
