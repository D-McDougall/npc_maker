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
//! 32-bit words immediately downstream of it are its coding region:
//!
//! ```text
//! | enhancer (32) | inhibitor (32) | promoter (8) | coding region (5 x 32) |
//! ```
//!
//! The gene's protein (the `effector`) is a 32-bit word obtained from the coding
//! region by a bitwise majority vote. Genes never overlap: after a gene is found
//! the scan resumes past the end of its coding region, leaving room for the next
//! gene's regulatory sites.
//!
//! # Network and phenome
//!
//! Every gene is a node in the network. The genome also carries one extra node
//! for each input and each output interface, the *I/O binding sites*. They are
//! drawn at random when the genome is created, and are inherited without
//! mutation. An I/O node has the same three fields as a gene, but instead of the
//! normal regulatory logic it exchanges values with the environment:
//!
//! * an **input** node is a pure source. Its effector regulates genes, but
//!   nothing regulates it, so its concentration is driven only by the input.
//! * an **output** node is a pure sink. Its enhancer and inhibitor sites listen
//!   to the genes' proteins, but it regulates nothing, so it only reports.
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

use bitvec::prelude::*;
use rand::{Rng, RngExt};
use serde::{Deserialize, Serialize};

/// Width of a regulatory site and of a protein, in bits.
const SITE_SIZE: usize = 32;

/// The promoter, which marks the start of a gene.
const START_SEQ: u8 = 0b01010101;

/// Number of 32-bit words in the coding region of a gene.
const GENE_WORDS: usize = 5;

// Majority vote needs an odd number of voters, so there are never ties.
const _: () = assert!(GENE_WORDS % 2 == 1);

/// Steepness of the exponential which turns a bit-match into a regulatory
/// strength. Larger values give sparser networks.
pub const BETA: f64 = 1.0;

/// The raw genetic data. The explicit `u32` store keeps the serialized form the
/// same on every platform, unlike the default `usize`.
type Chromosome = BitVec<u32, Lsb0>;

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

    /// Raw genetic data. This is the only part which mutates.
    chromosome: Chromosome,

    /// Binding sites for the input interfaces, inherited without mutation.
    inputs: Vec<Gene>,

    /// Binding sites for the output interfaces, inherited without mutation.
    outputs: Vec<Gene>,
}

impl Genome {
    /// Create a genome of random bits, with randomly generated I/O binding
    /// sites for `inputs` input interfaces and `outputs` output interfaces.
    ///
    /// # Panics
    ///
    /// Panics if `temperature` is not finite and non-negative.
    pub fn new(bits: usize, inputs: usize, outputs: usize, temperature: f64) -> Self {
        Self::new_with_rng(&mut rand::rng(), bits, inputs, outputs, temperature)
    }

    /// Like [`Genome::new`], with an explicit source of randomness. Use a seeded
    /// generator for reproducible results.
    pub fn new_with_rng<R: Rng + ?Sized>(
        rng: &mut R,
        bits: usize,
        inputs: usize,
        outputs: usize,
        temperature: f64,
    ) -> Self {
        let inputs = (0..inputs).map(|_| Gene::random(rng)).collect();
        let outputs = (0..outputs).map(|_| Gene::random(rng)).collect();
        Self::with_sites(rng, bits, inputs, outputs, temperature)
    }

    /// Create a genome of random bits, using the given I/O binding sites.
    ///
    /// # Panics
    ///
    /// Panics if `temperature` is not finite and non-negative.
    pub fn with_sites<R: Rng + ?Sized>(
        rng: &mut R,
        bits: usize,
        inputs: Vec<Gene>,
        outputs: Vec<Gene>,
        temperature: f64,
    ) -> Self {
        assert!(
            temperature.is_finite() && temperature >= 0.0,
            "temperature must be finite and non-negative, found {temperature}"
        );
        let words: Vec<u32> = (0..bits.div_ceil(SITE_SIZE)).map(|_| rng.random()).collect();
        let mut chromosome = Chromosome::from_vec(words);
        chromosome.truncate(bits);
        Self {
            temperature,
            chromosome,
            inputs,
            outputs,
        }
    }

    /// Create a child by copying this genome and flipping each bit of the
    /// chromosome independently, with probability `mutation_rate`. The I/O
    /// binding sites and the temperature are inherited unchanged.
    ///
    /// # Panics
    ///
    /// Panics unless `0 <= mutation_rate <= 1`.
    pub fn reproduce(&self, mutation_rate: f64) -> Self {
        self.reproduce_with_rng(&mut rand::rng(), mutation_rate)
    }

    /// Like [`Genome::reproduce`], with an explicit source of randomness.
    pub fn reproduce_with_rng<R: Rng + ?Sized>(&self, rng: &mut R, mutation_rate: f64) -> Self {
        assert!(
            (0.0..=1.0).contains(&mutation_rate),
            "mutation rate must be in [0, 1], found {mutation_rate}"
        );
        let mut child = self.clone();
        if mutation_rate > 0.0 {
            for mut bit in child.chromosome.iter_mut() {
                if rng.random_bool(mutation_rate) {
                    *bit = !*bit;
                }
            }
        }
        child
    }

    /// Build the phenome, in the JSON format of the `arn` controller.
    ///
    /// See the module documentation for how the genome becomes a network. The
    /// number of nodes `N` is zero only if the chromosome has no genes and the
    /// genome has no I/O sites, which the controller will reject.
    pub fn phenome(&self) -> Vec<u8> {
        let genes = Gene::find_all(&self.chromosome);
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

        #[derive(Serialize)]
        #[allow(non_snake_case)]
        struct Phenome {
            T: f64,
            N: usize,
            W: Vec<f64>,
            I: Vec<Vec<usize>>,
            O: Vec<Vec<usize>>,
        }
        let phenome = Phenome {
            T: self.temperature,
            N: n,
            W: w,
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

    /// The raw genetic data.
    pub fn chromosome(&self) -> &BitSlice<u32, Lsb0> {
        &self.chromosome
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

    /// Number of genes in the chromosome.
    pub fn num_genes(&self) -> usize {
        Gene::find_all(&self.chromosome).len()
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

    /// Scan a chromosome for genes, in order.
    fn find_all(sequence: &BitSlice<u32, Lsb0>) -> Vec<Self> {
        let start = START_SEQ.view_bits::<Lsb0>();
        let body_len = GENE_WORDS * SITE_SIZE;
        let mut genes = vec![];
        // The first promoter can be no earlier than two sites into the sequence.
        let mut index = 2 * SITE_SIZE;
        // The promoter must be followed by a complete coding region.
        while index + start.len() + body_len <= sequence.len() {
            if sequence[index..index + start.len()] == *start {
                let body = index + start.len();
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
                // Resume after the coding region, leaving room for the next
                // gene's regulatory sites, so that genes do not overlap.
                index = body + body_len + 2 * SITE_SIZE;
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
        // Tiny genomes are allowed.
        let genome = Genome::new(10, 1, 1, 1.0);
        assert_eq!(genome.num_genes(), 0);
        assert_eq!(genome.chromosome().len(), 10);
    }

    #[test]
    fn random_genomes_have_a_plausible_number_of_genes() {
        // About one promoter per 340 bits, and then the gene is skipped.
        let genome = Genome::new_with_rng(&mut rng(), 1 << 15, 0, 0, 1.0);
        assert_eq!(genome.chromosome().len(), 1 << 15);
        let genes = genome.num_genes();
        assert!((20..=200).contains(&genes), "found {genes} genes");
    }

    #[test]
    fn construction_is_deterministic_given_a_seed() {
        let make = |seed| Genome::new_with_rng(&mut StdRng::seed_from_u64(seed), 4096, 3, 2, 1.0);
        assert_eq!(make(1), make(1));
        assert_ne!(make(1), make(2));
    }

    #[test]
    fn explicit_sites_are_kept_and_inherited() {
        let inputs = vec![Gene::new(1, 2, 3)];
        let outputs = vec![Gene::new(4, 5, 6), Gene::new(7, 8, 9)];
        let parent = Genome::with_sites(&mut rng(), 4096, inputs.clone(), outputs.clone(), 2.0);
        assert_eq!((parent.inputs(), parent.outputs()), (&inputs[..], &outputs[..]));
        let child = parent.reproduce_with_rng(&mut rng(), 0.5);
        assert_eq!((child.inputs(), child.outputs()), (&inputs[..], &outputs[..]));
        assert_eq!(child.temperature(), 2.0);
    }

    #[test]
    fn reproduce_extremes() {
        let parent = Genome::new_with_rng(&mut rng(), 4096, 3, 2, 0.5);
        assert_eq!(parent.reproduce_with_rng(&mut rng(), 0.0), parent);
        let flipped = parent.reproduce_with_rng(&mut rng(), 1.0);
        assert_eq!(flipped.chromosome, !parent.chromosome.clone());
        assert_eq!((&flipped.inputs, &flipped.outputs), (&parent.inputs, &parent.outputs));
    }

    #[test]
    fn reproduce_flips_about_the_requested_fraction_of_bits() {
        let parent = Genome::new_with_rng(&mut rng(), 1 << 14, 1, 1, 1.0);
        let child = parent.reproduce_with_rng(&mut rng(), 0.05);
        let changed = (parent.chromosome.iter().by_vals())
            .zip(child.chromosome.iter().by_vals())
            .filter(|(a, b)| a != b)
            .count();
        // Expect 819 changes, with a standard deviation of 28.
        assert!((490..=1150).contains(&changed), "{changed} bits changed");
        assert_eq!(child.chromosome.len(), parent.chromosome.len());
    }

    #[test]
    fn serialization_round_trips() {
        let genome = Genome::new_with_rng(&mut rng(), 1 << 12, 3, 2, 0.5);
        let bytes = genome.to_bytes();
        assert_eq!(Genome::from_bytes(&bytes).unwrap(), genome);
        // Roughly 4 Kibit of chromosome plus 5 sites, so well under 1 KiB.
        assert!(bytes.len() < 1024, "{} bytes", bytes.len());
    }

    #[test]
    fn bad_bytes_are_rejected() {
        let genome = Genome::new_with_rng(&mut rng(), 1 << 12, 3, 2, 0.5);
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
        let genome = Genome::new_with_rng(&mut rng(), 1 << 14, 3, 2, 0.5);
        let genes = genome.num_genes();
        assert!(genes > 0);
        let n = genes + 3 + 2;

        let json: serde_json::Value = serde_json::from_slice(&genome.phenome()).unwrap();
        assert_eq!(json["T"], 0.5);
        assert_eq!(json["N"], n);
        let w: Vec<f64> = json["W"]
            .as_array()
            .unwrap()
            .iter()
            .map(|x| x.as_f64().unwrap())
            .collect();
        assert_eq!(w.len(), n * n);
        assert_eq!(json["I"], serde_json::json!([[genes], [genes + 1], [genes + 2]]));
        assert_eq!(json["O"], serde_json::json!([[genes + 3], [genes + 4]]));

        // Strengths are differences of numbers in (0, 1], scaled by 1 / N.
        assert!(w.iter().all(|x| x.is_finite() && x.abs() <= 1.0 / n as f64));
        assert!(w.iter().any(|x| *x != 0.0), "the network is empty");
        // Nothing regulates an input, and an output regulates nothing.
        for target in genes..genes + 3 {
            assert!(w[target * n..(target + 1) * n].iter().all(|x| *x == 0.0));
        }
        for target in 0..n {
            for source in genes + 3..n {
                assert_eq!(w[target * n + source], 0.0);
            }
        }
    }

    #[test]
    fn phenome_of_an_empty_genome() {
        let json: serde_json::Value = serde_json::from_slice(&Genome::new(10, 0, 0, 1.0).phenome()).unwrap();
        assert_eq!(json["N"], 0);
        assert_eq!(json["W"], serde_json::json!([]));
    }
}
