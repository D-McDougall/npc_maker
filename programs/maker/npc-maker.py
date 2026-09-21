"""
Simplified router program for testing and debugging the NPC Maker
"""

from npc_maker.env import Environment
from npc_maker.evo import Evolution
from npc_maker.gen import Genetics
from npc_maker.exp import Experiment
import sys

parser = argparse.ArgumentParser(prog='ProgramName',
        description='What the program does')
parser.add_argument('filename')
args = parser.parse_args()

config = Experiment.load(args.filename)

# Start one instance of the environment
env = Enviroment(*config.environment, "graphical")

# Start genetic and evolution programs
evo = {}
gen = {}
for organism in config.organisms:
    evo[organism.body_type] = Evolution(1/0)
    gen[organism.body_type] = Genetics(1/0)

# Main loop
while True:
    for env in environments:
        message = env.poll()
        print(message)
