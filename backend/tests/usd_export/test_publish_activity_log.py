# test_publish_activity_log.py - USD publishes (light / look) reach the activity feed.

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from features.usd_export import publish


class UsdPublishActivity(unittest.TestCase):
    def test_logs_with_project_name(self):
        with mock.patch("features.activity.activity_writer.log_publish") as lp:
            publish.log_usd_publish("ADAM", Path("D:/P/UTAHRAPTOR_PROD"), "CHAR_GEO_UTAH_null_v001.usd", Path("D:/x"))
        lp.assert_called_once_with("ADAM", "CHAR_GEO_UTAH_null_v001.usd", "UTAHRAPTOR_PROD", dest_folder=Path("D:/x"))

    def test_never_fails_the_publish(self):
        with mock.patch("features.activity.activity_writer.log_publish", side_effect=OSError("disk")):
            publish.log_usd_publish("", "P", "f.usd", Path("."))   # no exception


if __name__ == "__main__":
    unittest.main()
