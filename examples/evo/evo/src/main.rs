//! Program for running evolutionary algorithms
//!
//! Features:
//! * Many strategies for:
//!     + Calculating agent score
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

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let mut evo = Evolution::new(args).unwrap();
    evo.main().unwrap();
}

pub const VERSION: &'static str = env!("CARGO_PKG_VERSION");

pub const USAGE: &'static str = r#"evo PATH [--flag VALUE]"#;

pub const HELP: &'static str = r#"
Example Evolutionary Algorithms for the NPC Maker
"#;

/// Main program data structure
#[derive(Debug)]
pub struct Evolution {
    path: PathBuf,

    score: String,

    selection: Vec<String>,

    selection_fn: SelectionFn,

    replacement: Replacement,

    population_size: usize,

    leaderboard_size: usize,

    hall_of_fame_size: usize,

    ascension: u64,

    generation: u64,

    population: Vec<Individual>,

    waiting: Vec<Individual>,

    leaderboard: Vec<Individual>,

    parents: Vec<Vec<PathBuf>>,

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
    score: String,
    selection: Vec<String>,
    replacement: Replacement,
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
    /// Get the `score` argument
    pub fn get_score(&self) -> String {
        self.score.clone()
    }
    /// Get the `selection` argument
    pub fn get_selection(&self) -> Vec<String> {
        self.selection.clone()
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
            score: "score".to_string(),
            population_size: 100,
            leaderboard_size: 10,
            hall_of_fame_size: 0,
            ascension: 0,
            generation: 0,
            population: vec![],
            waiting: vec![],
            leaderboard: vec![],
            parents: vec![],
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
                "--score" => {
                    todo!();
                    update = true;
                }
                "-s" | "--selection" => {
                    let (selection, selection_fn) = Self::parse_selection(args);
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
    fn parse_selection(args: &mut Vec<String>) -> (Vec<String>, SelectionFn) {
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
            score: self.get_score(),
            selection: self.get_selection(),
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
            Self::parse_selection(&mut std::mem::take(&mut metadata.selection));
        self.score = std::mem::take(&mut metadata.score);
        self.population_size = metadata.population_size;
        self.leaderboard_size = metadata.leaderboard_size;
        self.hall_of_fame_size = metadata.hall_of_fame_size;
        self.ascension = metadata.ascension;
        self.generation = metadata.generation;
        self.population = Individual::load_dir(self.get_population_path())?;
        self.waiting = Individual::load_dir(self.get_waiting_path())?;
        self.leaderboard = Individual::load_dir(self.get_leaderboard_path())?;
        // self.leaderboard.sort_unstable_by();
        // todo!();
        Ok(())
    }
}
impl Replacement {
    fn parse(args: &mut Vec<String>) -> Replacement {
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

impl API for Evolution {
    /// Get a list of parents to be mated together to produce a child.
    fn spawn(&mut self) -> Vec<PathBuf> {
        if self.population.is_empty() {
            return vec![];
        }
        // Refill parents buffer.
        if self.parents.is_empty() {
            let rng = &mut rand::rng();
            let buffer_size = match self.replacement {
                Replacement::Generation | Replacement::Frozen => self.population_size,
                _ => 1,
            };
            let scores: Vec<f64> = self
                .population
                .iter()
                .map(|individual| self.score_fn(individual))
                .collect();
            let mut index = self.selection_fn.pairs(rng, buffer_size, scores);
            // Deduplicate all of the parents pairs.
            // for pair in index.iter_mut() {
            //     pair.sort_unstable();
            //     pair.dedup();
            // }
            self.parents.reserve(index.len());
            for pair in index {
                self.parents.push(
                    pair.iter()
                        .map(|&idx| self.population[idx].path.as_ref().unwrap().clone())
                        .collect(),
                );
            }
        }
        self.parents.pop().unwrap()
    }
    /// Add a new individual to this population.
    fn death(&mut self, mut individual: PathBuf) {
        /*
        debug_assert!(individual.ascension.is_none());
        individual.ascension = Some(self.ascension);
        self.ascension += 1;
        //
        individual.save(&self.path)?;
        let individual = Arc::from(Mutex::from(individual));
        // Make room in the current members list for another individual.
        match self.replacement {
            Replacement::Unbounded => {}
            Replacement::Generation => {}
            Replacement::Random => {
                while !self.members.is_empty() && self.members.len() >= self.population_size {
                    let random_index = rand::random_range(0..self.members.len());
                    let random_individual = self.members.swap_remove(random_index);
                    Individual::drop(random_individual)?;
                }
            }
            Replacement::Worst => {
                let compare_scores = compare_scores(self.score.as_ref());
                while !self.members.is_empty() && self.members.len() >= self.population_size {
                    let (worst_index, _worst_individual) = self
                        .members
                        .iter()
                        .enumerate()
                        .min_by(|a, b| compare_scores(a.1, b.1))
                        .unwrap();
                    let worst_individual = self.members.swap_remove(worst_index);
                    Individual::drop(worst_individual)?;
                }
            }
            Replacement::Oldest => {
                while !self.members.is_empty() && self.members.len() >= self.population_size {
                    let (oldest_index, _oldest_individual) = self
                        .members
                        .iter()
                        .enumerate()
                        .min_by_key(|(_index, individual)| individual.lock().unwrap().ascension)
                        .unwrap();
                    let oldest_individual = self.members.swap_remove(oldest_index);
                    Individual::drop(oldest_individual)?;
                }
            }
        }
        // Save the individual into the current generation.
        match self.replacement {
            Replacement::Unbounded
            | Replacement::Random
            | Replacement::Worst
            | Replacement::Oldest => {
                self.members.push(individual.clone());
            }
            Replacement::Generation => {}
        }
        // Stage the individual for the next generation and bookkeeping.
        self.waiting.push(individual.clone());
        if self.waiting.len() >= self.population_size {
            self.rollover()?;
        }
        */
    }
    /// Receive a non-standard command
    fn custom(&mut self, command: String, arguments: Vec<serde_json::Value>) -> serde_json::Value {
        match command.as_str() {
            "rollover" => {
                todo!();
            }
            _ => {
                panic!("unsupported operation: {command}");
            }
        }
        Default::default()
    }
}
impl Evolution {
    fn score_fn(&self, individual: &Individual) -> f64 {
        individual.score.as_ref().unwrap().parse().unwrap()
    }
}

/*

/// Evolutionary algorithms choose which parent to reproduce with this
/// user-supplied function.
///
/// The first argument is the current mating population.
///
/// The second argument is the requested number of children to be spawned.
///
/// Returns a list of parent groups, where each parent group is a list of
/// parents to be mated together. The caller should take the following action
/// depending on how many unique parents are in a group.
///
/// | Parents | Action |
/// | --- | --- |
/// | 0 | Use the initial genetic material |
/// | 1 | Asexually reproduce the parent |
/// | 2 | Sexually reproduce the parents |
/// | 3+ | Unspecified |
///
fn foobar() {}

/// Individuals may have custom score functions with this type signature.
///
/// By default the npc_maker will parse the individual's score field into a single
/// floating point number, with a default of `-inf` for missing or invalid scores.
pub type Score = dyn Fn(&Individual) -> f64 + Send + Sync;

const DEFAULT_SCORE: f64 = f64::NEG_INFINITY;

fn default_score(individual: &Individual) -> f64 {
    if let Some(score) = &individual.score {
        score.parse().unwrap_or(DEFAULT_SCORE)
    } else {
        DEFAULT_SCORE
    }
}

fn compare_scores(
    score_fn: &Score,
) -> impl Fn(&Arc<Mutex<Individual>>, &Arc<Mutex<Individual>>) -> std::cmp::Ordering {
    move |a, b| {
        let a_score = score_fn(&a.lock().unwrap());
        let b_score = score_fn(&b.lock().unwrap());
        match (a_score.is_nan(), b_score.is_nan()) {
            (false, false) => a_score.total_cmp(&b_score),
            (true, true) => a_score.total_cmp(&b_score),
            (false, true) => std::cmp::Ordering::Greater,
            (true, false) => std::cmp::Ordering::Less,
        }
        .reverse()
    }
}

impl Evolution {
    /// Argument `path` is a directory where this will save the population to.
    /// If path is an empty string, a temporary directory will be created.
    ///
    /// Argument `replacement` controls how new members are added once the size of
    /// the population reaches the population_size argument.
    ///
    /// Argument `selection` controls which individuals are allowed to mate and
    /// with whom.
    ///
    /// Argument `score` is an optional custom scoring function.
    ///
    /// Argument `population_size` controls the total size of the mating
    /// population.
    ///
    /// Argument `leaderboard_size` is the number of the best scoring individuals
    /// to save in perpetuity. Set to zero to disable the leaderboard.
    ///
    /// Argument `hall_of_fame_size` is the number of individuals from each
    /// generation to induct in to the hall of fame. Set to zero to disable the
    /// hall of fame.

    //

    //

    /// Force the next generation to replace the current generation, even if the
    /// next generation has not reached the `population_size`. This is useful for
    /// seeding a population with initial genetic material and then making
    /// the seed material immediately available by calling this method.
    pub fn rollover(&mut self) -> Result<(), Error> {
        self.rollover_leaderboard()?;
        self.rollover_hall_of_fame()?;
        self.rollover_generation()?;
        self.save()?;
        Ok(())
    }
    fn rollover_leaderboard(&mut self) -> Result<(), Error> {
        if self.leaderboard_size == 0 || self.waiting.is_empty() {
            return Ok(());
        }
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
        Ok(())
    }
    fn rollover_hall_of_fame(&mut self) -> Result<(), Error> {
        if self.hall_of_fame_size == 0 || self.waiting.is_empty() {
            return Ok(());
        }
        // Find the highest scoring individuals in the new generation.
        let n = self.hall_of_fame_size.min(self.waiting.len() - 1);
        // This should be a stable sort but std does not support it.
        self.waiting
            .select_nth_unstable_by(n, compare_scores(self.score.as_ref()));
        let winners = &mut self.waiting[..n];
        winners.sort_unstable_by_key(|individual| individual.lock().unwrap().ascension);
        self.hall_of_fame.extend_from_slice(winners);
        Ok(())
    }
    fn rollover_generation(&mut self) -> Result<(), Error> {
        self.generation += 1;
        // Move the next generation into place.
        if self.replacement == Replacement::Generation {
            std::mem::swap(&mut self.members, &mut self.waiting);
        }
        // Discard the old generation.
        for individual in self.waiting.drain(..) {
            Individual::drop(individual)?;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pop_save_load() {
        let mut pop1 = Evolution::new("", None, None, None, 10, 3, 2).unwrap();

        for _ in 0..30 {
            let mut genome = Box::new(*b"beepboop");
            rand::fill(&mut genome[..]);
            let mut indiv = Individual::new("foo", "bar", &["ctrl", "prog"], genome);
            indiv.score = Some(rand::random::<f64>().to_string());
            pop1.death(indiv).unwrap();
        }
        pop1.save().unwrap();
        let pop2 = Evolution::new(pop1.get_path(), None, None, None, 10, 3, 2).unwrap();
        assert_eq!(pop1.get_path(), pop2.get_path());
        assert_eq!(pop1.get_ascension(), pop2.get_ascension());
        assert_eq!(pop1.get_generation(), pop2.get_generation());
        fn cmp_indiv(individuals: &[Arc<Mutex<Individual>>]) -> Vec<(Option<PathBuf>, Arc<[u8]>)> {
            let mut stubs = individuals
                .iter()
                .map(|stub| {
                    let stub = stub.lock().unwrap();
                    (stub.path.clone(), stub.genome())
                })
                .collect::<Vec<(Option<PathBuf>, Arc<[u8]>)>>();
            stubs.sort();
            stubs
        }
        assert_eq!(cmp_indiv(pop1.get_members()), cmp_indiv(pop2.get_members()));
        assert_eq!(
            cmp_indiv(pop1.get_leaderboard()),
            cmp_indiv(pop2.get_leaderboard())
        );
        assert_eq!(
            cmp_indiv(pop1.get_hall_of_fame()),
            cmp_indiv(pop2.get_hall_of_fame())
        );
        assert_eq!(pop2.get_members().len(), 10);
        assert_eq!(pop2.get_leaderboard().len(), 3);
        assert_eq!(pop2.get_hall_of_fame().len(), 6);
    }
    #[test]
    fn compare_scores() {
        use rand::seq::SliceRandom;
        let rng = &mut rand::rng();
        // Make some individuals with random scores.
        let mut individuals = vec![];
        for index in 0..30 {
            let mut indiv = Individual::new("foo", "bar", &["ctrl", "prog"], Box::new(*b""));
            indiv.score = Some(index.to_string());
            individuals.push(Arc::new(Mutex::new(indiv)));
        }
        for index in 5..10 {
            individuals[index].lock().unwrap().score = Some("corrupt".to_string());
        }
        for index in 10..15 {
            individuals[index].lock().unwrap().score = Some(f64::NAN.to_string());
        }
        //
        individuals.shuffle(rng);
        individuals.sort_by(super::compare_scores(&default_score));
        //
        for index in 0..20 {
            let score = default_score(&individuals[index].lock().unwrap());
            assert!(dbg!(score) >= 0.0);
        }
    }
    #[test]
    fn evo() {
        fn new_genome() -> Box<[u8]> {
            rand::random_iter::<u8>()
                .take(10)
                .collect::<Vec<u8>>()
                .into_boxed_slice()
        }
        fn mate_fn(a: &[u8], b: &[u8]) -> Box<[u8]> {
            let n = a.len();
            let crossover = rand::random_range(0..n);
            let mut c = vec![];
            c.extend_from_slice(&a[0..crossover]);
            c.extend_from_slice(&b[crossover..n]);
            mutate_fn(&mut c);
            c.into_boxed_slice()
        }
        fn mutate_fn(x: &mut [u8]) {
            if rand::random_bool(0.5) {
                x[rand::random_range(0..x.len())] = rand::random();
            }
        }
        fn eval(a: &[u8], b: &[u8]) -> String {
            let abs_dif = a
                .iter()
                .zip(b)
                .map(|(&x, &y)| (x as f64 - y as f64).abs())
                .sum::<f64>();
            (-abs_dif).to_string()
        }
        let target_genome = new_genome();
        let seed_genome = new_genome();
        let seed_score = eval(&seed_genome, &target_genome);
        let mut seed = Individual::new("", "", &[], seed_genome);
        seed.score = Some(seed_score);
        let mut evo = Evolution::new("", None, None, None, 100, 3, 1).unwrap();
        evo.death(seed).unwrap();
        evo.rollover().unwrap();
        while evo.get_generation() < 20 {
            let mut parents = evo.spawn();
            let mut child = if parents.len() == 1 {
                let mom = parents.pop().unwrap();
                let mut mom = mom.lock().unwrap();
                let mut genome: Vec<u8> = mom.genome().iter().cloned().collect();
                mutate_fn(&mut genome);
                Individual::asex(&mut mom, &genome)
            } else if parents.len() == 2 {
                let mom = parents.pop().unwrap();
                let dad = parents.pop().unwrap();
                let mut mom = mom.lock().unwrap();
                let mut dad = dad.lock().unwrap();
                let genome = mate_fn(&mom.genome(), &dad.genome());
                Individual::sex(&mut mom, &mut dad, &genome)
            } else {
                panic!()
            };
            child.score = Some(eval(&child.genome(), &target_genome));
            evo.death(child).unwrap();
        }
        for indiv in evo.get_hall_of_fame() {
            println!("{}", indiv.lock().unwrap().score.as_ref().unwrap());
        }
        let best = evo.get_leaderboard()[0].clone();
        assert!(
            best.lock()
                .unwrap()
                .score
                .as_ref()
                .unwrap()
                .parse::<f64>()
                .unwrap()
                > -100.0
        );
    }
}

*/
