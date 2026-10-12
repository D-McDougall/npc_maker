"""
Integration test for npc-server.

The server runs the test environment (environment.py), which exercises the
Environment service and checks the Diagnostics service against its own model.
The environment reports the outcome through a result file.

The server is told which address to listen on, so the test can also connect to
its Diagnostics service directly, and then shuts the server down with SIGINT
which must result in a successful exit status.
"""

import json
import sys
import tempfile
import time
from pathlib import Path

from npc_maker.diagnostics import Diagnostics
from npc_maker.individual import Individual


def test_npc_server_py():
    server_test_inner("npc-server.py")

def test_npc_server():
    server_test_inner("npc-server")


def server_test_inner(server_program):
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        population = directory / "population"
        population.mkdir()

        # Create a small replay population for npc-player.
        for score in range(3):
            individual = Individual()
            individual.score = score
            individual.save(population)

        environment = Path(__file__).with_name("environment.py")
        result_file = directory / "result.json"
        config = {
            "name": "npc-server smoke test",
            "environment": [
                sys.executable,
                str(environment),
                "--result", str(result_file),
            ],
            "organisms": [
                {
                    "body_type": "test",
                    "evolution": [
                        "npc-player",
                        str(population),
                        "random",
                    ],
                },
            ],
        }

        config_file = directory / "experiment.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")

        with Diagnostics(
            config_file,
            directory / "server-data",
            verbose=True,
            server_program=server_program,
            timeout=30,
        ) as diagnostics:
            # Wait for the environment to finish its checks.
            deadline = time.monotonic() + 120
            while not result_file.exists():
                if diagnostics.process.poll() is not None:
                    raise AssertionError(
                        "npc-server exited unexpectedly with status "
                        f"{diagnostics.process.returncode}")
                if time.monotonic() > deadline:
                    raise AssertionError("timed out waiting for the environment")
                time.sleep(0.1)

            result = json.loads(result_file.read_text(encoding="utf-8"))
            assert result["ok"], result.get("error")

            # The run must have been non-trivial, or the checks prove little.
            counts = result["counts"]
            assert all(count > 0 for count in counts.values()), counts
            assert result["max_score"] is not None

            # The server should have survived the environment.
            assert diagnostics.process.poll() is None, (
                f"npc-server exited with status {diagnostics.process.returncode}")

            # The server must be serving on the address it was given, and what
            # it reports must still agree with what the environment did.
            assert diagnostics.spawn_count("test") == counts["Spawn"]
            assert diagnostics.death_count("test") == counts["Death"]
            assert diagnostics.living_count("test") == result["living"]
            assert diagnostics.maximum_score("test") == result["max_score"]

        # Exiting the context sends SIGINT and reaps the server.
        assert diagnostics.process.returncode == 0, (
            f"npc-server exited with status {diagnostics.process.returncode}")


if __name__ == "__main__":
    test_server()
