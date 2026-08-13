# The Evolution Interface #

This chapter describes the interface for evolutionary algorithms.
The purpose of the evolutionary algorithm is to pick which individuals
reproduce. The evolution API has two methods: spawn and death, which mark the
beginning and end of an individual's life cycle.

Individuals are stored in [individual files](/docs/individuals.md).

One instance of the evolution API can serve multiple environments.
Each instance of the API is responsible for exactly one body_type, so
environments with multiple body_types will need multiple instances.


### Spawn ###

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

