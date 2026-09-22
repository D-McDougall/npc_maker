"""
Simplified router program for testing and debugging the NPC Maker
"""

from npc_maker.exp import Experiment
from npc_maker.env import Environment
from npc_maker.evo import Evolution
from npc_maker.gen import Genetics
from os import chdir
import argparse

def main():
    parser = argparse.ArgumentParser(prog='npc-maker.py', description=__doc__)
    parser.add_argument('filename', help='experiment file (.exp)')
    args = parser.parse_args()

    config = Experiment(args.filename)
    chdir(config.path.parent)

    # Start one instance of the environment
    env = Environment(*config.environment, "graphical")

    # Start genetic and evolution programs
    evo = {}
    gen = {}
    for organism in config.organisms:
        evo[organism.body_type] = Evolution(organism.evolution)
        gen[organism.body_type] = Genetics(organism.genetics)

    # Main loop
    while True:
        for env in environments:
            message = env.poll()
            print(message)
