# The Evolution Interface #

This chapter describes the interface for evolutionary algorithms, whose
purpose is to pick which individuals to reproduce. The interface has only two
messages: `spawn` and `death`, which mark the start and end of an individual's
life cycle. Individuals are stored in [individual files](/docs/individuals.md)
and are identified by file path.

One instance of an evolutionary algorithm can serve multiple environments.
Each instance is responsible for exactly one body_type, so environments with
multiple body_types will need multiple instances.

Evolutionary algorithms execute in isolated computer processes and communicate
via their standard I/O channels using JSON messages, which are encoded in UTF-8.

## Command Line Invocation ##

Evolution programs are totally specified by their command line invocation.
Both the program name and its arguments are considered part of the
algorithm's identity.

TODO: pass env spec and body type into here?

## Standard Input / Output Channels ##

Evolutionary algorithms receive commands via their standard input channel.
Messages to the evolutionary algorithm are single-line JSON arrays, where the
first value is the name of a command, and the other values are the command's
arguments. Commands are executed in the order they are received. Evolutionary
algorithms terminate when the standard input channel reaches end of file.

| Array Index | JSON Type | Description |
| :---------- | :-------- | :---------- |
| 0 | String | Name of command |
| 1, 2, 3, ... | Any | Arguments for command |

Responses from the evolutionary algorithm to the router are printed to the
standard output channel and are formatted as single-line JSON objects.

### Command: Spawn ###

_message format:_ `["spawn"]`

_response format:_ `["FILE_PATH_1", "FILE_PATH_2", ...]`

The spawn command requests a new individual from the evolutionary algorithm,
which returns a list of parent individuals to be mated together to produce a
child. It accepts zero arguments. It prints a JSON array containing file
paths to ".indiv" files, followed by a newline, to the standard output
channel. Depending on how many parents are returned, the router should take
one of the following actions:

| Parents | Action |
| ------: | ------ |
| 0  | Use the initial genetic material |
| 1  | Asexually reproduce the parent |
| 2  | Sexually reproduce the parents |
| 3+ | Unspecified |


### Command: Death ###

_message format:_ `["death", "FILE_PATH"]`

The death method notifies the evolutionary algorithm that an individual has
died. It accepts one argument: the file path of the dead individual.
It printing nothing to the standard output channel.

The evolutionary algorithm is responsible for maintaining or deleting the
given file.


### Non-Standard Commands ###

Evolutionary algorithms may implement extra / custom commands.
However, it is an error to invoke an undefined command.


## Standard Error Channel ##

The standard error channel is for unformatted diagnostic and error messages.

In the event that any of the three standard I/O channels closes or emits an error,
then all parties should assume that the other program is dead and act accordingly.

