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
    names: HashMap<u64, Vec<usize>>,

    nodes: Vec<(f64, f64)>,

    state: Vec<f64>,

    edges: Vec<(usize, usize, f64)>,
}

impl API for NeuralNetwork {
    fn genome(&mut self, _env: &std::path::Path, _pop: &str, genome: Box<[u8]>) {
        //
        let mut genome: Vec<Chromosome> = serde_json::from_slice(&genome).unwrap();
        genome.sort_unstable_by_key(|x| x.name());
        //
        self.names.clear();
        self.nodes.clear();
        for (idx, (name, midpoint, slope)) in genome
            .iter()
            .filter_map(|chrom| match chrom {
                Chromosome::Node {
                    name,
                    midpoint,
                    slope,
                } => Some((name, midpoint, slope)),
                Chromosome::Edge { .. } => None,
            })
            .enumerate()
        {
            self.names.entry(*name).or_default().push(idx);
            self.nodes.push((*slope, *midpoint));
        }
        //
        self.state = vec![0.0; self.nodes.len()];
        //
        self.edges.clear();
        for chrom in genome {
            if let Chromosome::Edge {
                presyn,
                postsyn,
                weight,
                ..
            } = chrom
            {
                for presyn_index in &self.names[&presyn] {
                    for postsyn_index in &self.names[&postsyn] {
                        self.edges.push((*presyn_index, *postsyn_index, weight));
                    }
                }
            }
        }
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
        let value: f64 = value.parse().unwrap();
        for index in &self.names[&gin] {
            self.state[*index] = value;
        }
    }

    fn get_output(&mut self, gin: u64) -> String {
        let mut sum = 0.0;
        for index in &self.names[&gin] {
            sum += self.state[*index];
        }
        let avg = sum / self.names[&gin].len() as f64;
        avg.to_string()
    }
}

fn main() {
    NeuralNetwork::default().main().unwrap();
}
