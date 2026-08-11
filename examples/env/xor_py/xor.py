#!/usr/bin/python
"""
Exclusive-Or test environment.

The exclusive-or function (a.k.a. XOR) is a very simple boolean function.
It is difficult because it is not linearly separable, meaning that implementing
the XOR function using a neural network requires at least one hidden node.
It can not be solved by only connecting the inputs directly to the outputs.

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


A reasonable initial seed genotype for this environment is to simply connect
both of the inputs directly to the output node. For example:

[{"name": 0, "type": "Node"},
 {"name": 1, "type": "Node"},
 {"name": 2, "type": "Node"},
 {"name": 3, "type": "Edge", "presyn": 0, "postsyn": 3, "weight": 0},
 {"name": 4, "type": "Edge", "presyn": 1, "postsyn": 3, "weight": 0}]

This environment can be solved using only a single hidden node.
For example, here is a hand-crafted solution:

[{"name": 0, "type": "Node", "slope": 2.0, "threshold":  0.5},
 {"name": 1, "type": "Node", "slope": 2.0, "threshold":  0.5},
 {"name": 2, "type": "Node", "slope": 2.0, "threshold":  0.5},
 {"name": 3, "type": "Node", "slope": 2.0, "threshold":  2.0},
 {"name": 4, "type": "Edge", "presyn": 0, "postsyn": 2, "weight": 1.0},
 {"name": 5, "type": "Edge", "presyn": 1, "postsyn": 2, "weight": 1.0},
 {"name": 6, "type": "Edge", "presyn": 3, "postsyn": 2, "weight": -4.0},
 {"name": 7, "type": "Edge", "presyn": 0, "postsyn": 3, "weight": 1.0},
 {"name": 8, "type": "Edge", "presyn": 1, "postsyn": 3, "weight": 1.0}]

"""

from npc_maker import env
import json

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
                # Run the neural network until the neural network reaches a steady state response.
                steadystate = False
                prev = None
                for _ in range(4):
                    controller.set_input(0, input_1)
                    controller.set_input(1, input_2)
                    controller.advance(1.0)
                    answer = float(controller.get_outputs(2))
                    # 
                    if answer == prev:
                        steadystate = True
                        break
                    else:
                        prev = answer
                # Update the score.
                if steadystate:
                    correct = float(input_1 != input_2)
                    answer  = max(0.0, min(1.0, answer))
                    distance += abs(answer - correct)
                    if self.verbose:
                        env.eprint(f"{input_1} xor {input_2} = {answer}")
                else:
                    # Discard neural networks that contain recurrent connections
                    # or have too many hidden layers.
                    if self.verbose: env.eprint("Network unstable, score 0")
                    return 0.0
        score = (4.0 - distance) ** 2
        if self.verbose: env.eprint(f"score {score}")
        return score

if __name__ == '__main__':
    XorTest.main()
