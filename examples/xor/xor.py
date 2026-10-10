#!/usr/bin/python
"""
Exclusive-Or test environment.

The exclusive-or function (a.k.a. XOR) is a very simple boolean function.
It is difficult because it is not linearly separable, meaning that implementing
the XOR function using a neural network requires at least one hidden node.
It can not be solved by connecting the inputs directly to the outputs.

The XOR task serves as a starting point for experimenting with evolving neural
networks. It is one of the simplest non-trivial tasks.

+---------+---------+--------------+
| Input 1 | Input 2 | Exclusive Or |
+---------+---------+--------------+
|  false  |  false  |     false    |
|  false  |  true   |     true     |
|  true   |  false  |     true     |
|  true   |  true   |     false    |
+---------+---------+--------------+
"""

from npc_maker import env
import json

tstop = 100
dt    = 0.1

class XorTest(env.SoloAPI):

    def __init__(self, env_spec, mode, **settings):
        self.verbose = (mode == 'graphical')

    def evaluate(self, name, controller):
        """
        Evaluate the given neural network on the XOR task.
        Returns a score in the range [0, 16] where higher is better.
        """
        distance = 0.0
        # Measure all four combinations of the two inputs.
        for input_1 in [0, 1]:
            for input_2 in [0, 1]:
                controller.reset();
                prev = None
                for _ in range(round(tstop / dt)):
                    controller.set_input(0, input_1)
                    controller.set_input(1, input_2)
                    controller.advance(dt)
                    answer = float(controller.get_outputs(0))
                    # Stop the neural network if it reaches steady state.
                    if answer == prev:
                        break
                    else:
                        prev = answer
                # Update the score.
                correct = float(input_1 != input_2)
                answer  = max(0.0, min(1.0, answer))
                distance += abs(answer - correct)
                if self.verbose:
                    env.eprint(f"{input_1} xor {input_2} = {answer}")
        score = (4.0 - distance) ** 2
        if self.verbose: env.eprint(f"score {score}")
        return score

if __name__ == '__main__':
    XorTest.main()
