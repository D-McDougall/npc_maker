use clap::{Parser, Subcommand, ValueEnum};
use std::error::Error;
use std::path::PathBuf;

/// Command line interface for the evolution program.
#[derive(Debug, Parser)]
#[command(name = "npc-evo", about = "Evolutionary algorithm program for NPC Maker", version)]
pub struct Cli {
    /// Directory where population files (.indiv) are stored. If empty, a
    /// temporary directory will be used.
    #[arg(short = 'p', long = "population-dir", value_name = "PATH", default_value = "")]
    pub population_dir: PathBuf,

    /// Total population size used by the evolutionary algorithm.
    #[arg(short = 'n', long = "population-size", default_value_t = 100)]
    pub population_size: usize,

    /// Number of top individuals to keep in the leaderboard.
    #[arg(long = "leaderboard-size", default_value_t = 3)]
    pub leaderboard_size: usize,

    /// Number of individuals per generation to add to the hall of fame.
    #[arg(long = "hall-of-fame-size", default_value_t = 1)]
    pub hall_of_fame_size: usize,

    /// Replacement strategy for the population.
    #[arg(short = 'r', long = "replacement", value_enum, default_value_t = Replacement::Generation)]
    pub replacement: Replacement,

    /// Increase verbosity (-v, -vv, ...)
    #[arg(short, long, action = clap::ArgAction::Count)]
    pub verbose: u8,

    /// Subcommands for different program modes
    #[command(subcommand)]
    pub command: Option<Commands>,
}

#[derive(Debug, Subcommand)]
pub enum Commands {
    /// Run as an evolution API program: read single-line JSON array commands
    /// from stdin ("[\"spawn\"]", "[\"death\", \"path\"]") and
    /// write responses on stdout.
    Run {},

    /// Print the parsed configuration and exit.
    ShowConfig {},
}

#[derive(Debug, Clone, ValueEnum)]
pub enum Replacement {
    Unbounded,
    Random,
    Oldest,
    Worst,
    Generation,
}

impl Cli {
    /// Parse command line arguments into a Cli configuration
    pub fn parse_args() -> Self {
        Cli::parse()
    }

    /// Lightweight runner; this will be expanded later to construct the
    /// Evolution client or start an in-process algorithm. For now it only
    /// dispatches subcommands and returns any errors encountered.
    pub fn run(&self) -> Result<(), Box<dyn Error>> {
        match &self.command {
            Some(Commands::Run {}) | None => {
                // Default behaviour: run as API program.
                // The actual implementation will hook into the evolution API
                // (spawn/death handlers) and enter the protocol main loop.
                println!("Starting evolution program (API mode)");
                println!("population_dir = {:?}", self.population_dir);
                println!("population_size = {}", self.population_size);
                println!("leaderboard_size = {}", self.leaderboard_size);
                println!("hall_of_fame_size = {}", self.hall_of_fame_size);
                println!("replacement = {:?}", self.replacement);
                // TODO: wire up the API implementation here
                Ok(())
            }
            Some(Commands::ShowConfig {}) => {
                println!("Configuration:\n{:#?}", self);
                Ok(())
            }
        }
    }
}
