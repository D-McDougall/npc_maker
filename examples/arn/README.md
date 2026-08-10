# Artificial Regulatory Network - Control System

This implements the controller interface for artificial regulatory networks.


## Genome Format

The genome is UTF-8 encoded. It is a single JSON Object, with the following
attributes:

| Attribute | JSON Type | Description |
| :-------- | :-------: | :---------- |
| N | Integer | Number of genes in the network |
| W | Array of Numbers | Weights matrix (N x X), flattened in row-major format |
| I | Array of Array of Number | Indices of input genes |
| O | Array of Array of Number | Indices of output genes |

I/O are arrays of I/O interfaces, where each interface is an array of indices
into the gene array.


## Input / Output

Inputs & Outputs are identified by an `ID` index into the I/O arrays.

Input and output values are UTF-8 strings containing 64-bit floating-point
values in the range `[0, +inf]`.

