#!/usr/bin/env python
"""
Simplified router program for testing and debugging the NPC Maker
"""

from npc_maker.utils import eprint
from npc_maker.exp import Experiment
from npc_maker.env import Environment
from npc_maker.indiv import Individual
from npc_maker.evo import Evolution
from npc_maker.gen import Genetics
from os import chdir
import argparse
import time

def main():
    parser = argparse.ArgumentParser(prog='npc-maker.py', description=__doc__)
    parser.add_argument('filename', help='experiment file (.exp)')
    args = parser.parse_args()

    try:
        config = Experiment(args.filename)
    except Exception as error:
        eprint(f"{type(error).__name__} in \"{args.filename}\": {error}")
        exit(5)

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
        message = env.poll()
        if message is None:
            time.sleep(0) # Yield thread
        elif "Spawn" in message:
            body_type = message["Spawn"]
            parent = evo[body_type].spawn()
            genome, phenome = gen[body_type].asex(parent)
            individual = parent.asex(genome)
            env.birth(individual, phenome)
        elif "Death" in message:
            individual = message["Death"]
            evo[individual.get_body_type()].death(individual)
        else:
            raise ValueError(f'unrecognized message "{message}"')

if __name__ == "__main__":
    main()
