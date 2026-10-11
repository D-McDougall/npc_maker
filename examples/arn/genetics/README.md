# Artificial Regulatory Network - Genetics

Core genetic algorithms for the artificial regulatory network (ARN) of Banzhaf
(2003), for use with the NPC Maker. This is paired with the controller program
in `examples/arn/controller`.

## Usage

```rust
use arn_genetics::Genome;

// Grow a founder from a random 32-bit seed by 9 rounds of duplication, each
// followed by 1% mutation. That is 32 * 2^9 = 16 Kibit of chromosome. The
// genome has 3 input and 2 output interfaces, and T = 1.0.
let founder = Genome::new(9, 0.01, 3, 2, 1.0);

// Flip each chromosome bit with probability 0.1%. The I/O binding sites and the
// temperature are inherited unchanged.
let child = founder.reproduce(0.001);

// Binary round trip, for storing as the `genome` of an Individual.
let bytes = child.to_bytes();
let child = Genome::from_bytes(&bytes).unwrap();

// JSON for the `arn` controller, for the `phenome` of an Individual.
let phenome: Vec<u8> = child.phenome();
```

Every operation that uses randomness has a `_with_rng` variant which takes an
explicit generator, so that experiments and tests can be seeded.

## Initialization

A new genome is grown from a single random word by repeated duplication and
mutation, following Kuo & Banzhaf (2004). They show that growing the bit string
this way, instead of drawing it uniformly at random, gives interaction networks
with scale-free and small-world features. A copy of a well connected gene is
itself well connected, so duplication acts like preferential attachment, and
mutation then rewires the copies.

```text
chromosome <- one uniformly random 32-bit word
repeat `duplications` times:
    chromosome <- chromosome followed by a copy of itself
    for every bit of chromosome:                  # the whole of it, new copy included
        flip the bit with probability `mutation_rate`
```

1. **Seed.** The chromosome starts as one uniformly random 32-bit word.
2. **Duplicate.** The whole chromosome is appended to itself, doubling its
   length. Genes can also appear across the join, where the end of one copy
   meets the start of the next.
3. **Mutate.** Every bit of the doubled chromosome is flipped independently with
   probability `mutation_rate`. This is the same operator as
   `Genome::reproduce`.
4. **Repeat** steps 2 and 3, `duplications` times in all.

The chromosome therefore has `32 * 2^duplications` bits. Kuo & Banzhaf used 12
duplications, which gives 131,072 bits.

Mutation acts on the whole chromosome in every round, the last included, so the
older copies keep diverging while the newer ones are made. Banzhaf (2003) says
only that the duplications are followed by mutations, and does not give the
schedule. Mutating once at the end, or mutating only the new copy in each round,
does not reproduce the gene counts which Kuo & Banzhaf report, and this does.

The I/O binding sites do not take part in any of this. They are drawn uniformly
at random, and inherited without mutation.

### Genes may overlap

Genes are found by scanning the chromosome for the promoter, as described in the
module documentation. As in the literature, genes may overlap: the regulatory
sites and coding region of one gene can contain the promoter of another, and
duplication produces many such genes. Only promoters are kept apart. A scan
resumes just past each promoter it finds, so a longer alternating run such as
`101010101010` is one promoter, not three.

### What to expect

The number of genes is not bounded, and a seed which contains no promoter gives a
genome with few or no genes. Both are deliberate, and follow the literature. The
mutation rate decides which you get. These are the numbers of genes in 400
genomes of 12 duplications each, which you can compare with Figs. 3 to 5 of Kuo &
Banzhaf (2004):

| `mutation_rate` | median genes | genomes with fewer than 125 genes | most genes in any genome |
| --------------- | ------------ | --------------------------------- | ------------------------ |
| 0               | 0            | 87%                               | 8,178                    |
| 0.1%            | 12           | 83%                               | 7,776                    |
| 1%              | 202          | 39%                               | 4,758                    |
| 5%              | 379          | 0%                                | 964                      |

- At 5% the copies are scrambled as fast as they are made. The mean is 395 genes,
  about the same as the 386 of 131,072 uniformly random bits, and the genomes
  are similar to random ones.
- At 1% and below the distribution is heavy-tailed. Most genomes have few genes,
  but a seed which happens to contain a promoter is copied 4,096 times, and can
  leave thousands of genes.
- With no mutation the chromosome is the seed repeated `2^duplications` times, so
  it has genes only if the seed holds a promoter, counting across the join of one
  copy to the next. About 13% of seeds do.

A large genome makes a large phenome, whose weights matrix has `N * N` entries
for `N` genes and I/O sites. Growing a genome is fast: about 2 ms for 131,072
bits in a release build.

## Serialization

A genome is serialized with [serde](https://serde.rs) and
[postcard](https://docs.rs/postcard). The chromosome is stored in `u32` words.

## References

- W. Banzhaf (2003), "On the Dynamics of an Artificial Regulatory Network",
  Advances in Artificial Life, ECAL 2003, LNAI 2801, pp. 217-227.
- W. Banzhaf (2003), "Artificial Regulatory Networks and Genetic Programming",
  in Genetic Programming Theory and Practice, ch. 4, pp. 43-62.
- P. D. Kuo and W. Banzhaf (2004), "Small World and Scale-Free Network Topologies
  in an Artificial Regulatory Network Model".
