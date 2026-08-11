# The Genetic Interface #

This chapter describes the interface for genetic algorithms, which are
responsible for handling genomes.

The word "**genome**" refers to a complete set of parameters for creating an
AI agent. Each individual has exactly one immutable genome, which is appended
to the individual's file.

Genomes are treated as opaque binary objects outside of genetic algorithms.
Genomes are converted into "**phenomes**" before transmission to controllers.
This decouples the genetic representation from the controller implementation.

Genetic algorithms execute in isolated computer processes and communicate over
the standard IO channels, which are encoded in UTF-8 unless otherwise stated.

## Standard Input Channel ##

Genetic algorithms receive commands over standard input. Genetic algorithms
terminate when their input reaches end of file. Commands are executed in the
order they are received. Commands are formatted as JSON arrays, with the
following structure:

|  Index | JSON Type | Description |
| :----- | :------------- | :-------- |
| 0 | String | Name of command |
| 1, 2, 3, ... | Any | Arguments for command |


### asex ###

_command_ format:_ `["asex", "PARENT_PATH"]`

This function asexually reproduces a genome. It should copy the given genome
and apply mutations.


### sex ###

_command_ format:_ `["sex", "PARENT_1_PATH", "PARENT_2_PATH"]`

This function sexually reproduces two genomes. It should apply crossover and
mutation to the given genomes.


### Non-Standard Commands ###

Genetic algorithms may implement extra functions.


## Standard Output Channel ##

## Standard Error Channel ##

The standard error channel is for unformatted diagnostic and error messages.
By default it should be inherited from the evolutionary algorithm's process.

