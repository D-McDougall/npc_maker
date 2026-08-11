//! Example controller - artificial neural network
//!
//! This file demonstrates how to implement a control system for the NPC Maker.

use npc_maker::ctrl::API;
use serde::Deserialize;
use std::collections::HashMap;

pub fn logistic(value: f64, slope: f64, midpoint: f64) -> f64 {
    // The magic number 4.0 scales the maximum slope of the curve to 1.0
    let x = 4.0 * slope * (value - midpoint);
    1.0 / (1.0 + (-x).exp())
}

#[derive(Deserialize, Debug)]
#[serde(tag = "type")]
enum Chromosome {
    Node {
        name: u64,
        midpoint: f64,
        slope: f64,
    },

    Edge {
        #[serde(default)]
        name: u64,
        presyn: u64,
        postsyn: u64,
        weight: f64,
    },
}

impl Chromosome {
    pub fn name(&self) -> u64 {
        match self {
            Self::Node { name, .. } => *name,
            Self::Edge { name, .. } => *name,
        }
    }
}

#[derive(Debug, Default)]
struct NeuralNetwork {
    /// Maps name to index
    names: HashMap<u64, u64>,

    nodes: Vec<(f64, f64)>,

    state: Vec<f64>,

    edges: Vec<(u64, u64, f64)>,
}

impl API for NeuralNetwork {
    fn genome(&mut self, _env: &std::path::Path, _pop: &str, genome: Box<[u8]>) {
        //
        let mut genome: Vec<Chromosome> = serde_json::from_slice(&genome).unwrap();
        genome.sort_unstable_by_key(|x| x.name());
        //
        self.names = genome
            .iter()
            .filter_map(|chrom| match chrom {
                Chromosome::Node { .. } => Some(chrom.name()),
                Chromosome::Edge { .. } => None,
            })
            .enumerate()
            .map(|(idx, name)| (name, idx as u64))
            .collect();
        //
        self.nodes = genome
            .iter()
            .filter_map(|chrom| match chrom {
                Chromosome::Node {
                    slope, midpoint, ..
                } => Some((*slope, *midpoint)),
                Chromosome::Edge { .. } => None,
            })
            .collect();
        //
        self.state = vec![0.0; self.nodes.len()];
        //
        self.edges = genome
            .iter()
            .filter_map(|chrom| match chrom {
                Chromosome::Node { .. } => None,
                Chromosome::Edge {
                    presyn,
                    postsyn,
                    weight,
                    ..
                } => Some((self.names[presyn], self.names[postsyn], *weight)),
            })
            .collect();
    }

    fn reset(&mut self) {
        self.state.fill(0.0);
    }

    fn advance(&mut self, _dt: f64) {
        let mut next_state = vec![0.0; self.nodes.len()];
        for (presyn, postsyn, weight) in self.edges.iter().copied() {
            next_state[postsyn as usize] += weight * self.state[presyn as usize];
        }
        for ((slope, midpoint), value) in self.nodes.iter().copied().zip(&mut next_state) {
            *value = logistic(*value, slope, midpoint);
        }
        self.state = next_state;
    }

    fn set_input(&mut self, gin: u64, value: String) {
        self.state[gin as usize] = value.parse().unwrap();
    }

    fn get_output(&mut self, gin: u64) -> String {
        self.state[gin as usize].to_string()
    }
}

fn main() {
    NeuralNetwork::default().main().unwrap();
}
