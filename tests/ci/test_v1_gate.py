"""Requested V1 checks cannot disappear behind a green reusable workflow."""

import json
import os
import unittest
from unittest.mock import patch

from scripts.ci.v1 import main


class V1GateTests(unittest.TestCase):
    def run_gate(self, offline=True, live=True, images=True, auto=False, altered=None):
        needs = {
            "v1-offline": {"result": "success" if offline else "skipped"},
            "v1-local": {"result": "success" if live else "skipped"},
            "images": {"result": "success" if images else "skipped"},
            "image-paths": {"result": "skipped"},
        }
        needs.update(altered or {})
        env = {
            "RUN_OFFLINE": str(offline).lower(),
            "RUN_LIVE": str(live).lower(),
            "IMAGES": str(images).lower(),
            "AUTO_IMAGES": str(auto).lower(),
            "CI_NEEDS": json.dumps(needs),
        }
        with patch.dict(os.environ, env), patch("sys.argv", ["v1", "gate"]):
            main()

    def test_complete_and_selected_success(self):
        self.run_gate()
        self.run_gate(live=False, images=False)

    def test_every_requested_lane_fails_on_missing_cancelled_failed_or_skipped(self):
        for lane in ("v1-offline", "v1-local", "images"):
            for result in (None, "failure", "cancelled", "skipped"):
                with self.subTest(lane=lane, result=result), self.assertRaises(SystemExit):
                    self.run_gate(altered={lane: {"result": result}})

    def test_deselected_lane_must_really_be_skipped(self):
        with self.assertRaises(SystemExit):
            self.run_gate(live=False, altered={"v1-local": {"result": "success"}})

    def test_auto_selection_requires_valid_successful_selector(self):
        for result, changed in (("failure", "true"), ("skipped", None), ("success", "")):
            with self.subTest(result=result, changed=changed), self.assertRaises(SystemExit):
                self.run_gate(
                    images=False,
                    auto=True,
                    altered={"image-paths": {"result": result, "outputs": {"changed": changed}}},
                )
        self.run_gate(
            images=False,
            auto=True,
            altered={"image-paths": {"result": "success", "outputs": {"changed": "false"}}},
        )
        self.run_gate(
            images=False,
            auto=True,
            altered={
                "image-paths": {"result": "success", "outputs": {"changed": "true"}},
                "images": {"result": "success"},
            },
        )


if __name__ == "__main__":
    unittest.main()
