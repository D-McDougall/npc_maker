# Artificial Regulatory Network - Genetics

Core genetic algorithms for the artificial regulatory network (ARN) of Banzhaf
(2003), for use with the NPC Maker. This is paired with the controller program
in `examples/arn/controller`.

## Usage

```rust
use arn_genetics::Genome;

// 16 Kibit of random chromosome, 3 input and 2 output interfaces, T = 1.0.
let founder = Genome::new(1 << 14, 3, 2, 1.0);

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

## Serialization

A genome is serialized with [serde](https://serde.rs) and
[postcard](https://docs.rs/postcard). The chromosome is stored in `u32` words, so
the encoding does not depend on the platform.
