# Example Environment: XOR

This very simple environment is useful for testing and as an example of how to
make new environments. It is implemented in both python and rust.

The exclusive-or function (a.k.a. XOR) is a boolean function.
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

