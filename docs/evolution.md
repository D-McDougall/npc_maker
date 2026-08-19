# The Evolution Interface #

This chapter describes the interface for evolutionary algorithms, whose
purpose is to pick which individuals to reproduce.

The interface has only two methods: spawn and death, which mark the beginning
and end of an individual's life cycle. Individuals are stored in
[individual files](/docs/individuals.md) and are identified by file path.

One instance of an evolutionary algorithm can serve multiple environments.
Each instance is responsible for exactly one body_type, so environments with
multiple body_types will need multiple instances.

Evolutionary algorithms execute in isolated computer processes and communicate over
their standard IO channels, which are encoded in UTF-8 unless otherwise stated.

## Standard Input Channel ##

### Spawn ###

TODO: Rewrite this spec with IPC over STDIO/JSON

_method signature:_ `evolution.spawn(self) -> [individual]`

The spawn method returns a list of parent individuals to be mated together to
produce a child. Depending on how many parents are returned take the following
actions:

| Parents | Action |
| --- | --- |
| 0 | Use the initial genetic material |
| 1 | Asexually reproduce the parent |
| 2 | Sexually reproduce the parents |
| 3+ | Unspecified |


### Death ###

_method signature:_ `evolution.death(self, individual)`

The death method notifies the evolutionary algorithm that an individual has died.


## Standard Input Channel ##



## Standard Error Channel ##

The standard error channel is for unformatted diagnostic and error messages.
By default controllers inherit their `stderr` channel from their environment.

In the event that any of the three standard I/O channels closes or emits an error,
then all parties should assume that the controller program is dead and act accordingly.

