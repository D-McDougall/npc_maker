//! Genetic algorithms for an Artificial Regulatory Network (ARN).
//!
//! The model follows Banzhaf (2003), "On the Dynamics of an Artificial
//! Regulatory Network", and Kuo & Banzhaf (2004), "Small World and Scale-Free
//! Network Topologies in an Artificial Regulatory Network Model".
//!
//! # Chromosome layout
//!
//! The chromosome is a plain bit string. A gene is found by scanning for the
//! promoter, an 8-bit start sequence. The two 32-bit regulatory sites
//! immediately upstream of the promoter belong to that gene, and the five
//! 32-bit words immediately downstream of it are its coding region.
//!
//! ```text
//! | enhancer (32) | inhibitor (32) | promoter (8) | coding region (5 x 32) |
//! ```
//!
//! The gene's protein (the `effector`) is a 32-bit word obtained from the coding
//! region by a bitwise majority vote.
//!
//! Genes may overlap. Only promoters are kept apart. The chromosome is
//! scanned from the left, a promoter is accepted where it first matches, and the
//! scan resumes just past it. A longer alternating run such as `101010101010` is
//! therefore one promoter, not three. A promoter is accepted only if there is room
//! for two full sites upstream of it and a full coding region downstream of it.
//!
//! # Initialization
//!
//! A new genome is grown from a single random word by repeated duplication and
//! mutation, following Kuo & Banzhaf (2004). They show that growing the bit
//! string this way, instead of drawing from a uniform random distribution,
//! gives interaction networks with scale-free and small-world features. A copy
//! of a well connected gene is itself well connected, so duplication acts like
//! preferential attachment, and mutation then rewires the copies.
//!
//! 1. **Seed.** The chromosome starts as one uniformly random 32-bit word.
//! 2. **Duplicate.** The whole chromosome is appended to itself, doubling its
//!    length. Genes can also appear across the join, where the end of one copy
//!    meets the start of the next.
//! 3. **Mutate.** Every bit of the doubled chromosome is flipped independently
//!    with probability `mutation_rate`. This is the same operator as
//!    [`Genome::reproduce`].
//! 4. **Repeat** steps 2 and 3, `duplications` times in all.
//!
//! The chromosome therefore has `32 * 2^duplications` bits. Kuo & Banzhaf used 12
//! duplications, which gives 131,072 bits. Mutation acts on the whole chromosome
//! in every round, the last included, so the older copies keep diverging while the
//! newer ones are made.
//!
//! With `mutation_rate = 0` the chromosome is the seed repeated `2^duplications`
//! times. The rate sets how far the copies diverge. In simulations with 12
//! duplications, a rate of 5% leaves about 390 genes on average, about the same as
//! 131,072 uniformly random bits (about 386), because the copies are scrambled as
//! fast as they are made. A rate of 1% gives a heavy-tailed distribution: roughly
//! 40% of genomes have fewer than 125 genes, while a few have over 2,000, since a
//! seed which happens to contain a promoter is copied 4,096 times.
//!
//! # Network and phenome
//!
//! Every gene is a node in the network. The genome also carries one extra node
//! for each input and each output interface, the *I/O binding sites*. They are
//! drawn at random when the genome is created, and are inherited without
//! mutation. An I/O node has the same three fields as a gene, but instead of the
//! normal regulatory logic it exchanges values with the environment:
//!
//! * An **input** node is a pure source. Its effector regulates genes, but
//!   nothing regulates it, so its concentration is driven only by the input.
//! * An **output** node is a pure sink. Its enhancer and inhibitor sites bind
//!   to proteins, but it regulates nothing, so it only reports.
//!
//! Protein `j` acts on node `i` with strength
//! `(exp(B * (u+ - max u+)) - exp(B * (u- - max u-))) / N`,
//! where `u+` and `u-` are the number of bits in which the effector of `j`
//! differs from the enhancer and from the inhibitor of `i`, `max` is taken over
//! all edges in the network, `B` is [`BETA`], and `N` is the number of nodes.
//! These strengths are the weights matrix `W` of the phenome, which uses the
//! JSON format of the `arn` controller: `{"T", "N", "W", "I", "O"}`.
//!
//! Nodes are numbered with the genes first (in chromosome order), then the
//! input sites, then the output sites.
//!
//! A genome can contain multiple homologous chromosomes. The genes from each
//! chromosome are concatenated in chromosome order when building its phenome.

use bitvec::prelude::*;
use rand::distr::{Bernoulli, Distribution};
use rand::seq::SliceRandom;
use rand::{Rng, RngExt};
use serde::{Deserialize, Serialize};

/// Width of a regulatory site and of a protein, in bits.
pub const SITE_SIZE: usize = 32;

/// The promoter, which marks the start of a gene.
///
/// It is stored least significant bit first, like every word in the chromosome,
/// so reading the chromosome from the left the promoter is `01010101`.
pub const START_SEQ: u8 = 0b10101010;

/// Number of 32-bit words in the coding region of a gene.
pub const GENE_WORDS: usize = 5;

/// Length of one gene in a chromosome, in bits: two regulatory sites, the
/// promoter, and the coding region. See [`Gene::encode`].
pub const GENE_BITS: usize = 2 * SITE_SIZE + u8::BITS as usize + GENE_WORDS * SITE_SIZE;

// Majority vote needs an odd number of voters, so there are never ties.
const _: () = assert!(GENE_WORDS % 2 == 1);

/// Steepness of the exponential which turns a bit-match into a regulatory
/// strength. Larger values give sparser networks.
pub const BETA: f64 = 1.0;

/// Weights with magnitude below this value are omitted from phenomes.
pub const WEIGHT_THRESHOLD: f64 = 1e-9;

/// The raw genetic data. The explicit `u32` store keeps the serialized form the
/// same on every platform, unlike the default `usize`.
pub type Chromosome = BitVec<u32, Lsb0>;

/// Length of the random seed which a chromosome is grown from, in bits.
const SEED_BITS: usize = SITE_SIZE;

fn assert_mutation_rate(rate: f64) {
    assert!(
        (0.0..=1.0).contains(&rate),
        "mutation rate must be in [0, 1], found {rate}"
    );
}

/// Flip each bit independently with probability `rate`.
fn mutate<R: Rng + ?Sized>(chromosome: &mut Chromosome, rng: &mut R, rate: f64) {
    if rate > 0.0 {
        // This flips bit `i` of the chromosome when the `i`th draw succeeds, which is
        // what a loop over bit references would do, but through the raw words, which
        // is much faster. Aligning first makes bit `i` the bit `i % 32` of word `i / 32`.
        chromosome.force_align();
        let len = chromosome.len();
        let words = chromosome.as_raw_mut_slice();
        // `random_bool` builds this same distribution on every call.
        let flip = Bernoulli::new(rate).expect("mutation rate is checked to be a probability");
        for index in 0..len {
            if flip.sample(rng) {
                words[index / SITE_SIZE] ^= 1 << (index % SITE_SIZE);
            }
        }
    }
}

/// Create one chromosome by independently choosing each bit from one of the
/// given homologous chromosomes, with equal probability for each chromosome.
///
/// # Panics
///
/// Panics if `chromosomes` is empty or if their lengths differ.
pub fn crossover(chromosomes: &[Chromosome]) -> Chromosome {
    crossover_with_rng(&mut rand::rng(), chromosomes)
}

/// Like [`crossover`], with an explicit source of randomness. Use a seeded
/// generator for reproducible results.
///
/// Each output bit independently selects one input chromosome uniformly, so
/// this is bit-wise crossover without linkage between neighboring bits.
///
/// # Panics
///
/// Panics if `chromosomes` is empty or if their lengths differ.
pub fn crossover_with_rng<R: Rng + ?Sized>(rng: &mut R, chromosomes: &[Chromosome]) -> Chromosome {
    assert!(!chromosomes.is_empty(), "crossover requires at least one chromosome");
    let len = chromosomes[0].len();
    assert!(
        chromosomes.iter().all(|chromosome| chromosome.len() == len),
        "crossover chromosomes must have equal lengths"
    );

    (0..len)
        .map(|index| chromosomes[rng.random_range(0..chromosomes.len())][index])
        .collect()
}

/// Create a chromosome by taking one contiguous chunk from each homologous
/// chromosome (in random order). Chunk lengths differ by at most one bit when
/// the chromosome length is not divisible by the number of homologues. Their
/// boundaries are evenly spaced around the chromosome, with a uniformly
/// selected phase; the chunk crossing the end wraps around to the beginning.
///
/// # Panics
///
/// Panics if `chromosomes` is empty or if their lengths differ.
pub fn crossover_chunk(chromosomes: &[Chromosome]) -> Chromosome {
    crossover_chunk_with_rng(&mut rand::rng(), chromosomes)
}

/// Like [`crossover_chunk`], with an explicit source of randomness.
pub fn crossover_chunk_with_rng<R: Rng + ?Sized>(
    rng: &mut R,
    chromosomes: &[Chromosome],
) -> Chromosome {
    assert!(!chromosomes.is_empty(), "crossover requires at least one chromosome");
    let len = chromosomes[0].len();
    assert!(
        chromosomes.iter().all(|chromosome| chromosome.len() == len),
        "crossover chromosomes must have equal lengths"
    );
    if len == 0 {
        return Chromosome::new();
    }

    let count = chromosomes.len();
    let average_chunk_len = len / count;
    let offset = rng.random_range(0..=average_chunk_len);
    let mut order: Vec<_> = (0..count).collect();
    order.shuffle(rng);

    (0..len)
        .map(|index| {
            // Rotate the index by the offset.
            let rotated = (index + len - offset) % len;
            // Scaling the rotated index assigns either floor(B/N) or ceil(B/N)
            // bits to each chunk.
            let chunk = ((rotated as u128 * count as u128) / len as u128) as usize;
            chromosomes[order[chunk]][index]
        })
        .collect()
}

/// Grow a chromosome from `seed`: in each of `duplications` rounds, append a copy
/// of the whole chromosome to itself, then mutate every bit at probability `rate`.
fn grow<R: Rng + ?Sized>(rng: &mut R, seed: u32, duplications: usize, rate: f64) -> Chromosome {
    let len = u32::try_from(duplications)
        .ok()
        .and_then(|d| 1usize.checked_shl(d))
        .and_then(|copies| copies.checked_mul(SEED_BITS))
        .unwrap_or_else(|| panic!("{duplications} duplications overflow the chromosome length"));
    let mut chromosome = Chromosome::with_capacity(len);
    chromosome.extend_from_bitslice(seed.view_bits::<Lsb0>());
    for _ in 0..duplications {
        let copy = chromosome.clone();
        chromosome.extend_from_bitslice(&copy);
        mutate(&mut chromosome, rng, rate);
    }
    debug_assert_eq!(chromosome.len(), len);
    chromosome
}

/// Errors from decoding a genome.
#[derive(Debug, thiserror::Error)]
pub enum GenomeError {
    #[error("cannot decode genome: {0}")]
    Decode(#[from] postcard::Error),

    #[error("cannot decode genome: {0} unexpected trailing bytes")]
    TrailingBytes(usize),

    #[error("invalid temperature {0}: must be finite and non-negative")]
    Temperature(f64),
}

/// The complete genetic material of one individual.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Genome {
    /// Scaling factor for the network's rate of change, the `T` of the phenome.
    temperature: f64,

    /// Homologous copies of the raw genetic data. Every chromosome must be
    /// homologous to every other chromosome in this genome. For now, asexual
    /// reproduction mutates only the first chromosome.
    chromosomes: Vec<Chromosome>,

    /// Binding sites for the input interfaces, inherited without mutation.
    inputs: Vec<Gene>,

    /// Binding sites for the output interfaces, inherited without mutation.
    outputs: Vec<Gene>,
}

impl Genome {
    /// Create a genome by growing a random 32-bit seed with `duplications` rounds
    /// of duplication and mutation, with randomly generated I/O binding sites for
    /// `inputs` input interfaces and `outputs` output interfaces.
    ///
    /// The chromosome has `32 * 2^duplications` bits. In each round it is
    /// appended to itself, and then every bit is flipped with probability
    /// `mutation_rate`. See the module documentation for more information.
    ///
    /// # Panics
    ///
    /// Panics unless `0 <= mutation_rate <= 1`, if `temperature` is not finite
    /// and non-negative, or if the chromosome length would overflow `usize`.
    pub fn new(duplications: usize, mutation_rate: f64, inputs: usize, outputs: usize, temperature: f64) -> Self {
        Self::new_with_rng(
            &mut rand::rng(),
            duplications,
            mutation_rate,
            inputs,
            outputs,
            temperature,
        )
    }

    /// Like [`Genome::new`], with an explicit source of randomness. Use a seeded
    /// generator for reproducible results.
    pub fn new_with_rng<R: Rng + ?Sized>(
        rng: &mut R,
        duplications: usize,
        mutation_rate: f64,
        inputs: usize,
        outputs: usize,
        temperature: f64,
    ) -> Self {
        let inputs = (0..inputs).map(|_| Gene::random(rng)).collect();
        let outputs = (0..outputs).map(|_| Gene::random(rng)).collect();
        Self::with_sites(rng, duplications, mutation_rate, inputs, outputs, temperature)
    }

    /// Like [`Genome::new`], using the given I/O binding sites.
    ///
    /// # Panics
    ///
    /// Panics unless `0 <= mutation_rate <= 1`, if `temperature` is not finite
    /// and non-negative, or if the chromosome length would overflow `usize`.
    pub fn with_sites<R: Rng + ?Sized>(
        rng: &mut R,
        duplications: usize,
        mutation_rate: f64,
        inputs: Vec<Gene>,
        outputs: Vec<Gene>,
        temperature: f64,
    ) -> Self {
        assert!(
            temperature.is_finite() && temperature >= 0.0,
            "temperature must be finite and non-negative, found {temperature}"
        );
        assert_mutation_rate(mutation_rate);
        let seed: u32 = rng.random();
        let chromosome = grow(rng, seed, duplications, mutation_rate);
        Self {
            temperature,
            chromosomes: vec![chromosome],
            inputs,
            outputs,
        }
    }

    /// Create a genome from existing homologous chromosomes and I/O binding
    /// sites. All chromosomes must be homologous copies of the same genetic
    /// code. The first chromosome is used for asexual reproduction for now.
    ///
    /// # Panics
    ///
    /// Panics if `chromosomes` is empty or if `temperature` is not finite and
    /// non-negative.
    pub fn from_chromosomes(
        chromosomes: Vec<Chromosome>,
        inputs: Vec<Gene>,
        outputs: Vec<Gene>,
        temperature: f64,
    ) -> Self {
        assert!(!chromosomes.is_empty(), "a genome must contain a chromosome");
        assert!(
            temperature.is_finite() && temperature >= 0.0,
            "temperature must be finite and non-negative, found {temperature}"
        );
        Self {
            temperature,
            chromosomes,
            inputs,
            outputs,
        }
    }

    /// Create a child by copying this genome and flipping each bit of the
    /// first chromosome independently, with probability `mutation_rate`. Other
    /// homologs, the I/O binding sites, and the temperature are inherited
    /// unchanged.
    ///
    /// # Panics
    ///
    /// Panics unless `0 <= mutation_rate <= 1`.
    pub fn reproduce(&self, mutation_rate: f64) -> Self {
        self.reproduce_with_rng(&mut rand::rng(), mutation_rate)
    }

    /// Like [`Genome::reproduce`], with an explicit source of randomness.
    pub fn reproduce_with_rng<R: Rng + ?Sized>(&self, rng: &mut R, mutation_rate: f64) -> Self {
        assert_mutation_rate(mutation_rate);
        let mut child = self.clone();
        for chromosome in child.chromosomes.iter_mut() {
            mutate(chromosome, rng, mutation_rate);
        }
        child
    }

    /// Create a gamete by crossing over this genome's homologous chromosomes,
    /// then mutating the resulting chromosome at `mutation_rate`.
    pub fn gamete(&self, mutation_rate: f64) -> Chromosome {
        self.gamete_with_rng(&mut rand::rng(), mutation_rate)
    }

    /// Like [`Genome::gamete`], with an explicit source of randomness.
    pub fn gamete_with_rng<R: Rng + ?Sized>(&self, rng: &mut R, mutation_rate: f64) -> Chromosome {
        assert_mutation_rate(mutation_rate);
        let mut gamete = crossover_chunk_with_rng(rng, &self.chromosomes);
        mutate(&mut gamete, rng, mutation_rate);
        gamete
    }

    /// Build the phenome, in the JSON format of the `arn` controller.
    ///
    /// See the module documentation for how the genome becomes a network. The
    /// number of nodes `N` is zero only if the chromosome has no genes and the
    /// genome has no I/O sites, which the controller will reject.
    pub fn phenome(&self) -> Vec<u8> {
        let genes = self.genes();
        let (n_genes, n_inputs) = (genes.len(), self.inputs.len());
        let n = n_genes + n_inputs + self.outputs.len();
        let nodes: Vec<&Gene> = genes.iter().chain(&self.inputs).chain(&self.outputs).collect();

        // Edges run from a source node's protein to a target node's sites.
        // Inputs are never targets and outputs are never sources.
        let is_input = |node: usize| (n_genes..n_genes + n_inputs).contains(&node);
        let is_output = |node: usize| node >= n_genes + n_inputs;
        let is_edge = |target: usize, source: usize| !is_input(target) && !is_output(source);

        // How many bits differ between the source's protein and each site.
        let mut enhance = vec![0u32; n * n];
        let mut inhibit = vec![0u32; n * n];

        for target in 0..n {
            for source in 0..n {
                if is_edge(target, source) {
                    let protein = nodes[source].effector;
                    let e = (protein ^ nodes[target].enhancer).count_ones();
                    let i = (protein ^ nodes[target].inhibitor).count_ones();
                    enhance[target * n + source] = e;
                    inhibit[target * n + source] = i;
                }
            }
        }

        let weight = |matches: u32| (BETA * (f64::from(matches) - SITE_SIZE as f64)).exp();
        let mut w = vec![0.0; n * n];
        for target in 0..n {
            for source in 0..n {
                if is_edge(target, source) {
                    let k = target * n + source;
                    w[k] = (weight(enhance[k]) - weight(inhibit[k])) / n as f64;
                }
            }
        }

        #[derive(Debug, Serialize)]
        #[allow(non_snake_case)]
        struct Phenome {
            T: f64,
            N: usize,
            W: Vec<(usize, usize, f64)>,
            I: Vec<Vec<usize>>,
            O: Vec<Vec<usize>>,
        }
        let phenome = Phenome {
            T: self.temperature,
            N: n,
            W: w.into_iter()
                .enumerate()
                .filter_map(|(index, value)| (value.abs() >= WEIGHT_THRESHOLD).then_some((index / n, index % n, value)))
                .collect(),
            I: (n_genes..n_genes + n_inputs).map(|node| vec![node]).collect(),
            O: (n_genes + n_inputs..n).map(|node| vec![node]).collect(),
        };
        serde_json::to_vec(&phenome).expect("phenome is always serializable")
    }

    /// Serialize to binary.
    pub fn to_bytes(&self) -> Vec<u8> {
        postcard::to_allocvec(self).expect("genome is always serializable")
    }

    /// Deserialize from binary, as written by [`Genome::to_bytes`].
    pub fn from_bytes(bytes: &[u8]) -> Result<Self, GenomeError> {
        let (genome, rest): (Self, _) = postcard::take_from_bytes(bytes)?;
        if !rest.is_empty() {
            return Err(GenomeError::TrailingBytes(rest.len()));
        }
        if !(genome.temperature.is_finite() && genome.temperature >= 0.0) {
            return Err(GenomeError::Temperature(genome.temperature));
        }
        Ok(genome)
    }

    /// All homologous chromosomes in this genome.
    pub fn chromosomes(&self) -> &[BitVec<u32, Lsb0>] {
        &self.chromosomes
    }

    /// Binding sites of the input interfaces.
    pub fn inputs(&self) -> &[Gene] {
        &self.inputs
    }

    /// Binding sites of the output interfaces.
    pub fn outputs(&self) -> &[Gene] {
        &self.outputs
    }

    /// The temperature, which scales the network's rate of change.
    pub fn temperature(&self) -> f64 {
        self.temperature
    }

    /// The genes found in the chromosomes, in node order: every gene of the
    /// first chromosome in chromosome order, then those of the second, and so on.
    ///
    /// This does not include the I/O binding sites, see [`Genome::inputs`] and
    /// [`Genome::outputs`].
    pub fn genes(&self) -> Vec<Gene> {
        self.chromosomes
            .iter()
            .flat_map(|chromosome| Gene::find_all(chromosome))
            .collect()
    }

    /// Total number of genes across all chromosomes.
    pub fn num_genes(&self) -> usize {
        self.chromosomes.iter().map(|c| Gene::find_all(c).len()).sum()
    }
}

/// A network node: two regulatory sites and the protein they respond to.
///
/// Genes are read from the chromosome. The I/O binding sites are random.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Gene {
    /// Proteins which match this site increase the node's concentration.
    pub enhancer: u32,

    /// Proteins which match this site decrease the node's concentration.
    pub inhibitor: u32,

    /// The protein this node produces.
    pub effector: u32,
}

impl Gene {
    /// Create a gene or an I/O binding site from its three fields.
    pub fn new(enhancer: u32, inhibitor: u32, effector: u32) -> Self {
        Self {
            enhancer,
            inhibitor,
            effector,
        }
    }

    /// All three fields are random bits.
    pub fn random<R: Rng + ?Sized>(rng: &mut R) -> Self {
        Self::new(rng.random(), rng.random(), rng.random())
    }

    /// Write this gene as [`GENE_BITS`] bits of chromosome, the inverse of
    /// [`Gene::find_all`]:
    ///
    /// ```text
    /// | enhancer (32) | inhibitor (32) | promoter (8) | effector x 5 (5 x 32) |
    /// ```
    ///
    /// The coding region is five copies of the effector. The effector is the
    /// bitwise majority of the coding region, and the majority of five equal words
    /// is that word, so [`Gene::find_all`] reads the same effector back.
    ///
    /// Concatenating the encodings of several genes gives a chromosome which
    /// holds those genes, in that order, *provided that* the scan finds no other
    /// promoter. The scan accepts a promoter wherever the 8 bits match, and
    /// there is room for a full coding region after it, which includes the sites
    /// and coding regions of the genes before the last. A word with a run of 8
    /// alternating bits, such as the effector `0x5555_5555`, therefore makes
    /// extra genes if other genes follow it. Check the result with
    /// [`Gene::find_all`] or [`Genome::genes`].
    pub fn encode(&self) -> Chromosome {
        let mut chromosome = Chromosome::with_capacity(GENE_BITS);
        chromosome.extend_from_bitslice(self.enhancer.view_bits::<Lsb0>());
        chromosome.extend_from_bitslice(self.inhibitor.view_bits::<Lsb0>());
        chromosome.extend_from_bitslice(START_SEQ.view_bits::<Lsb0>());
        for _ in 0..GENE_WORDS {
            chromosome.extend_from_bitslice(self.effector.view_bits::<Lsb0>());
        }
        debug_assert_eq!(chromosome.len(), GENE_BITS);
        chromosome
    }

    /// Scan a chromosome for genes, in order. Genes may overlap, but promoters
    /// may not: after a promoter the scan resumes just past it.
    ///
    /// A promoter is accepted only if there is room for two full regulatory sites
    /// before it and a full coding region after it. See the module documentation.
    pub fn find_all(sequence: &BitSlice<u32, Lsb0>) -> Vec<Self> {
        let promoter_len = u8::BITS as usize;
        let body_len = GENE_WORDS * SITE_SIZE;
        let mut genes = vec![];
        // The first promoter can be no earlier than two sites into the sequence.
        let mut index = 2 * SITE_SIZE;
        // The promoter must be followed by a complete coding region.
        while index + promoter_len + body_len <= sequence.len() {
            if sequence[index..index + promoter_len].load_le::<u8>() == START_SEQ {
                let body = index + promoter_len;
                let site = |at: usize| -> u32 { sequence[at..at + SITE_SIZE].load_le() };
                let words: [u32; GENE_WORDS] = std::array::from_fn(|w| site(body + w * SITE_SIZE));
                // Majority vote on every bit position.
                let effector = (0..SITE_SIZE).fold(0u32, |protein, bit| {
                    let ones = words.iter().filter(|word| (*word >> bit) & 1 == 1).count();
                    protein | (u32::from(ones > GENE_WORDS / 2) << bit)
                });
                genes.push(Gene {
                    enhancer: site(index - 2 * SITE_SIZE),
                    inhibitor: site(index - SITE_SIZE),
                    effector,
                });
                // Genes may overlap, but promoters must not overlap, so resume
                // right after the promoter.
                index = body;
            } else {
                index += 1;
            }
        }
        genes
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rand::SeedableRng;
    use rand::rngs::StdRng;

    /// A fixed seed, so that these stochastic tests are reproducible.
    fn rng() -> StdRng {
        StdRng::seed_from_u64(0xA2_4E)
    }

    const ENHANCER: u32 = 0xFFFF_0000;
    const INHIBITOR: u32 = 0x00FF_FF00;
    const BODY: [u32; GENE_WORDS] = [0x0000_FFFF, 0x00FF_00FF, 0x0F0F_0F0F, 0x3333_3333, 0x5555_5555];

    /// Bits before the promoter and after it, for a gene to fit around it.
    const UPSTREAM: usize = 2 * SITE_SIZE;
    const DOWNSTREAM: usize = GENE_WORDS * SITE_SIZE;

    /// A chromosome holding exactly one gene, at an unaligned offset, followed
    /// by `trailing` zero bits. The zeros cannot contain a promoter.
    fn one_gene(trailing: usize) -> Chromosome {
        let mut chromosome = Chromosome::new();
        chromosome.resize(5, false);
        for word in [ENHANCER, INHIBITOR] {
            chromosome.extend_from_bitslice(word.view_bits::<Lsb0>());
        }
        chromosome.extend_from_bitslice(START_SEQ.view_bits::<Lsb0>());
        for word in BODY {
            chromosome.extend_from_bitslice(word.view_bits::<Lsb0>());
        }
        chromosome.resize(chromosome.len() + trailing, false);
        chromosome
    }

    /// Uniformly random bits, which is what the chromosome of a genome used to be.
    fn random_chromosome<R: Rng + ?Sized>(rng: &mut R, bits: usize) -> Chromosome {
        let mut chromosome = Chromosome::from_vec((0..bits.div_ceil(SITE_SIZE)).map(|_| rng.random()).collect());
        chromosome.truncate(bits);
        chromosome
    }

    /// The gene scan again, in plain integer arithmetic on a `Vec<bool>`, as an
    /// independent check of `Gene::find_all`.
    fn reference_genes(bits: &[bool]) -> Vec<Gene> {
        let word = |at: usize| (0..SITE_SIZE).fold(0u32, |w, bit| w | (u32::from(bits[at + bit]) << bit));
        let promoter: Vec<bool> = (0..8).map(|bit| (START_SEQ >> bit) & 1 == 1).collect();
        let mut genes = vec![];
        let mut at = UPSTREAM;
        while at + promoter.len() + DOWNSTREAM <= bits.len() {
            if bits[at..at + promoter.len()] == promoter[..] {
                let body: Vec<u32> = (0..GENE_WORDS)
                    .map(|w| word(at + promoter.len() + w * SITE_SIZE))
                    .collect();
                let mut effector = 0u32;
                for bit in 0..SITE_SIZE {
                    if body.iter().filter(|w| (*w >> bit) & 1 == 1).count() * 2 > GENE_WORDS {
                        effector |= 1 << bit;
                    }
                }
                genes.push(Gene::new(word(at - UPSTREAM), word(at - SITE_SIZE), effector));
                at += promoter.len();
            } else {
                at += 1;
            }
        }
        genes
    }

    /// A zero chromosome, which has no promoters, with an alternating run of
    /// `run` bits starting at `at`. The run is a promoter wherever it holds 8
    /// consecutive alternating bits, starting with the first bit of `START_SEQ`.
    fn with_run(len: usize, at: usize, run: usize) -> Chromosome {
        let mut chromosome = Chromosome::repeat(false, len);
        for offset in 0..run {
            chromosome.set(at + offset, (START_SEQ >> (offset % 2)) & 1 == 1);
        }
        chromosome
    }

    /// The number of genes in each of `n` genomes of `duplications` rounds at
    /// `rate`. Growing a genome is slow in a debug build, so the genomes are shared
    /// out between threads. Each has its own seed, so the result is the same
    /// whatever the number of threads.
    fn gene_counts(duplications: usize, rate: f64, n: usize) -> Vec<usize> {
        let threads = std::thread::available_parallelism().map_or(1, |t| t.get()).min(n);
        let chunk = n.div_ceil(threads);
        let mut counts = vec![0; n];
        std::thread::scope(|scope| {
            for (t, slots) in counts.chunks_mut(chunk).enumerate() {
                scope.spawn(move || {
                    for (k, slot) in slots.iter_mut().enumerate() {
                        let mut rng = StdRng::seed_from_u64(42 + (t * chunk + k) as u64);
                        *slot = Genome::new_with_rng(&mut rng, duplications, rate, 0, 0, 1.0).num_genes();
                    }
                });
            }
        });
        counts
    }

    #[test]
    fn finds_a_hand_built_gene() {
        // Compute the expected majority vote with plain integer arithmetic.
        let mut expected = 0u32;
        for bit in 0..32 {
            let ones = BODY.iter().filter(|word| (*word >> bit) & 1 == 1).count();
            if ones >= 3 {
                expected |= 1 << bit;
            }
        }
        // It is found with room to spare, and when it ends exactly at the end.
        for trailing in [0, 100] {
            let genes = Gene::find_all(&one_gene(trailing));
            assert_eq!(
                genes,
                vec![Gene::new(ENHANCER, INHIBITOR, expected)],
                "trailing={trailing}"
            );
        }
    }

    #[test]
    fn short_sequences_have_no_genes() {
        assert!(Gene::find_all(&Chromosome::new()).is_empty());
        assert!(Gene::find_all(&Chromosome::repeat(false, 100)).is_empty());
        // One bit short of a complete gene.
        let mut chromosome = one_gene(0);
        chromosome.pop();
        assert!(Gene::find_all(&chromosome).is_empty());
        // The smallest genome is just the seed, which is too short to hold a gene.
        let genome = Genome::new(0, 0.0, 1, 1, 1.0);
        assert_eq!(genome.num_genes(), 0);
        assert_eq!(genome.chromosomes[0].len(), SEED_BITS);
    }

    #[test]
    fn a_promoter_needs_room_on_both_sides() {
        let promoter_at = |at: usize, len: usize| {
            let mut chromosome = Chromosome::repeat(false, len);
            chromosome[at..at + 8].clone_from_bitslice(START_SEQ.view_bits::<Lsb0>());
            chromosome
        };
        let len = UPSTREAM + 8 + DOWNSTREAM;
        assert_eq!(Gene::find_all(&promoter_at(UPSTREAM, len)).len(), 1);
        assert_eq!(
            Gene::find_all(&promoter_at(UPSTREAM - 1, len)).len(),
            0,
            "too close to the start"
        );
        assert_eq!(
            Gene::find_all(&promoter_at(UPSTREAM, len - 1)).len(),
            0,
            "too close to the end"
        );
    }

    #[test]
    fn genes_may_overlap_but_promoters_may_not() {
        let len = UPSTREAM + 8 + DOWNSTREAM + 200;
        let at = UPSTREAM + 50;

        // An alternating run matches at every even offset which leaves 8 bits, but
        // matches may not overlap, so the scan resumes 8 bits after each one. Every
        // full 8 bits of the run is one promoter, and so one gene, and all of these
        // genes overlap. (Even lengths only: the zeros around the run extend one
        // of odd length by a bit, which `find_all_matches_the_reference` covers.)
        for run in (8..=40).step_by(2) {
            assert_eq!(Gene::find_all(&with_run(len, at, run)).len(), run / 8, "run={run}");
        }
    }

    #[test]
    fn overlapping_genes_read_their_own_sites() {
        // The second promoter lies inside the first gene's coding region, so the
        // regulatory sites of the second gene overlap the first promoter.
        let len = UPSTREAM + 8 + DOWNSTREAM + 300;
        let (first, second) = (UPSTREAM + 3, UPSTREAM + 3 + 40);
        // Zeros hold no promoters, so these are the only two.
        let mut chromosome = Chromosome::repeat(false, len);
        for at in [first, second] {
            chromosome[at..at + 8].clone_from_bitslice(START_SEQ.view_bits::<Lsb0>());
        }
        chromosome[first - 2 * SITE_SIZE..first - SITE_SIZE].store_le(0x1234_5678u32);
        chromosome[first - SITE_SIZE..first].store_le(0xDEAD_BEEFu32);

        let genes = Gene::find_all(&chromosome);
        assert_eq!(genes.len(), 2);
        assert_eq!((genes[0].enhancer, genes[0].inhibitor), (0x1234_5678, 0xDEAD_BEEF));
        // The second gene starts 40 bits after the first, so its enhancer spans the
        // top 24 bits of the first gene's inhibitor (0xDEADBE) and the first
        // promoter (0xAA, in bits 24 to 31). Its inhibitor lies in the first
        // gene's coding region, which is all zeros.
        assert_eq!(genes[1].enhancer, 0xAADE_ADBE);
        assert_eq!(genes[1].inhibitor, 0);
    }

    #[test]
    fn find_all_matches_the_reference() {
        let mut rng = rng();
        // Words which make periodic runs, and so overlapping promoters, likely.
        let alphabet = [0x5555_5555u32, 0xAAAA_AAAA, 0x0000_0000, 0x0055_5500, 0xFF55_55FF];
        for case in 0..300 {
            let len = rng.random_range(0..2000);
            let chromosome = if case % 2 == 0 {
                random_chromosome(&mut rng, len)
            } else {
                let words = (0..len.div_ceil(SITE_SIZE)).map(|_| {
                    if rng.random_bool(0.7) {
                        alphabet[rng.random_range(0..alphabet.len())]
                    } else {
                        rng.random()
                    }
                });
                let mut chromosome = Chromosome::from_vec(words.collect());
                chromosome.truncate(len);
                chromosome
            };
            let bits: Vec<bool> = chromosome.iter().by_vals().collect();
            assert_eq!(
                Gene::find_all(&chromosome),
                reference_genes(&bits),
                "case {case}, len {len}"
            );
        }
    }

    #[test]
    fn random_chromosomes_have_the_expected_number_of_genes() {
        // Kuo & Banzhaf, Fig. 5: 131,072 random bits hold about 340 to 440 genes.
        // The expected spacing of promoters is 256 + 64 + 16 + 4 = 340 bits,
        // because this promoter can overlap itself.
        let mut rng = rng();
        let bits = SEED_BITS << 12;
        let counts: Vec<usize> = (0..20)
            .map(|_| Gene::find_all(&random_chromosome(&mut rng, bits)).len())
            .collect();
        let mean = counts.iter().sum::<usize>() as f64 / counts.len() as f64;
        assert!((365.0..=405.0).contains(&mean), "mean {mean}, counts {counts:?}");
        assert!(counts.iter().all(|n| (300..=470).contains(n)), "{counts:?}");
    }

    #[test]
    fn grown_chromosomes_have_the_requested_length() {
        for duplications in 0..=10 {
            let genome = Genome::new_with_rng(&mut rng(), duplications, 0.3, 1, 1, 1.0);
            assert_eq!(genome.chromosomes[0].len(), SEED_BITS << duplications, "{duplications}");
        }
    }

    #[test]
    fn without_mutation_the_chromosome_is_the_seed_repeated() {
        let genome = Genome::new_with_rng(&mut rng(), 7, 0.0, 0, 0, 1.0);
        let chromosome = &genome.chromosomes[0];
        assert_eq!(chromosome.len(), 4096);
        // The seed is the first word drawn from the generator.
        let seed: u32 = rng().random();
        assert!(chromosome.chunks(SEED_BITS).all(|word| word.load_le::<u32>() == seed));
    }

    #[test]
    fn every_round_duplicates_and_then_mutates_everything() {
        // At rate 1 each round doubles the chromosome and then flips all of it, so
        // the chromosome is always the seed repeated, complemented after an odd
        // number of rounds. This also shows that the last round is mutated.
        let seed: u32 = rng().random();
        for duplications in 0..8 {
            let genome = Genome::new_with_rng(&mut rng(), duplications, 1.0, 0, 0, 1.0);
            let expected = if duplications % 2 == 0 { seed } else { !seed };
            let chromosome = &genome.chromosomes[0];
            assert_eq!(chromosome.len(), SEED_BITS << duplications);
            assert!(
                chromosome
                    .chunks(SEED_BITS)
                    .all(|word| word.load_le::<u32>() == expected),
                "duplications={duplications}"
            );
        }
    }

    #[test]
    fn the_new_copy_and_the_old_one_are_both_mutated() {
        // Just before the last round the two halves are identical. Mutating both
        // of them makes a bit differ with probability 2p(1-p), where mutating only
        // the new copy would make it differ with probability p.
        let rate = 0.05;
        let genome = Genome::new_with_rng(&mut rng(), 12, rate, 0, 0, 1.0);
        let (a, b) = genome.chromosomes[0].split_at(SEED_BITS << 11);
        let differing = (a.iter().by_vals())
            .zip(b.iter().by_vals())
            .filter(|(x, y)| x != y)
            .count();
        // Expect 6,226 differences, with a standard deviation of 75.
        assert!((5700..=6700).contains(&differing), "{differing} bits differ");
    }

    #[test]
    fn construction_is_deterministic_given_a_seed() {
        let make = |seed| Genome::new_with_rng(&mut StdRng::seed_from_u64(seed), 7, 0.01, 3, 2, 1.0);
        assert_eq!(make(1), make(1));
        assert_ne!(make(1), make(2));
    }

    #[test]
    fn a_repetitive_chromosome_holds_many_overlapping_genes() {
        // 0xAAAA_AAAA is one long alternating run, which holds a promoter every 8
        // bits. Every one of them has a full gene around it, and the genes overlap
        // almost completely.
        let chromosome = grow(&mut rng(), 0xAAAA_AAAA, 6, 0.0);
        assert_eq!(chromosome.len(), 2048);
        let genes = Gene::find_all(&chromosome);
        assert_eq!(genes.len(), (chromosome.len() - UPSTREAM - 8 - DOWNSTREAM) / 8 + 1);
        assert!(
            genes
                .iter()
                .all(|gene| *gene == Gene::new(0xAAAA_AAAA, 0xAAAA_AAAA, 0xAAAA_AAAA))
        );
    }

    #[test]
    fn five_percent_mutation_is_like_random_bits() {
        // Kuo & Banzhaf, Fig. 4: after 12 duplications at 5% the genes number about
        // 200 to 700, centred near 390, like the random genomes of Fig. 5.
        let counts = gene_counts(12, 0.05, 30);
        let mean = counts.iter().sum::<usize>() as f64 / counts.len() as f64;
        assert!((340.0..=450.0).contains(&mean), "mean {mean}, counts {counts:?}");
        assert!(counts.iter().all(|n| (150..=900).contains(n)), "{counts:?}");
    }

    #[test]
    fn one_percent_mutation_has_a_heavy_tail() {
        // Kuo & Banzhaf, Fig. 3: after 12 duplications at 1% most genomes have few
        // genes, a few have thousands, and the distribution is heavy-tailed.
        let counts = gene_counts(12, 0.01, 100);
        let few = counts.iter().filter(|n| **n < 250).count() as f64 / counts.len() as f64;
        assert!(
            (0.45..=0.85).contains(&few),
            "{few} of genomes have fewer than 250 genes"
        );
        let most = counts.iter().max().unwrap();
        assert!(*most >= 1000, "at most {most} genes");
    }

    #[test]
    fn bad_arguments_are_rejected() {
        for rate in [-0.1, 1.1, f64::NAN] {
            let result = std::panic::catch_unwind(|| Genome::new(3, rate, 0, 0, 1.0));
            assert!(result.is_err(), "rate {rate}");
        }
        for duplications in [60, usize::MAX] {
            let result = std::panic::catch_unwind(|| Genome::new(duplications, 0.0, 0, 0, 1.0));
            assert!(result.is_err(), "duplications {duplications}");
        }
        let result = std::panic::catch_unwind(|| Genome::new(3, 0.0, 0, 0, f64::NAN));
        assert!(result.is_err());
    }

    #[test]
    fn explicit_sites_are_kept_and_inherited() {
        let inputs = vec![Gene::new(1, 2, 3)];
        let outputs = vec![Gene::new(4, 5, 6), Gene::new(7, 8, 9)];
        let parent = Genome::with_sites(&mut rng(), 7, 0.01, inputs.clone(), outputs.clone(), 2.0);
        assert_eq!((parent.inputs(), parent.outputs()), (&inputs[..], &outputs[..]));
        let child = parent.reproduce_with_rng(&mut rng(), 0.5);
        assert_eq!((child.inputs(), child.outputs()), (&inputs[..], &outputs[..]));
        assert_eq!(child.temperature(), 2.0);
    }

    #[test]
    fn reproduce_extremes() {
        let parent = Genome::new_with_rng(&mut rng(), 7, 0.01, 3, 2, 0.5);
        assert_eq!(parent.reproduce_with_rng(&mut rng(), 0.0), parent);
        let flipped = parent.reproduce_with_rng(&mut rng(), 1.0);
        assert_eq!(flipped.chromosomes[0], !parent.chromosomes[0].clone());
        assert_eq!((&flipped.inputs, &flipped.outputs), (&parent.inputs, &parent.outputs));
    }

    #[test]
    fn reproduce_flips_about_the_requested_fraction_of_bits() {
        let parent = Genome::new_with_rng(&mut rng(), 9, 0.01, 1, 1, 1.0);
        let child = parent.reproduce_with_rng(&mut rng(), 0.05);
        let changed = (parent.chromosomes[0].iter().by_vals())
            .zip(child.chromosomes[0].iter().by_vals())
            .filter(|(a, b)| a != b)
            .count();
        // Expect 819 changes, with a standard deviation of 28.
        assert!((490..=1150).contains(&changed), "{changed} bits changed");
        assert_eq!(child.chromosomes[0].len(), parent.chromosomes[0].len());
    }

    #[test]
    fn serialization_round_trips() {
        let genome = Genome::new_with_rng(&mut rng(), 7, 0.01, 3, 2, 0.5);
        let bytes = genome.to_bytes();
        assert_eq!(Genome::from_bytes(&bytes).unwrap(), genome);
        // Roughly 4 Kibit of chromosome plus 5 sites, so well under 1 KiB.
        assert!(bytes.len() < 1024, "{} bytes", bytes.len());
    }

    #[test]
    fn bad_bytes_are_rejected() {
        let genome = Genome::new_with_rng(&mut rng(), 7, 0.01, 3, 2, 0.5);
        let bytes = genome.to_bytes();
        assert!(Genome::from_bytes(&[]).is_err());
        assert!(Genome::from_bytes(&bytes[..bytes.len() - 1]).is_err());
        let mut padded = bytes.clone();
        padded.push(0);
        assert!(matches!(
            Genome::from_bytes(&padded),
            Err(GenomeError::TrailingBytes(1))
        ));
        for bad in [f64::NAN, f64::INFINITY, -1.0] {
            let mut broken = genome.clone();
            broken.temperature = bad;
            assert!(matches!(
                Genome::from_bytes(&broken.to_bytes()),
                Err(GenomeError::Temperature(_))
            ));
        }
    }

    #[test]
    fn phenome_has_the_controller_format() {
        let genome = Genome::new_with_rng(&mut rng(), 9, 0.05, 3, 2, 0.5);
        let genes = genome.num_genes();
        assert!(genes > 0);
        let n = genes + 3 + 2;

        let json: serde_json::Value = serde_json::from_slice(&genome.phenome()).unwrap();
        assert_eq!(json["T"], 0.5);
        assert_eq!(json["N"], n);
        let w: Vec<(usize, usize, f64)> = json["W"]
            .as_array()
            .unwrap()
            .iter()
            .map(|x| {
                let entry = x.as_array().unwrap();
                (
                    entry[0].as_u64().unwrap() as usize,
                    entry[1].as_u64().unwrap() as usize,
                    entry[2].as_f64().unwrap(),
                )
            })
            .collect();
        assert!(w.len() < n * n);
        assert_eq!(json["I"], serde_json::json!([[genes], [genes + 1], [genes + 2]]));
        assert_eq!(json["O"], serde_json::json!([[genes + 3], [genes + 4]]));

        // Strengths are differences of numbers in (0, 1], scaled by 1 / N.
        assert!(w.iter().all(|(_, _, x)| x.is_finite() && x.abs() <= 1.0 / n as f64));
        assert!(w.iter().any(|(_, _, x)| *x != 0.0), "the network is empty");
        assert!(w.iter().all(|(_, _, x)| x.abs() >= WEIGHT_THRESHOLD));
        // Nothing regulates an input, and an output regulates nothing.
        assert!(w.iter().all(|(target, _, _)| !(genes..genes + 3).contains(target)));
        assert!(w.iter().all(|(_, source, _)| *source < genes + 3));
    }

    #[test]
    fn phenome_of_an_empty_genome() {
        let json: serde_json::Value = serde_json::from_slice(&Genome::new(0, 0.0, 0, 0, 1.0).phenome()).unwrap();
        assert_eq!(json["N"], 0);
        assert_eq!(json["W"], serde_json::json!([]));
    }

    /// Three genes whose words hold no run of alternating bits, so that encoding
    /// them next to each other cannot make an extra promoter.
    fn plain_genes() -> [Gene; 3] {
        [
            Gene::new(ENHANCER, INHIBITOR, 0x0F0F_0F0F),
            Gene::new(0x00FF_FF00, 0xF0F0_F0F0, 0x3333_3333),
            Gene::new(0, u32::MAX, 0xC000_0003),
        ]
    }

    /// The phenome of `genome`, with its weights as `(target, source, value)`.
    fn weights(genome: &Genome) -> (serde_json::Value, Vec<(u64, u64, f64)>) {
        let json: serde_json::Value = serde_json::from_slice(&genome.phenome()).unwrap();
        let w = json["W"]
            .as_array()
            .unwrap()
            .iter()
            .map(|x| (x[0].as_u64().unwrap(), x[1].as_u64().unwrap(), x[2].as_f64().unwrap()))
            .collect();
        (json, w)
    }

    #[test]
    fn encode_lays_out_a_gene() {
        let block = Gene::new(ENHANCER, INHIBITOR, 0x0F0F_0F0F).encode();
        assert_eq!(GENE_BITS, 232);
        assert_eq!(block.len(), GENE_BITS);
        assert_eq!(block[0..32].load_le::<u32>(), ENHANCER);
        assert_eq!(block[32..64].load_le::<u32>(), INHIBITOR);
        assert_eq!(block[64..72].load_le::<u8>(), START_SEQ);
        for word in 0..GENE_WORDS {
            let at = 72 + word * SITE_SIZE;
            assert_eq!(block[at..at + SITE_SIZE].load_le::<u32>(), 0x0F0F_0F0F, "word {word}");
        }
    }

    #[test]
    fn a_lone_encoded_gene_is_always_found_first() {
        // The scan starts at the promoter of a lone gene, so whatever else a random
        // block holds, the first gene found is the one which was encoded.
        let mut rng = rng();
        for _ in 0..500 {
            let gene = Gene::random(&mut rng);
            assert_eq!(Gene::find_all(&gene.encode())[0], gene);
        }
        // Words which hold no alternating bits make a block with no other promoter.
        for gene in plain_genes() {
            assert_eq!(Gene::find_all(&gene.encode()), vec![gene]);
        }
    }

    #[test]
    fn concatenated_genes_decode_in_order() {
        let genes = plain_genes();
        let mut chromosome = Chromosome::new();
        for gene in &genes {
            chromosome.extend_from_bitslice(&gene.encode());
        }
        assert_eq!(chromosome.len(), 3 * GENE_BITS);
        assert_eq!(Gene::find_all(&chromosome), genes);

        let genome = Genome::from_chromosomes(vec![chromosome], vec![], vec![], 1.0);
        assert_eq!(genome.genes(), genes);
        assert_eq!(genome.num_genes(), 3);
    }

    #[test]
    fn an_alternating_word_can_make_extra_genes() {
        // Eight alternating bits are a promoter wherever they are, and a promoter
        // counts if a full coding region follows it. A lone gene has no room for one
        // in its coding region, but the second gene gives the first one's room.
        let alternating = Gene::new(ENHANCER, INHIBITOR, 0x5555_5555);
        let [plain, ..] = plain_genes();
        assert_eq!(Gene::find_all(&alternating.encode()).len(), 1);
        let mut chromosome = alternating.encode();
        chromosome.extend_from_bitslice(&plain.encode());
        assert!(Gene::find_all(&chromosome).len() > 2);
    }

    #[test]
    fn genes_are_listed_chromosome_by_chromosome() {
        let [a, b, c] = plain_genes();
        let join = |first: &Gene, second: &Gene| {
            let mut chromosome = first.encode();
            chromosome.extend_from_bitslice(&second.encode());
            chromosome
        };
        // Homologous chromosomes have the same length, here two genes each.
        let genome = Genome::from_chromosomes(
            vec![join(&a, &b), join(&c, &a)],
            vec![Gene::new(0, 0, 1)],
            vec![Gene::new(2, 3, 4)],
            2.0,
        );
        assert_eq!(genome.genes(), vec![a, b, c, a]);
        assert_eq!(genome.num_genes(), 4);
        // Nodes are the genes, then the inputs, then the outputs.
        assert_eq!(weights(&genome).0["N"], 4 + 1 + 1);
    }

    #[test]
    fn from_chromosomes_rejects_bad_arguments() {
        let chromosome = plain_genes()[0].encode();
        let empty = std::panic::catch_unwind(|| Genome::from_chromosomes(vec![], vec![], vec![], 1.0));
        assert!(empty.is_err());
        for bad in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY, -1.0] {
            let chromosome = chromosome.clone();
            let result =
                std::panic::catch_unwind(move || Genome::from_chromosomes(vec![chromosome], vec![], vec![], bad));
            assert!(result.is_err(), "temperature {bad}");
        }
        // Zero is a valid temperature, which freezes the network.
        Genome::from_chromosomes(vec![chromosome], vec![], vec![], 0.0);
    }

    #[test]
    fn a_hand_built_genome_round_trips_through_bytes() {
        let genome = Genome::from_chromosomes(
            vec![plain_genes()[1].encode()],
            vec![Gene::new(0, 0, 0x1234_5678), Gene::new(0, 0, 0x8765_4321)],
            vec![Gene::new(0xDEAD_BEEF, 0, 0)],
            20.0,
        );
        let loaded = Genome::from_bytes(&genome.to_bytes()).unwrap();
        assert_eq!(loaded, genome);
        assert_eq!(loaded.phenome(), genome.phenome());
    }

    #[test]
    fn weights_follow_the_bit_counts_of_the_sites() {
        // One gene whose enhancer is the exact complement of its own protein, and
        // whose inhibitor is the protein itself. Every bit of the protein differs
        // from the enhancer, which is the strongest match, e^0 = 1, and no bit
        // differs from the inhibitor, which is the weakest, e^-32.
        let protein = 0x0F0F_0F0F;
        let genome = Genome::from_chromosomes(
            vec![Gene::new(!protein, protein, protein).encode()],
            vec![],
            vec![],
            1.0,
        );
        let (json, w) = weights(&genome);
        assert_eq!(json["N"], 1);
        assert_eq!(w.len(), 1);
        assert_eq!((w[0].0, w[0].1), (0, 0));
        assert!((w[0].2 - (1.0 - (-32.0f64).exp())).abs() < 1e-15, "{w:?}");

        // With an input, N = 2, and a site which is one bit short of the complement
        // of the input's protein has strength e^-1, divided by N. The inhibitor
        // is the input's own protein, and is too weak to matter.
        let input = 0xFFC0_0000u32;
        let gene = Gene::new(!input ^ 1, input, protein);
        let genome = Genome::from_chromosomes(vec![gene.encode()], vec![Gene::new(0, 0, input)], vec![], 1.0);
        let (json, w) = weights(&genome);
        assert_eq!(json["N"], 2);
        let (_, _, value) = *w
            .iter()
            .find(|(target, source, _)| (*target, *source) == (0, 1))
            .unwrap();
        let expected = ((-1.0f64).exp() - (-32.0f64).exp()) / 2.0;
        assert!((value - expected).abs() < 1e-15, "{value} != {expected}");
    }
}
