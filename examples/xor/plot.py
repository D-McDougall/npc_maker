#!/usr/bin/env python3
"""
Plot a controller's output over time for each XOR input pair.
"""

import argparse

import matplotlib.pyplot as plt

from npc_maker.controller import ControllerClient
from npc_maker.individual import Individual


TSTOP = 100
DT = 0.1


def record_outputs(controller, input_1, input_2):
    """Run one XOR input pair and return its output samples and times."""
    controller.reset()
    outputs = []
    times = []
    for step in range(round(TSTOP / DT)):
        controller.set_inputs((input_1, input_2))
        controller.advance(DT)
        outputs.append(float(controller.get_output()))
        times.append((step + 1) * DT)
    return times, outputs


def score_outputs(outputs, input_1, input_2):
    """Return the XOR score contribution for one input pair."""
    answer = max(0.0, min(1.0, outputs[-1]))
    correct = float(input_1 != input_2)
    return abs(answer - correct)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("individual", help="path to the individual's directory")
    args = parser.parse_args()

    individual = Individual.load(args.individual)
    command = tuple(individual.controller)

    fig, axes = plt.subplots(4, 1, sharex=True, figsize=(8, 10),
                             label=f"XOR: {' '.join(command)}")
    distance = 0.0
    try:
        with ControllerClient(command, individual.phenome) as controller:
            for axis, (input_1, input_2) in zip(
                    axes, ((0, 0), (0, 1), (1, 0), (1, 1))):
                times, outputs = record_outputs(controller, input_1, input_2)
                distance += score_outputs(outputs, input_1, input_2)
                axis.set_ylim(0, 1)
                axis.plot(times, outputs)
                axis.set_title(f"Input: ({input_1}, {input_2})")
                axis.set_ylabel("Output")
                axis.grid(True)

        print(f"score {(4.0 - distance) ** 2}")

        axes[-1].set_xlabel("Time")
        fig.tight_layout()
        plt.show()
    finally:
        plt.close(fig)


if __name__ == "__main__":
    main()
