# NK Environment

The NK model defines a fitness landscape over genomes with **N** genes, where
each gene is a real-valued number. Each gene contributes to fitness based on
its own value and the values of **K** other genes. Increasing K adds more
interactions between genes and generally makes the landscape more rugged and
harder to optimize.

This environment creates a reproducible landscape from a random seed. For each
gene it chooses K distinct interacting genes and creates a table of random
contributions for the `2^(K+1)` binary combinations of that gene and its
interactors. The seed determines both the interactions and table values. The
individual's fitness is the mean of the contributions from all N genes; higher
scores are better.

## Phenome

The phenome is a JSON array containing N floating-point values, each in the
range `[0, 1]`. The classic NK model defines genes as binary, so this environment
uses the binary combinations as the corners of each contribution table and
interpolates between them for real-valued inputs. For example, a gene value of
`0` or `1` uses the corresponding binary table entries; values between them
blend the entries according to their distance from each corner. This lets the
environment evaluate continuous-valued phenomes.

There are no controllers in this environment.

## Seed and Reproducibility

The `SEED` argument determines the gene interactions and all contribution-table
values. Running the environment again with the same `N`, `K`, and `SEED`
recreates the same fitness landscape; changing the seed creates a different one.

## Usage

Run the environment with:

```sh
python tests/nk/nk_environment.py --listen HOST:PORT N K SEED
```

`N` must be positive and `K` must satisfy `0 <= K < N`.

## References

Bull, L. (2019). *A Simple Haploid-Diploid Evolutionary Algorithm*.
arXiv:1903.11598. https://doi.org/10.48550/arXiv.1903.11598

