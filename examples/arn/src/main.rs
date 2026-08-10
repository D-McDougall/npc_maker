use ndarray::{Array1, Array2};
use npc_maker::ctrl::API;
use serde::Deserialize;
use std::path::Path;

#[derive(Deserialize)]
#[allow(non_snake_case)]
struct Genome {
    /// Number of genes
    N: usize,

    /// Weights matrix
    W: Vec<f64>,

    /// Input gene names
    I: Vec<Vec<usize>>,

    /// Output gene names
    O: Vec<Vec<usize>>,
}

#[derive(Default)]
struct RegulatoryNetwork {
    matrix: Array2<f64>,
    inputs: Vec<Vec<usize>>,
    outputs: Vec<Vec<usize>>,
    queue: Vec<(usize, f64)>,
    state: Array1<f64>,
}

impl RegulatoryNetwork {
    fn num_states(&self) -> usize {
        self.state.len()
    }
}
impl API for RegulatoryNetwork {
    fn genome(&mut self, _environment: &Path, _population: &str, value: Box<[u8]>) {
        let Genome { N, W, I, O } = serde_json::from_slice(&value).unwrap();
        //
        self.state = Array1::from_elem(N, 1.0);
        self.inputs = I;
        self.outputs = O;
        self.matrix = Array2::from_shape_vec((N, N), W).unwrap();
    }
    fn reset(&mut self) {
        self.queue.clear();
        self.state.fill(1.0);
    }
    fn set_input(&mut self, gin: u64, value: String) {
        let value: f64 = value.parse().unwrap();
        self.queue.push((gin as usize, value));
    }
    fn get_output(&mut self, gin: u64) -> String {
        let indices = &self.outputs[gin as usize];
        if indices.is_empty() {
            return 0.to_string();
        }
        let value = indices
            .iter()
            .map(|gene_index| self.state[*gene_index])
            .sum::<f64>()
            / indices.len() as f64;
        format!("{value}")
    }
    fn advance(&mut self, dt: f64) {
        let gamma = 0.1;
        let mut input_delta = Array1::<f64>::zeros(self.num_states());
        for (index, value) in self.queue.drain(..) {
            for gene_index in &self.inputs[index] {
                input_delta[*gene_index] += dt * gamma * value
            }
        }
        let state_delta = dt * gamma * &self.state * self.matrix.dot(&self.state);
        self.state = &self.state + state_delta + input_delta;
        for x in &mut self.state {
            *x = x.max(0.0);
        }
        self.state *= self.num_states() as f64 / self.state.sum();
    }
}

fn main() {
    RegulatoryNetwork::default().main().unwrap();
}
