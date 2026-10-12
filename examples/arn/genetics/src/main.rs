use arn_genetics::Genome;
use npc_maker::genetics::{self, Genetics};
use npc_maker::individual::Individual;
use std::{env, net::SocketAddr};

const DEFAULT_MUTATION_RATE: f64 = 0.001;
const DEFAULT_DUPLICATIONS: usize = 9;
const DEFAULT_INPUTS: usize = 3;
const DEFAULT_OUTPUTS: usize = 2;
const DEFAULT_TEMPERATURE: f64 = 1.0;

#[derive(Debug)]
struct Options {
    listen: String,
    mutation_rate: f64,
    duplications: usize,
    inputs: usize,
    outputs: usize,
    temperature: f64,
}

fn parse_args() -> Result<Options, String> {
    let mut listen = None;
    let mut mutation_rate = DEFAULT_MUTATION_RATE;
    let mut duplications = DEFAULT_DUPLICATIONS;
    let mut inputs = DEFAULT_INPUTS;
    let mut outputs = DEFAULT_OUTPUTS;
    let mut temperature = DEFAULT_TEMPERATURE;

    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        let value = |args: &mut std::iter::Skip<std::env::Args>, option: &str| {
            args.next().ok_or_else(|| format!("{option} requires a value"))
        };

        match arg.as_str() {
            "--listen" => listen = Some(value(&mut args, "--listen")?),
            "--mutation-rate" => {
                mutation_rate = value(&mut args, "--mutation-rate")?
                    .parse()
                    .map_err(|_| "--mutation-rate must be a number".to_string())?;
            }
            "--duplications" => {
                duplications = value(&mut args, "--duplications")?
                    .parse()
                    .map_err(|_| "--duplications must be a non-negative integer".to_string())?;
            }
            "--inputs" => {
                inputs = value(&mut args, "--inputs")?
                    .parse()
                    .map_err(|_| "--inputs must be a non-negative integer".to_string())?;
            }
            "--outputs" => {
                outputs = value(&mut args, "--outputs")?
                    .parse()
                    .map_err(|_| "--outputs must be a non-negative integer".to_string())?;
            }
            "--temperature" => {
                temperature = value(&mut args, "--temperature")?
                    .parse()
                    .map_err(|_| "--temperature must be a number".to_string())?;
            }
            "--help" | "-h" => {
                return Err(
                    "Usage: arn_genetics --listen HOST:PORT [--mutation-rate RATE] [--duplications N] [--inputs N] [--outputs N] [--temperature T]\n\
                     Defaults: mutation rate 0.001, duplications 9, inputs 3, outputs 2, temperature 1.0"
                        .to_string(),
                );
            }
            _ => return Err(format!("unknown argument {arg:?}")),
        }
    }

    let listen = listen.ok_or_else(|| "--listen HOST:PORT is required".to_string())?;
    if !(0.0..=1.0).contains(&mutation_rate) {
        return Err("--mutation-rate must be in [0, 1]".to_string());
    }
    if !temperature.is_finite() || temperature < 0.0 {
        return Err("--temperature must be finite and non-negative".to_string());
    }

    Ok(Options {
        listen,
        mutation_rate,
        duplications,
        inputs,
        outputs,
        temperature,
    })
}

struct ArnGenetics {
    mutation_rate: f64,
    duplications: usize,
    inputs: usize,
    outputs: usize,
    temperature: f64,
}

impl Genetics for ArnGenetics {
    fn reproduce(&self, parents: Vec<Individual>) -> Result<Individual, String> {
        let (mut child, genome) = if let Some(mut parent) = parents.into_iter().next() {
            if parent.metadata.is_none() {
                return Err("first parent has no metadata".to_string());
            }
            let genome_bytes = parent
                .genome
                .as_deref()
                .ok_or_else(|| "first parent has no genome".to_string())?;
            let genome = Genome::from_bytes(genome_bytes).map_err(|error| format!("invalid parent genome: {error}"))?;
            let child = Individual::reproduce(&mut [&mut parent]);
            (child, genome.reproduce(self.mutation_rate))
        } else {
            let genome = Genome::new(
                self.duplications,
                0.01,
                self.inputs,
                self.outputs,
                self.temperature,
            );
            (Individual::new(), genome)
        };

        child.genome = Some(genome.to_bytes());
        child.phenome = Some(genome.phenome());
        Ok(child)
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let options = match parse_args() {
        Ok(options) => options,
        Err(message) => {
            eprintln!("Error: {message}");
            std::process::exit(2);
        }
    };
    let addr: SocketAddr = options
        .listen
        .parse()
        .map_err(|error| format!("expected --listen address HOST:PORT, found {}: {error}", options.listen))?;
    let service = ArnGenetics {
        mutation_rate: options.mutation_rate,
        duplications: options.duplications,
        inputs: options.inputs,
        outputs: options.outputs,
        temperature: options.temperature,
    };

    genetics::serve(addr, service).await?;
    Ok(())
}
