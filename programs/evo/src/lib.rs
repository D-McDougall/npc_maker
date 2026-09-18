//! Program for running evolutionary algorithms
//!
//! Features:
//! * Many strategies for:
//!     + Selecting individuals to spawn
//!     + Replacing individuals on death
//! * Persistent save files
//! * Leaderboard
//! * Hall of Fame

use mate_selection::MateSelection;
use npc_maker::evo::{API, Error};
use npc_maker::indiv::Individual;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::ffi::OsStr;
use std::fs;
use std::io::{BufRead, BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};

pub const VERSION: &'static str = env!("CARGO_PKG_VERSION");

pub const USAGE: &'static str = r#"evo PATH [--flag VALUE]"#;

pub const HELP: &'static str = r#"
Example Evolutionary Algorithms for the NPC Maker




Argument `path` is a directory where this will save the population to.
If path is an empty string, a temporary directory will be created.

Argument `replacement` controls how new members are added once the size of
the population reaches the population_size argument.

Argument `selection` controls which individuals are allowed to mate and
with whom.

Argument `population_size` controls the total size of the mating
population.

Argument `leaderboard_size` is the number of the best scoring individuals
to save in perpetuity. Set to zero to disable the leaderboard.

Argument `hall_of_fame_size` is the number of individuals from each
generation to induct in to the hall of fame. Set to zero to disable the
hall of fame.
"#;

/// Main program data structure
#[derive(Debug)]
pub struct Evolution {
    path: PathBuf,

    selection: Vec<String>,

    selection_fn: SelectionFn,

    num_parents: usize,

    population_size: usize,

    replacement: Replacement,

    leaderboard_size: usize,

    hall_of_fame_size: usize,

    ascension: u64,

    generation: u64,

    population: Vec<Individual>,

    waiting: Vec<Individual>,

    leaderboard: Vec<Individual>,

    buffer: Vec<Vec<PathBuf>>,

    verbose: bool,
}

type SelectionFn = Box<dyn MateSelection<rand::rngs::ThreadRng>>;

/// Controls how the population replaces individuals
#[derive(Serialize, Deserialize, Debug, Copy, Clone, PartialEq, Eq)]
pub enum Replacement {
    /// Do not add or remove members
    Frozen,

    /// Do not replace members, the population grows without bounds
    Growth,

    /// Replace members at random
    Random,

    /// Replace the oldest members
    Oldest,

    /// Replace the lowest scoring members
    Worst,

    /// Replace each generation entirely and all at once
    Generation,
}

/// Persistent storage for parameters and program state
#[derive(Serialize, Deserialize)]
struct Metadata {
    selection: Vec<String>,
    replacement: Replacement,
    num_parents: usize,
    population_size: usize,
    leaderboard_size: usize,
    hall_of_fame_size: usize,
    ascension: u64,
    generation: u64,
}

/// Getter / setter methods
impl Evolution {
    /// Get the `path` argument or the assigned temporary directory
    pub fn get_path(&self) -> &Path {
        &self.path
    }
    /// Persistent storage for program parameters & state
    fn get_metadata_path(&self) -> PathBuf {
        self.path.join("evo.json")
    }
    /// Directory of the currently mating population
    pub fn get_population_path(&self) -> PathBuf {
        self.path.join("pop")
    }
    fn get_waiting_path(&self) -> PathBuf {
        self.path.join("next")
    }
    /// Directory of the highest scoring individuals ever recorded
    pub fn get_leaderboard_path(&self) -> PathBuf {
        self.path.join("leaderboard")
    }
    /// Directory of the highest scoring individuals from each generation
    pub fn get_hall_of_fame_path(&self) -> PathBuf {
        self.path.join("hall_of_fame")
    }
    /// Get the `selection` argument
    pub fn get_selection(&self) -> Vec<String> {
        self.selection.clone()
    }
    /// Get the `parents` argument
    pub fn get_parents(&self) -> usize {
        self.num_parents
    }
    /// Get the `replacement` argument
    pub fn get_replacement(&self) -> Replacement {
        self.replacement
    }
    /// Get the `population` argument
    pub fn get_population_size(&self) -> usize {
        self.population_size
    }
    /// Get the `leaderboard` argument
    pub fn get_leaderboard_size(&self) -> usize {
        self.leaderboard_size
    }
    /// Get the `hall_of_fame` argument
    pub fn get_hall_of_fame_size(&self) -> usize {
        self.hall_of_fame_size
    }
    /// Get the total number of individuals that have died
    pub fn get_ascension(&self) -> u64 {
        self.ascension
    }
    /// Get the number of cohorts of size `population` that have died
    pub fn get_generation(&self) -> u64 {
        self.generation
    }
}

/// Methods to initialize, save, and load
impl Evolution {
    /// Main entry point to initialize program state
    ///
    /// This accepts the program's CLI arguments
    pub fn new(mut args: Vec<String>) -> Result<Self, Error> {
        // Initialize or load from file
        let mut this = Self::default();
        if let Some(path) = Self::parse_args(&mut args)
            && !path.as_os_str().is_empty()
        {
            if !path.exists() {
                this.init(path)?;
            } else {
                this.load(path)?;
            }
        } else {
            let path = Self::mktempdir();
            this.init(path)?;
        }
        // Apply the remaining CLI arguments
        if this.parse_flags(&mut args) {
            // Update the save file with the new parameters
            this.save()?;
        }
        Ok(this)
    }
    fn default() -> Self {
        Self {
            path: PathBuf::new(),
            replacement: Replacement::Generation,
            selection: vec!["exponential".to_string(), "10".to_string()],
            selection_fn: Box::new(mate_selection::RankedExponential(10)),
            num_parents: 2,
            population_size: 100,
            leaderboard_size: 10,
            hall_of_fame_size: 0,
            ascension: 0,
            generation: 0,
            population: vec![],
            waiting: vec![],
            leaderboard: vec![],
            buffer: vec![],
            verbose: false,
        }
    }
    /// File-path for temporary directory with unique name, does not create directory
    fn mktempdir() -> PathBuf {
        let mut path = std::env::temp_dir();
        path.push(format!("evo{:x}", rand::random_range(0..u64::MAX)));
        path
    }
    /// Process the first 2 arguments (program-name and save-dir)
    fn parse_args(args: &mut Vec<String>) -> Option<PathBuf> {
        // Discard the name of the program
        if !args.is_empty() {
            let _prog = args.remove(0);
        }
        // Split the file path from flag arguments, if path was given
        let mut path = None;
        if let Some(arg0) = args.get(0) {
            if !arg0.starts_with("-") {
                path = Some(PathBuf::from(arg0));
                args.remove(0);
            }
        }
        path
    }
    /// Parse the command line arguments
    fn parse_flags(&mut self, args: &mut Vec<String>) -> bool {
        let mut update = false;
        while !args.is_empty() {
            let flag = args.remove(0).to_lowercase();
            match flag.as_str() {
                "-p" | "--population" => {
                    let value: usize = args.remove(0).parse().unwrap();
                    update = value != self.population_size;
                    self.population_size = value;
                }
                "-s" | "--selection" => {
                    let (selection, selection_fn) = parse_selection(args);
                    update = selection != self.selection;
                    self.selection = selection;
                    self.selection_fn = selection_fn;
                }
                "-r" | "--replacement" => {
                    let value = Replacement::parse(args);
                    update = value != self.replacement;
                    self.replacement = value;
                }
                "-l" | "--leaderboard" => {
                    let value: usize = args.remove(0).parse().unwrap();
                    update = value != self.leaderboard_size;
                    self.leaderboard_size = value;
                }
                "-f" | "--hall_of_fame" => {
                    let value: usize = args.remove(0).parse().unwrap();
                    update = value != self.hall_of_fame_size;
                    self.hall_of_fame_size = value;
                }
                "--parents" => {
                    let value: usize = args.remove(0).parse().unwrap();
                    update = value != self.num_parents;
                    self.num_parents = value;
                }
                "-v" | "--verbose" => {
                    self.verbose = true;
                }
                "--version" => {
                    println!("{}", VERSION);
                    std::process::exit(0);
                }
                "-h" | "--help" => {
                    println!("{}", HELP);
                    std::process::exit(0);
                }
                _ => {
                    eprintln!("{}", USAGE);
                    std::process::exit(1);
                }
            }
        }
        update
    }
    /// Initialize file & directory structures
    fn init(&mut self, path: PathBuf) -> Result<(), Error> {
        self.path = path;
        fs::create_dir(&self.path)?;
        fs::create_dir(self.get_population_path())?;
        fs::create_dir(self.get_waiting_path())?;
        fs::create_dir(self.get_leaderboard_path())?;
        fs::create_dir(self.get_hall_of_fame_path())?;
        self.save()?;
        Ok(())
    }
    /// Write metadata file
    fn save(&self) -> Result<(), Error> {
        let metadata = Metadata {
            selection: self.get_selection(),
            num_parents: self.get_parents(),
            replacement: self.get_replacement(),
            population_size: self.get_population_size(),
            leaderboard_size: self.get_leaderboard_size(),
            hall_of_fame_size: self.get_hall_of_fame_size(),
            ascension: self.get_ascension(),
            generation: self.get_generation(),
        };
        let metadata = serde_json::to_vec_pretty(&metadata)?;
        let path = self.get_metadata_path();
        // Write to temporary file and rename for atomic file update
        let mut tmp = path.clone();
        tmp.add_extension("tmp");
        fs::write(&tmp, &metadata)?;
        fs::rename(&tmp, &path)?;
        Ok(())
    }
    fn load(&mut self, path: PathBuf) -> Result<(), Error> {
        self.path = path;
        let json = fs::read(&self.get_metadata_path())?;
        let mut metadata: Metadata = serde_json::from_slice(&json)?;
        self.replacement = metadata.replacement;
        (self.selection, self.selection_fn) =
            parse_selection(&mut std::mem::take(&mut metadata.selection));
        self.num_parents = metadata.num_parents;
        self.population_size = metadata.population_size;
        self.leaderboard_size = metadata.leaderboard_size;
        self.hall_of_fame_size = metadata.hall_of_fame_size;
        self.ascension = metadata.ascension;
        self.generation = metadata.generation;
        self.population = Individual::load_dir(self.get_population_path())?;
        self.waiting = Individual::load_dir(self.get_waiting_path())?;
        self.leaderboard = Individual::load_dir(self.get_leaderboard_path())?;
        self.leaderboard.sort_unstable_by(compare_scores);
        // todo!();
        Ok(())
    }
}
pub fn parse_selection(args: &mut Vec<String>) -> (Vec<String>, SelectionFn) {
    let mut selection = vec![args.remove(0).to_lowercase()];
    let selection_fn: SelectionFn = match selection[0].as_str() {
        "best" => {
            selection.push(args.remove(0));
            Box::new(mate_selection::Best(selection[1].parse().unwrap()))
        }
        "normal" => todo!(),
        "percent" => todo!(),
        "score" => todo!(),
        "random" => todo!(),
        "ranked" => todo!(),
        "exponential" => {
            selection.push(args.remove(0));
            Box::new(mate_selection::RankedExponential(
                selection[1].parse().unwrap(),
            ))
        }
        arg0 => panic!(
            "unexpected selection type, expected on of ... found {}",
            arg0
        ),
    };
    (selection, selection_fn)
}
impl Replacement {
    pub fn parse(args: &mut Vec<String>) -> Replacement {
        match args.remove(0).to_lowercase().as_str() {
            "generation" => Replacement::Generation,
            "worst" => Replacement::Worst,
            "oldest" => Replacement::Oldest,
            "random" => Replacement::Random,
            "growth" => Replacement::Growth,
            "frozen" => Replacement::Frozen,
            arg0 => {
                panic!("Expected one of ..., found {}", arg0)
            }
        }
    }
}

// Utility functions dealing with scores
fn score_fn(individual: &Individual) -> f64 {
    let Some(score) = individual.score.as_ref() else {
        return f64::NEG_INFINITY;
    };
    *score
}
fn compare_scores(a: &Individual, b: &Individual) -> std::cmp::Ordering {
    let a_score = a.score.unwrap_or(f64::NAN);
    let b_score = b.score.unwrap_or(f64::NAN);
    a_score.total_cmp(&b_score).reverse().then_with(|| {
        a.ascension
            .unwrap_or(u64::MAX)
            .cmp(&b.ascension.unwrap_or(u64::MAX))
    })
}

////////////////////////////////////////////////////////////////////////////////

impl API for Evolution {
    /// Get a list of parents to be mated together to produce a child.
    fn spawn(&mut self) -> Vec<PathBuf> {
        if self.population.is_empty() {
            return vec![];
        }
        // Refill parents buffer.
        if self.buffer.is_empty() {
            let rng = &mut rand::rng();
            let buffer_size = match self.replacement {
                Replacement::Generation | Replacement::Frozen => self.population_size,
                _ => 1,
            };
            let scores: Vec<f64> = self.population.iter().map(score_fn).collect();
            let mut index = self.selection_fn.pairs(rng, buffer_size, scores);
            self.buffer.reserve(index.len());
            for pair in index {
                self.buffer.push(
                    pair.iter()
                        .map(|&idx| self.population[idx].path.as_ref().unwrap().clone())
                        .collect(),
                );
            }
        }
        self.buffer.pop().unwrap()
    }
    /// Add a new individual to this population.
    fn death(&mut self, mut individual: PathBuf) {
        // Bookkeeping on the Individual
        let mut individual = Individual::load(individual).unwrap();
        assert!(individual.ascension.is_none());
        individual.ascension = Some(self.ascension);
        self.ascension += 1;
        // Steady-state replacement: put individual directly into the population
        match self.replacement {
            Replacement::Frozen => {
                // Do nothing, by definition
            }
            Replacement::Growth => {
                // Add the individual to the population
                individual.save(self.get_population_path()).unwrap();
                self.population.push(individual.clone());
            }
            Replacement::Generation => {
                // Action defered until next rollover event
            }
            Replacement::Random => {
                while !self.population.is_empty() && self.population.len() >= self.population_size {
                    let index = rand::random_range(0..self.population.len());
                    let random_individual = self.population.swap_remove(index);
                    random_individual.delete().unwrap();
                }
                individual.save(self.get_population_path()).unwrap();
                self.population.push(individual.clone());
            }
            Replacement::Worst => {
                while !self.population.is_empty() && self.population.len() >= self.population_size {
                    let (worst_index, _worst_individual) = self
                        .population
                        .iter()
                        .enumerate()
                        .min_by(|a, b| a.1.score.unwrap().total_cmp(&b.1.score.unwrap()))
                        .unwrap();
                    let worst_individual = self.population.swap_remove(worst_index);
                    worst_individual.delete().unwrap();
                }
                individual.save(self.get_population_path()).unwrap();
                self.population.push(individual.clone());
            }
            Replacement::Oldest => {
                while !self.population.is_empty() && self.population.len() >= self.population_size {
                    let (oldest_index, _oldest_individual) = self
                        .population
                        .iter()
                        .enumerate()
                        .min_by_key(|(_index, individual)| individual.ascension)
                        .unwrap();
                    let oldest_individual = self.population.swap_remove(oldest_index);
                    oldest_individual.delete().unwrap();
                }
                individual.save(self.get_population_path()).unwrap();
                self.population.push(individual.clone());
            }
        }
        // Always save to waiting directory for bookkeeping
        individual.save(&self.get_waiting_path()).unwrap();
        self.waiting.push(individual);
        if self.waiting.len() >= self.population_size {
            self.rollover().unwrap();
        }
    }
    /// Receive a non-standard command
    fn custom(&mut self, command: String, arguments: Vec<serde_json::Value>) -> serde_json::Value {
        match command.as_str() {
            "rollover" => {
                self.rollover().unwrap();
            }
            _ => {
                panic!("unsupported operation: {command}");
            }
        }
        Default::default()
    }
}

/// Rollover Events
///
/// Generational rollover events happen every time `population_size` many
/// individuals die. On rollover:
///   * Replacement::Generation swaps in the new population
///   * Update Leaderboard
///   * Update Hall of Fame
///   * Waiting list is cleared
impl Evolution {
    /// Force the next generation to replace the current generation, even if the
    /// next generation has not reached the `population_size`. This is useful for
    /// seeding a population with initial genetic material and then making
    /// the seed material immediately available by calling this method.
    pub fn rollover(&mut self) -> Result<(), Error> {
        if !self.waiting.is_empty() {
            self.rollover_leaderboard()?;
            self.rollover_hall_of_fame()?;
            self.rollover_generation()?;
        }
        self.save()?;
        Ok(())
    }
    fn rollover_leaderboard(&mut self) -> Result<(), Error> {
        if self.leaderboard_size == 0 {
            return Ok(());
        }
        /*
        let min_score = if self.leaderboard.len() >= self.leaderboard_size {
            let individual = self.leaderboard.last().unwrap();
            (*self.score)(&individual.lock().unwrap())
        } else {
            f64::NEG_INFINITY
        };
        // Sort together the existing leaderboard and the new contenders.
        self.leaderboard.extend(
            self.waiting
                .iter()
                .filter(|individual| (*self.score)(&individual.lock().unwrap()) > min_score)
                .cloned(),
        );
        // Use stable sort to preserve ascension ordering.
        self.leaderboard
            .sort_by(compare_scores(self.score.as_ref()));
        // Remove low performing individuals from the leaderboard directory.
        if self.leaderboard.len() > self.leaderboard_size {
            for individual in self.leaderboard.drain(self.leaderboard_size..) {
                Individual::drop(individual)?;
            }
        }
        */
        Ok(())
    }
    fn rollover_hall_of_fame(&mut self) -> Result<(), Error> {
        if self.hall_of_fame_size == 0 {
            return Ok(());
        }
        // Find the highest scoring individuals in the new generation.
        let n = self.hall_of_fame_size.min(self.waiting.len() - 1);
        self.waiting.select_nth_unstable_by(n, compare_scores);
        let winners = &self.waiting[..n];
        // Copy the winners into the hall of fame directory
        let hall_of_fame_path = self.get_hall_of_fame_path();
        for individual in winners.iter() {
            let new_path = hall_of_fame_path.join(individual.file_name());
            std::fs::copy(individual.path.as_ref().unwrap(), new_path)?;
        }
        Ok(())
    }
    fn rollover_generation(&mut self) -> Result<(), Error> {
        self.generation += 1;
        if matches!(self.replacement, Replacement::Generation) {
            // Discard the current generation
            for individual in self.population.drain(..) {
                individual.delete()?;
            }
            // Move the waiting list files into the population directory
            let population_path = self.get_population_path();
            for individual in &mut self.waiting {
                let old_path = individual.path.as_ref().unwrap();
                let new_path = population_path.join(individual.file_name());
                std::fs::rename(&old_path, &new_path)?;
                individual.path = Some(new_path); // Update the Individual's bookkeeping
            }
            // Move the waiting list into the population
            self.population = std::mem::take(&mut self.waiting);
        } else {
            // Clear the waiting list
            for individual in self.waiting.drain(..) {
                individual.delete()?;
            }
        }
        Ok(())
    }
}
