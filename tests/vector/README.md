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

## Genetics

Discuss how to use a large genome with a random projection onto the phenome

Discuss diploidy
