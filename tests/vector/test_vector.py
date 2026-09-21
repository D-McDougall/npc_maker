import subprocess
from pathlib import Path

working_dir = Path(__file__).parent

def run(*args):
	return subprocess.run(*args, check=True)


# TODO: loop over all .exp files in working_dir
# TODO: loop over all router-program implementations (python & rust)

def test_vector():
	experiment_config = working_dir.joinpath("config1.exp")
	run(["npc-maker.py", experiment_config])


if __name__ == "__main__":
	test_vector()
