"""
Solve the XOR environment using the NEAT algorithm.
"""

import mate_selection
import neat
import npc_maker.env
import npc_maker.evo
import time
from pathlib import Path

repo = Path(__file__).parent.parent.parent
environment = repo.joinpath("examples/xor_rs/xor.env")
controller  = repo.joinpath("examples/nn_rs/target/release/nn")

def test_neat():
    # Make the seed.
    genome = neat.NeatGenome()
    in1 = genome.add_node().name
    in2 = genome.add_node().name
    out = genome.add_node().name
    genome.add_edge(in1, out)
    genome.add_edge(in2, out)
    seed = npc_maker.evo.Individual(genome, controller=controller)
    # 
    evo = npc_maker.evo.Evolution(seed,
        population_size = 150,
        speciation_distance = 3.0,
        species_distribution = mate_selection.Proportional(),
        mate_selection = mate_selection.Percentile(0.80),
        leaderboard=1)
    # Make the environments.
    num_threads = 100
    populations = {'xor': evo}
    env_pool = [npc_maker.env.Environment(populations, environment, 'headless')
                for _ in range(num_threads)]
    for env in env_pool:
        env.start()

    # Run the evolutionary algorithm.
    generation = 0
    while evo.get_generation() < 100:
        for env in env_pool:
            env.poll()
            time.sleep(0)
        # 
        if generation < evo.get_generation():
            generation = evo.get_generation()
            best = evo.get_best()
            score = best.get_custom_score()
            print("Generation", generation, "best score", score)
            if score >= 15.0:
                break

            # print(len(evo._species))
            print([len(m) for s,m in evo._species])
            print([s for s,m in evo._species])

    # Check results.
    1/0

if __name__ == "__main__":
    test_neat()
