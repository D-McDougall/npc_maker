from pathlib import Path
import os
import subprocess

# Add the CWD to the system PATH
os.environ["PATH"] = os.pathsep.join([".", os.environ.get("PATH", "")])

def run(*args):
	return subprocess.run(*args, check=True)

working_dir = Path(__file__).parent


# TODO: loop over all .exp files in working_dir
# TODO: loop over all router-program implementations (python & rust)

def test_vector():
	experiment_config = working_dir.joinpath("config1.exp")
	run(["npc-maker.py", experiment_config])


if __name__ == "__main__":
	test_vector()
