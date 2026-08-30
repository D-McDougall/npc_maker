# Example Evolutionary Algorithms & Supporting Tools

This directory contains programs that implement the NPC Maker evolution API.

## Contents

### Evolution Program

This rust program provides a suite of evolutionary algorithms.
Its basic function is to manage a population of individuals.
Individuals are added to the population by the "death" method,
and the state of the population is queried by the "spawn" method
requesting parents for mating.

Features:
* Many strategies for selecting individuals to spawn
* Many strategies for replacing individuals on death
* Persistent save files
* Leaderboard
* Hall of Fame


### Replayer

This python program provides a suite of utilities for spawning from a fully
evolved population.

Features:
* Custom score functions, using python `eval()`
* Many strategies for selecting individuals based on their score
* Serve individuals from many sources:
	+ Current population
	+ Leaderboad
	+ Hall of Fame
	+ Seed genetic material

