"""
Smoke tests for the npc-server wrapper.
"""

import json
import sys
import tempfile
import time
from pathlib import Path

from npc_maker.diagnostics import Diagnostics


def test_diagnostics_starts_queries_and_stops_server():
    with tempfile.TemporaryDirectory(prefix="npc-test-") as directory:
        directory = Path(directory)
        environment = Path(__file__).with_name("environment.py")
        result_file = directory / "result.json"
        config = {
            "name": "Diagnostics wrapper smoke test",
            "environment": [sys.executable, str(environment), "--result",
                            str(result_file), "--operations", "5"],
            "organisms": [{"body_type": "test"}],
        }
        config_file = directory / "experiment.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")

        with Diagnostics(config_file, directory / "server-data") as diagnostics:
            deadline = time.monotonic() + 30
            while not result_file.exists() and time.monotonic() < deadline:
                assert diagnostics.process.poll() is None
                time.sleep(0.05)
            assert result_file.exists(), "environment did not complete"

            result = json.loads(result_file.read_text(encoding="utf-8"))
            assert result["ok"], result.get("error")
            counts = result["counts"]
            assert diagnostics.living_count("test") == result["living"]
            assert diagnostics.spawn_count("test") == counts["Spawn"]
            assert diagnostics.mate_count("test") == counts["Mate"]
            assert diagnostics.score_count("test") == counts["Score"]
            assert diagnostics.telemetry_count("test") == counts["Telemetry"]
            assert diagnostics.death_count("test") == counts["Death"]
            assert diagnostics.maximum_score("test") == result["max_score"]

        assert diagnostics.process.poll() == 0
