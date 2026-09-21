# Player #

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




TODO

The player program is a utility for evaluating evolutionary progress. It
dispatches individuals from a population into the environment, but does not
modify the population when individuals die.

The player program always returns a single parent to be cloned and used
without genetic modification.


## Use Cases ##

### Replay Population ###

Dispatch individuals from an evolving population

This can be used to inspect the current state of long-running evolutionary
experiments without interrupting them.


### Replay Leaderboard ###

Dispatch all individuals in the leaderboard with uniform probability

path: population/leaderboard
selection: random


### Replay Hall of Fame ###

Dispatch individuals from recent generations.

When the score of an individual depends on the performance of other
individuals (for example in a competition or tournament) then the scores are
meaningless outside of the context of the individuals being compared.
Although the score may provide enough information to drive evolutionary
improvements, the score does not directly inform us of those improvements.
The hall of fame records the best individuals from each generation, which
allows us to compare generations and measure evolutionary progress.

path: population/hall_of_fame
selection: ranked exponential 100


### Custom Score ###

Evaluate individuals using a custom scoring function

This can be used to select individuals based on metadata attributes, such as
environmental telemetry or epigentic data.

score: `lambda individual: float(indiviual.telemetry['good boy'] + 1)`

