# Vector Test

This is the "Guess the Number" challenge. The phenome is simply a number
(or list of numbers) and the goal is to match a predetermined value.
There are no controller programs in this environment.

This is a basic optimization problem. Every evolutionary algorithm should be
able to solve this, and so this tests every selection and replacement strategy.

## Problem Statement

The problem is to find a randomly generated vector T in R^N  
The genome is a vector G in R^N  
The score is the RMS of (T - G)

All vector components are in the range \[0, 1\]

## Environment

The vector environment generates a deterministic target vector from a supplied
random seed. It repeatedly spawns an individual, decodes the individual's
phenome as a JSON array of numbers, and calculates its RMS error from the
target vector. The error is reported using the Score RPC before the individual
is killed with the Death RPC. This cycle repeats continuously, providing a
minimal environment for testing evolutionary algorithms.

## Genetics

Discuss how to use a large genome with a random projection onto the phenome

Discuss diploidy
