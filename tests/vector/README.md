# Vector Test

This is a classic "Guess the Number" challenge. The phenome is simply a list of
numbers and the goal is to match a predetermined hidden vector. There are no
controller programs in this environment.

This is a basic optimization problem. Every evolutionary algorithm should be
able to solve this, and so this tests every selection and replacement strategy.

## Problem Statement

### Target

The environment generates a target vector **T** of dimension **N**:

**T = (t₁, t₂, ..., tₙ)**

Each component is a real number in the range:

**0 ≤ tᵢ ≤ 1**

The target is generated deterministically from a supplied random seed.

The target vector is only known to the environment program.

The dimensionality **N** can be increased to make the optimization problem
progressively more difficult. A one-dimensional vector is a classic "guess the
number" problem, while larger vectors test the algorithm's ability to optimize
in multiple dimensions simultaneously.

### Phenome

The phenome is represented as a JSON array of numbers, which should be in the
range `[0, 1]`

### Objective

The objective is to minimize the root-mean-square (RMS) error between the
individual's phenome **P** and the target vector **T**.

The score is calculated using the formula:

**score(P) = 1 - √[(1/N) Σᵢ₌₁ⁿ (pᵢ - tᵢ)²]**

Higher scores are better. A score of **1** represents a perfect solution.

Because every component of both vectors is in the range `[0, 1]`, the score is
also bounded to the range `[0, 1]`.

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
