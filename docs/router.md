# Router Program #

The router program orchestrates all other components of the NPC Maker.

## Responsibilities ##

1) The router program is the first program to execute, and performs all
system-wide initialization tasks.

2) The router instantiates environments, evolutionary algorithms, and genetic
algorithms.

3) The router program keeps a record of every living individual. The
environment API implementation updates these records as the environment sends
information.

3) This program routes messages between environments and evolutionary algorithms:
    * Send "spawn" and "death" messages from environments to evolutionary algorithms.
    * Collect 


## Experiment Specification ##

To facilitate reproducible experimentation, 
JSON file with all parameters...

todo: define the structure

