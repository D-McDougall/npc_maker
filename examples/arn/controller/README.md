# Artificial Regulatory Network - Control System

This implements the controller interface for artificial regulatory networks,
as a gRPC server for the `controller.Controller` service (see
`proto/controller.proto`).


## Running

```
arn [--listen <ADDRESS:PORT> | --host <ADDRESS> --port <PORT>] [--temperature <T>]
```

The address must be an IP address and a port, such as `127.0.0.1:47001`, which
is the default. The options `--host` and `--port` are incompatible with
`--listen`. Also see `--help` and `--version`.

The optional `--temperature` argument is a non-negative number, which is used
for every phenome that does not specify its own temperature `T`. The default is
1.0. A temperature in the phenome takes precedence over this argument.


## Phenome Format

The phenome is contains the network parameters for a controller instance. It is
UTF-8 encoded, and it is a single JSON Object with the following attributes:

| Attribute | JSON Type | Description |
| :-------- | :-------: | :---------- |
| T | Number, optional | Temperature, a non-negative scaling factor for the rate of change. If missing, then the `--temperature` argument is used. |
| N | Integer | Number of genes in the network, must be positive |
| W | Array of Numbers | Weights matrix (N x N), flattened in row-major format |
| I | Array of Array of Integer | Indices of input genes |
| O | Array of Array of Integer | Indices of output genes |

I/O are arrays of I/O interfaces, where each interface is an array of indices
into the gene array. Every gene index must be less than N.


## Input / Output

Inputs & Outputs are identified by an `id`, which is an index into the I/O
arrays of the phenome.

Input and output values are 64-bit floating-point numbers, in the `number`
field of `IoValue`. Inputs must be finite. Inputs of type `text` or `blob` are
rejected. Outputs are always numbers. The value of an output is the mean
concentration of its genes, or zero if it has no genes.

