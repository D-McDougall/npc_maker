//! A hand-crafted genome which solves the XOR task.
//!
//! Run with `cargo run -p arn_genetics --example xor_genome`. It builds the
//! genome, converts it to a phenome, checks that the phenome solves XOR, and
//! saves an `Individual` which holds both, in a new directory of the current
//! working directory.
//!
//! The genome is not evolved or drawn at random. Every bit of it is chosen, and
//! the example asserts that the genes, the network and the answers are what the
//! design below says they are.
//!
//! # The task
//!
//! The XOR environment (`examples/xor`) gives the controller two inputs, 0 and 1,
//! which are each exactly 0 or 1, and reads output 0. For each of the four input
//! pairs it resets the controller, then 1000 times sets the inputs and advances
//! the network by 0.1 s, and reads the output once. The output is clamped to
//! [0, 1]. The score is `(4 - total error)^2`, so the best score is 16.
//!
//! # The network
//!
//! There are five nodes, and three edges. The weight of an edge is written
//! `W[target][source]`.
//!
//! | node | role | protein |
//! | ---- | ---- | ------- |
//! | 0 | hidden gene `H`, which enhances itself: `W[0][0] = 1/5` | bits 0 to 10 |
//! | 1 | spacer gene `Z`, which has no edges at all | bits 11 to 21 |
//! | 2 | input 0 | bits 22 to 31 |
//! | 3 | input 1, which has the same protein as input 0 | bits 22 to 31 |
//! | 4 | output 0, enhanced by both inputs: `W[4][2] = W[4][3] = e^-1 / 5` | none |
//!
//! # Why it computes XOR
//!
//! Each step of the controller, with `h = dt * T`, is
//!
//! ```text
//! c <- c + h * c * (W c) + h * u        u holds the inputs, c * (W c) is elementwise
//! c <- max(c, 0)
//! c <- c * N / sum(c)                   so the concentrations always sum to N
//! ```
//!
//! The last line is the competition between the nodes: whatever grows is paid for
//! by everything else. Let `U` be the sum of the inputs, which is 0, 1, 1 and 2
//! for the four cases. Injecting `U` units of input at once makes the sum
//! `N + h (c.Wc + U)` before it is scaled back, so every concentration is diluted
//! by the rate `g = (c.Wc + U) / N`. A state which a step leaves unchanged,
//! a fixed point, satisfies
//!
//! ```text
//! c * (W c) + u = g * c
//! ```
//!
//! and `h`, and so `T`, is not in it. `T` only sets how fast the network gets to
//! a fixed point. For this network, node by node:
//!
//! * An input has no incoming edge, so `u_k = g * c_k`: it holds `u_k / g`. The
//!   two inputs together hold `U / g`.
//! * The spacer has no edges, so it holds nothing, and it matters to
//!   nothing else, except through `N`, see below.
//! * The hidden gene holds nothing, or else `g = s * c_H`, where `s = 1/5` is the
//!   weight of its self-enhancement.
//! * The output holds nothing, or else `g = a * U / g`, where `a = e^-1 / 5` is
//!   the weight of each input. So `g = sqrt(a * U)`, the inputs hold `U / g`, and
//!   the output holds what is left of the total `N`:
//!
//! ```text
//! c_out = N - sqrt(U / a)         if that is positive, and 0 if not
//! ```
//!
//! The four cases are:
//!
//! * **(0, 0)**, `U = 0`. Nothing feeds the inputs, so they fade away, and then
//!   nothing feeds the output either. `H` enhances itself, and takes everything.
//!   The output goes to 0.
//! * **(0, 1) and (1, 0)**, `U = 1`. The injected input feeds the output, which
//!   settles at `N - sqrt(1/a) = 5 - sqrt(5e) = 1.3133`. This is more than 1, so
//!   it is clamped to the right answer, 1. Both input nodes have the same protein,
//!   so the two cases are the same network, with the inputs swapped.
//! * **(1, 1)**, `U = 2`. The output would need `N - sqrt(2/a) = -0.21`, which is
//!   less than nothing, so there is no such state. Two inputs dilute the output by
//!   `g = U / N = 0.4` for every step. The most they can feed it, with the inputs
//!   holding everything, is `a * N = 0.368`. So it shrinks, by `(1 + h * 0.368) /
//!   (1 + h * 0.4)` every step. The output goes to 0.
//!
//! So the output survives for an input which is neither too small nor too large,
//! `U` between 0 and `a * N^2 = 1.84`, which is exactly one input. That is what
//! XOR is, here.
//!
//! This depends on the numbers, and the numbers come from the bits:
//!
//! * The weight of an input on the output is `e^-k / N`, where `k` is the number
//!   of bits by which the site misses the complement of the protein, so it comes
//!   in steps of `1/e`. XOR needs `1 < N e^-k < 2`, so that `U = 1` survives and
//!   `U = 2` does not, and `N - sqrt(N e^k) >= 1`, so that the answer for `U = 1`
//!   is big enough. For `N = 5` and `k = 1` both hold. For `N = 4` the first one
//!   holds, but the answer for `U = 1` is `4 - sqrt(4e) = 0.70`, which is not big
//!   enough. This is what the spacer gene is for: it is the fifth node.
//! * `H` enhances itself at full strength, so that it wins when there is no input.
//!   With a weaker site it can lose to the output, which starts with the same
//!   concentration, and which is fed by the two inputs at first.
//! * `T` has to be big enough to settle the (1, 1) case to within the resolution
//!   of the score, which takes `(1 + h * 0.368) / (1 + h * 0.4)` to the power
//!   1000 below 1e-16, which is `T` of about 20 or more. This genome uses 50.
//!   Larger values also work, because `h` drops out of the fixed points.
//!
//! The network works from the controller's initial state, in which every
//! concentration is 1, and the environment resets it before every case. It is not
//! stable against other starting points. In case (0, 1), for example, there is a
//! second fixed point, in which `H` holds 3.62 and the output holds nothing, and
//! a network that begins with a large `H` goes there.
//!
//! # The bits
//!
//! A weight is `(e^-(32 - m_e) - e^-(32 - m_i)) / N`, where `m_e` and `m_i` are
//! the numbers of bits in which the protein of the source differs from the
//! enhancer and from the inhibitor of the target. A protein is a perfect match,
//! and `e^0 = 1`, for the complement of the site, and `e^-1` for a site that is
//! one bit off. Every node has the same two sites for every protein, so all of the
//! sites and proteins are chosen together:
//!
//! * The three proteins are runs of bits which do not overlap, and which together
//!   cover all 32 bits: 11 for `H`, 11 for the spacer, and 10 for the inputs.
//! * Almost every site is zero. A zero site differs from a protein in the bits
//!   which the protein holds, so in at most 11 bits, and `e^-(32-11) / 5 = 1.5e-10`
//!   is below `WEIGHT_THRESHOLD`: no edge. Only two sites are not zero.
//! * `H` enhances itself, so its enhancer is the complement of its own protein.
//!   It has to be at least 20 bits from the other proteins, which is how far
//!   apart the disjoint runs are, so that it does not match them either.
//! * The enhancer of the output is the complement of the input protein, with one
//!   bit flipped, so that `k = 1`.
//! * The effectors are runs of ones, and so none of the 8 alternating bits of a
//!   promoter can show up in the chromosome except where `Gene::encode` put one.
//!   The example checks this by decoding the chromosome.
//!
//! The chromosome is the two genes, one after the other, 464 bits, with nothing
//! else in it.
//!
//! # The individual
//!
//! The `Individual` has the genome and the phenome, `body_type` "xor", and the
//! controller command of this checkout, as in `examples/arn/xor.py`. Its score is
//! not set. The in-process replica below is not a real environment, and so it is
//! not a reason to say that the environment has scored it.

use arn_controller::RegulatoryNetwork;
use arn_genetics::{BETA, Gene, Genome, SITE_SIZE, WEIGHT_THRESHOLD};
use npc_maker::controller::{IoValue, io_value::Value};
use npc_maker::individual::Individual;
use serde_json::json;
use std::error::Error;
use std::path::Path;

/// The temperature of the network. See the module documentation.
const TEMPERATURE: f64 = 50.0;

/// Node numbers. Nodes are numbered genes first, then inputs, then outputs.
const NODES: usize = 5;
const HIDDEN_NODE: usize = 0;
const INPUT_NODES: [usize; 2] = [2, 3];
const OUTPUT_NODE: usize = 4;

/// The proteins, runs of bits which do not overlap.
const HIDDEN_PROTEIN: u32 = 0x0000_07FF; // bits 0 to 10
const SPACER_PROTEIN: u32 = 0x003F_F800; // bits 11 to 21
const INPUT_PROTEIN: u32 = 0xFFC0_0000; // bits 22 to 31

/// The hidden gene, which enhances itself at full strength.
const HIDDEN: Gene = Gene {
    enhancer: !HIDDEN_PROTEIN,
    inhibitor: 0,
    effector: HIDDEN_PROTEIN,
};

/// A gene which has no edges, and is here only so that there are 5 nodes.
const SPACER: Gene = Gene {
    enhancer: 0,
    inhibitor: 0,
    effector: SPACER_PROTEIN,
};

/// Both inputs. Nothing regulates an input, so its sites are not used.
const INPUT: Gene = Gene {
    enhancer: 0,
    inhibitor: 0,
    effector: INPUT_PROTEIN,
};

/// The output, which is enhanced by the input protein at strength `e^-1 / N`.
/// Nothing is regulated by an output, so its effector is not used.
const OUTPUT: Gene = Gene {
    enhancer: !INPUT_PROTEIN ^ 1,
    inhibitor: 0,
    effector: 0,
};

/// What the controller is told to run, as in `examples/arn/xor.py`.
const BODY_TYPE: &str = "xor";

/// The name of the environment, which is the name of the `examples/xor` package.
const ENVIRONMENT: &str = "xor";

/// The XOR environment runs for this long, in steps of this size. See
/// `evaluate` in `examples/xor/src/main.rs`.
const TSTOP: f64 = 100.0;
const DT: f64 = 0.1;

/// The strength with which `protein` acts through `site`, which is the formula in
/// the module documentation of `arn_genetics`.
fn strength(protein: u32, site: u32) -> f64 {
    (BETA * ((protein ^ site).count_ones() as f64 - SITE_SIZE as f64)).exp()
}

/// The weight of the edge from a node with `protein` to `target`.
fn weight(protein: u32, target: &Gene) -> f64 {
    (strength(protein, target.enhancer) - strength(protein, target.inhibitor)) / NODES as f64
}

fn build_genome() -> Genome {
    // The chromosome is the two genes, with nothing in between or after them.
    let mut chromosome = HIDDEN.encode();
    chromosome.extend_from_bitslice(&SPACER.encode());
    Genome::from_chromosomes(vec![chromosome], vec![INPUT, INPUT], vec![OUTPUT], TEMPERATURE)
}

fn number(id: u64, value: f64) -> IoValue {
    IoValue {
        id,
        value: Some(Value::Number(value)),
    }
}

/// One input pair, as the XOR environment does it: reset, then set the inputs
/// and advance, over and over, and read output 0 once. Returns the raw output.
fn run_case(network: &mut RegulatoryNetwork, first: f64, second: f64) -> f64 {
    network.reset();
    for _ in 0..(TSTOP / DT).round() as usize {
        network.set_inputs(&[number(0, first), number(1, second)]).unwrap();
        network.advance(DT).unwrap();
    }
    match network.get_outputs(&[0]).unwrap().remove(0).value {
        Some(Value::Number(output)) => output,
        other => panic!("expected a number, found {other:?}"),
    }
}

/// The fixed point of the output from the module documentation, for a total input
/// `total`, in a network of `NODES` nodes with edge weight `a` from the inputs.
fn predicted_output(total: f64, a: f64) -> f64 {
    if total == 0.0 {
        0.0
    } else {
        (NODES as f64 - (total / a).sqrt()).max(0.0)
    }
}

fn main() -> Result<(), Box<dyn Error>> {
    let genome = build_genome();
    println!(
        "genome: {} bits of chromosome, {} genes, T = {}",
        genome.chromosomes()[0].len(),
        genome.num_genes(),
        genome.temperature(),
    );

    // 1. The chromosome holds the two genes, and no accidental third.
    assert_eq!(
        genome.genes(),
        vec![HIDDEN, SPACER],
        "the chromosome must decode to the design"
    );
    assert_eq!(genome.chromosomes()[0].len(), 2 * arn_genetics::GENE_BITS);

    // 2. The phenome has the nodes, interfaces and edges of the design.
    let phenome = genome.phenome();
    let json: serde_json::Value = serde_json::from_slice(&phenome)?;
    assert_eq!(json["T"], TEMPERATURE);
    assert_eq!(json["N"], NODES);
    assert_eq!(json["I"], json!([[INPUT_NODES[0]], [INPUT_NODES[1]]]));
    assert_eq!(json["O"], json!([[OUTPUT_NODE]]));
    let edges: Vec<(usize, usize, f64)> = serde_json::from_value(json["W"].clone())?;

    let a = weight(INPUT_PROTEIN, &OUTPUT);
    let designed = [
        (HIDDEN_NODE, HIDDEN_NODE, weight(HIDDEN_PROTEIN, &HIDDEN)),
        (OUTPUT_NODE, INPUT_NODES[0], a),
        (OUTPUT_NODE, INPUT_NODES[1], a),
    ];
    assert_eq!(
        edges.len(),
        designed.len(),
        "the phenome has an edge which is not in the design: {edges:?}"
    );
    for ((target, source, value), (want_target, want_source, want_value)) in edges.iter().zip(designed) {
        assert_eq!((*target, *source), (want_target, want_source));
        assert!(
            (value - want_value).abs() < 1e-15,
            "W[{target}][{source}] = {value}, not {want_value}"
        );
        println!("edge W[{target}][{source}] = {value:.6}");
    }

    // Every other pair is below the threshold. Find the strongest one, to show how
    // much room there is. Inputs are never regulated, and outputs never regulate.
    let nodes: Vec<Gene> = genome.genes().into_iter().chain([INPUT, INPUT, OUTPUT]).collect();
    let mut strongest_dropped: f64 = 0.0;
    for (target, regulated) in nodes.iter().enumerate().filter(|(t, _)| !INPUT_NODES.contains(t)) {
        for (source, regulator) in nodes.iter().enumerate().filter(|(s, _)| *s != OUTPUT_NODE) {
            if !designed.iter().any(|(t, s, _)| (*t, *s) == (target, source)) {
                strongest_dropped = strongest_dropped.max(weight(regulator.effector, regulated).abs());
            }
        }
    }
    assert!(strongest_dropped < WEIGHT_THRESHOLD);
    println!("strongest edge left out: {strongest_dropped:.2e} (threshold {WEIGHT_THRESHOLD:.0e})");

    // 3. Replay the XOR environment through the controller. This is a replica of
    // `evaluate` in `examples/xor/src/main.rs`, and not a run of the environment.
    let mut network = RegulatoryNetwork::from_phenome(&phenome, 1.0).expect("the phenome is valid");
    let mut distance = 0.0;
    println!("\ninput  raw output  predicted  answer");
    for first in [0.0, 1.0] {
        for second in [0.0, 1.0] {
            let output = run_case(&mut network, first, second);
            let predicted = predicted_output(first + second, a);
            let answer = output.clamp(0.0, 1.0);
            let correct = if first != second { 1.0 } else { 0.0 };
            distance += (answer - correct).abs();
            println!("{first:.0} {second:.0}    {output:<10.6}  {predicted:<9.6}  {answer:.6}");
            assert!(
                (output - predicted).abs() < 1e-9,
                "({first}, {second}) gave {output}, not {predicted}"
            );
            assert!(
                (answer - correct).abs() < 1e-12,
                "({first}, {second}) gave {answer}, not {correct}"
            );
        }
    }
    // The output for (1, 1) is about 1e-25, and not exactly 0, because it decays
    // by a factor each step and never reaches 0. It is so small that the sum of the
    // errors is lost in the rounding of `4 - distance`, and the score is exactly 16.
    let score = (4.0 - distance).powi(2);
    println!("score {score} (replica of the environment, the best is 16)");
    assert_eq!(score, 16.0);

    // 4. Make the individual, in the way that the genetics server does.
    let genome_bytes = genome.to_bytes();
    assert_eq!(Genome::from_bytes(&genome_bytes)?, genome);
    let mut individual = Individual::new();
    individual.genome = Some(genome_bytes);
    individual.phenome = Some(phenome);
    let metadata = individual.metadata.as_mut().expect("Individual::new sets the metadata");
    metadata.body_type = Some(BODY_TYPE.to_string());
    metadata.environment = Some(ENVIRONMENT.to_string());
    metadata.controller = controller_command();
    let name = metadata.name.clone();

    // The phenome has its own temperature, which takes precedence over the
    // `--temperature` of the controller, so the command needs no such argument.
    let directory = std::env::current_dir()?;
    individual.save(&directory)?;
    println!("\nsaved individual {name} in {}", directory.display());
    Ok(())
}

/// The command which runs the controller of this checkout, with an absolute path.
/// The XOR environment adds `--listen`.
fn controller_command() -> Vec<String> {
    // The manifest is in `examples/arn/genetics`, three levels below the root.
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("the manifest is in a repository");
    let program = root
        .join("target")
        .join("release")
        .join(format!("arn_controller{}", std::env::consts::EXE_SUFFIX));
    if !program.is_file() {
        eprintln!(
            "note: {} does not exist yet, build it with `cargo build --release -p arn_controller`",
            program.display()
        );
    }
    vec![program.to_string_lossy().into_owned()]
}
