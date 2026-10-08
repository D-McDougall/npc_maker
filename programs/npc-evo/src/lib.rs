//! Evolutionary algorithms for the NPC Maker

use mate_selection::MateSelection;
use npc_maker::evolution::DeathRequest;
use npc_maker::individual::{Individual, Metadata};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(thiserror::Error, Debug)]
pub enum Error {
    #[error("{0}")]
    Io(#[from] std::io::Error),

    #[error("{0}")]
    Json(#[from] serde_json::Error),
}

pub const VERSION: &'static str = env!("CARGO_PKG_VERSION");

pub const HELP: &'static str = r#"Evolutionary algorithms for the NPC Maker

USAGE: npc-evo [PATH] [OPTIONS]

PATH:
    The npc-evo program saves the current population to this directory,
    and evolution can be restarted by passing in an existing directory.

SERVER OPTIONS:
    --host <ADDRESS>              Bind to host address
    --port <PORT>                 Bind to port number
    --listen <ADDRESS:PORT>       Bind to host and port
    --tls-cert <PATH>             TLS certificate (unimplemented)
    --tls-key <PATH>              TLS private key (unimplemented)

EVOLUTION OPTIONS:
    -p, --population <SIZE>       Set the population size
    -r, --replacement <MODE>      Set the replacement mode
    -s, --selection <SELECTION>   Set the selection method
        --parents <COUNT>         Set the number of parents
    -l, --leaderboard <SIZE>      Set the leaderboard size
    -f, --hall_of_fame <SIZE>     Set the hall of fame size

GENERAL OPTIONS:
    -v, --verbose                 Enable verbose output
        --version                 Print version information
    -h, --help                    Print this help message
"#;

/// Main program data structure
#[derive(Debug)]
pub struct Evolution {
    path: PathBuf,

    selection: String,

    selection_fn: SelectionFn,

    num_parents: usize,

    population_size: usize,

    replacement: Replacement,

    leaderboard_size: usize,

    hall_of_fame_size: usize,

    ascension: u64,

    generation: u64,

    population: Vec<Metadata>,

    waiting: Vec<Metadata>,

    leaderboard: Vec<Metadata>,

    buffer: Vec<Vec<String>>,

    verbose: bool,
}

type SelectionFn = Box<dyn MateSelection>;

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
struct PersistentData {
    selection: String,
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
    pub fn get_selection(&self) -> String {
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
        if this.verbose {
            eprintln!(
                "npc-evo: path={} population={} replacement={:?} selection={} parents={} \
                 leaderboard={} hall_of_fame={} generation={} ascension={}",
                this.path.display(),
                this.population_size,
                this.replacement,
                this.selection,
                this.num_parents,
                this.leaderboard_size,
                this.hall_of_fame_size,
                this.generation,
                this.ascension,
            );
        }
        Ok(this)
    }
    // Does not implement the `Default` trait, because this method is private.
    fn default() -> Self {
        let selection = "percentile=0.80".to_string();
        Self {
            path: PathBuf::new(),
            replacement: Replacement::Generation,
            selection_fn: mate_selection::parse(&selection).unwrap(),
            selection,
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
        path.push(format!("npc-evo-{:x}", rand::random_range(0..u64::MAX)));
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
            let flag = args.remove(0);
            match flag.as_str() {
                "-p" | "--population" => {
                    let value: usize = args.remove(0).parse().unwrap();
                    update |= value != self.population_size;
                    self.population_size = value;
                }
                "-s" | "--selection" => {
                    let selection = args.remove(0);
                    let selection_fn = mate_selection::parse(&selection).unwrap();
                    update |= selection != self.selection;
                    self.selection = selection;
                    self.selection_fn = selection_fn;
                }
                "-r" | "--replacement" => {
                    let value = Replacement::parse(args);
                    update |= value != self.replacement;
                    self.replacement = value;
                }
                "-l" | "--leaderboard" => {
                    let value: usize = args.remove(0).parse().unwrap();
                    update |= value != self.leaderboard_size;
                    self.leaderboard_size = value;
                }
                "-f" | "--hall_of_fame" => {
                    let value: usize = args.remove(0).parse().unwrap();
                    update |= value != self.hall_of_fame_size;
                    self.hall_of_fame_size = value;
                }
                "--parents" => {
                    let value: usize = args.remove(0).parse().unwrap();
                    update |= value != self.num_parents;
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
                arg => {
                    eprintln!("Error: unrecognized argument: {}", arg);
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
        let metadata = PersistentData {
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
        let metadata: PersistentData = serde_json::from_slice(&json)?;
        self.replacement = metadata.replacement;
        self.selection = metadata.selection;
        self.selection_fn = mate_selection::parse(&self.selection).unwrap();
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
        Ok(())
    }
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
                panic!(
                    "Expected one of generation, worst, oldest, random, growth, frozen; found {}",
                    arg0
                )
            }
        }
    }
}

// Utility functions dealing with scores
fn score_fn(metadata: &Metadata) -> (f64, u64) {
    // Treat NaN like a missing score, otherwise `total_cmp` would rank it best.
    let score = metadata.score.filter(|s| !s.is_nan()).unwrap_or(f64::NEG_INFINITY);
    let ascension = metadata.ascension.unwrap_or(u64::MAX);
    (score, ascension)
}
fn compare_scores(a: &Metadata, b: &Metadata) -> std::cmp::Ordering {
    let (a_score, a_ascension) = score_fn(a);
    let (b_score, b_ascension) = score_fn(b);
    a_score
        .total_cmp(&b_score)
        .reverse()
        .then_with(|| a_ascension.cmp(&b_ascension))
}

/// Make a second copy of an individual's directory.
///
/// The four data files are hard-linked when possible, which is instant and uses
/// no extra disk space, and are copied otherwise (for example across file
/// systems). Hard links are safe here because individuals are never modified in
/// place and `Individual::delete` unlinks each file separately, so deleting one
/// copy leaves the other intact.
fn copy_individual(src: &Path, dst: &Path) -> std::io::Result<()> {
    fs::create_dir(dst)?;
    let result = (|| {
        for file in ["metadata.json", "genome", "epigenome", "phenome"] {
            let (from, to) = (src.join(file), dst.join(file));
            if fs::hard_link(&from, &to).is_err() {
                fs::copy(&from, &to)?;
            }
        }
        Ok(())
    })();
    // Remove partial copy on error.
    if result.is_err() {
        let _ = fs::remove_dir_all(dst);
    }
    result
}

/// Primary API methods: spawn & death
impl Evolution {
    /// Get a list of parents to be mated together to produce a child
    pub fn spawn(&mut self) -> Vec<Individual> {
        if self.population.is_empty() {
            return vec![];
        }
        // Refill parents buffer.
        if self.buffer.is_empty() {
            let buffer_size = match self.replacement {
                Replacement::Generation | Replacement::Frozen => self.population_size,
                _ => 1,
            };
            let scores: Vec<f64> = self.population.iter().map(|i| score_fn(i).0).collect();
            let index: Vec<Vec<usize>> = match self.num_parents {
                0 => vec![vec![]; buffer_size],
                1 => {
                    let parents = self.selection_fn.select(buffer_size, scores).unwrap();
                    parents.into_iter().map(|index| vec![index]).collect()
                }
                2 => {
                    let pairs = self.selection_fn.pairs(buffer_size, scores).unwrap();
                    pairs.into_iter().map(|pair| pair.to_vec()).collect()
                }
                _ => {
                    let total = buffer_size.checked_mul(self.num_parents).expect("too many parents");
                    let flat = self.selection_fn.select(total, scores).unwrap();
                    flat.chunks_exact(self.num_parents)
                        .map(|group| group.to_vec())
                        .collect()
                }
            };
            self.buffer.reserve(index.len());
            for group in index {
                self.buffer
                    .push(group.iter().map(|&idx| self.population[idx].name.clone()).collect());
            }
        }
        // Load the parents
        let mut parents = vec![];
        for name in self.buffer.pop().unwrap() {
            let path = self.get_population_path().join(name);
            parents.push(Individual::load(path).unwrap());
        }
        parents
    }
    /// Add a new individual to this population
    pub fn death(&mut self, request: DeathRequest) {
        // Bookkeeping on the Individual
        let mut individual = request.individual.unwrap();
        {
            let metadata = individual.metadata.as_mut().unwrap();
            assert!(metadata.ascension.is_none());
            metadata.ascension = Some(self.ascension);
            self.ascension += 1;
        }
        let metadata = individual.metadata.as_ref().unwrap(); // Reborrow as immutable
        // Steady-state replacement: put individual directly into the population
        match self.replacement {
            Replacement::Frozen => {
                // Do nothing, by definition
            }
            Replacement::Growth => {
                // Add the individual to the population
                individual.save(self.get_population_path()).unwrap();
                self.population.push(metadata.clone());
            }
            Replacement::Generation => {
                // Action defered until next rollover event
            }
            Replacement::Random => {
                while !self.population.is_empty() && self.population.len() >= self.population_size {
                    let index = rand::random_range(0..self.population.len());
                    let random_individual = self.population.swap_remove(index);
                    random_individual.delete(self.get_population_path()).unwrap();
                }
                individual.save(self.get_population_path()).unwrap();
                self.population.push(metadata.clone());
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
                    worst_individual.delete(self.get_population_path()).unwrap();
                }
                individual.save(self.get_population_path()).unwrap();
                self.population.push(metadata.clone());
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
                    oldest_individual.delete(self.get_population_path()).unwrap();
                }
                individual.save(self.get_population_path()).unwrap();
                self.population.push(metadata.clone());
            }
        }
        // Always save to waiting directory for bookkeeping
        individual.save(&self.get_waiting_path()).unwrap();
        self.waiting.push(metadata.clone());
        // Rollover immediately, don't be lazy or wait until the next spawn.
        if self.waiting.len() >= self.population_size {
            self.rollover().unwrap();
        }
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
            if self.verbose {
                let best = self.leaderboard.first().and_then(|m| m.score);
                eprintln!(
                    "npc-evo: rollover to generation {} ({} individuals died, high score {:?})",
                    self.generation, self.ascension, best,
                );
            }
        }
        self.save()?;
        Ok(())
    }
    fn rollover_leaderboard(&mut self) -> Result<(), Error> {
        if self.leaderboard_size == 0 {
            return Ok(());
        }
        // Individuals must beat the current last place to be considered.
        let min_score = if self.leaderboard.len() >= self.leaderboard_size {
            score_fn(self.leaderboard.last().unwrap()).0
        } else {
            f64::NEG_INFINITY
        };
        let waiting_path = self.get_waiting_path();
        let leaderboard_path = self.get_leaderboard_path();
        // Copy the new contenders into the leaderboard directory.
        for contender in self.waiting.iter().filter(|m| score_fn(m).0 > min_score) {
            copy_individual(
                &waiting_path.join(&contender.name),
                &leaderboard_path.join(&contender.name),
            )?;
            self.leaderboard.push(contender.clone());
        }
        // Use stable sort to preserve ascension ordering between equal scores.
        self.leaderboard.sort_by(compare_scores);
        // Remove low performing individuals from the leaderboard directory.
        if self.leaderboard.len() > self.leaderboard_size {
            for loser in self.leaderboard.drain(self.leaderboard_size..) {
                loser.delete(&leaderboard_path)?;
            }
        }
        Ok(())
    }
    fn rollover_hall_of_fame(&mut self) -> Result<(), Error> {
        if self.hall_of_fame_size == 0 {
            return Ok(());
        }
        // Find the highest scoring individuals in the new generation.
        self.waiting.sort_by(compare_scores);
        let n = self.hall_of_fame_size.min(self.waiting.len());
        // Copy the winners into the hall of fame directory
        let waiting_path = self.get_waiting_path();
        let hall_of_fame_path = self.get_hall_of_fame_path();
        for winner in &self.waiting[..n] {
            if score_fn(winner).0 > f64::NEG_INFINITY {
                copy_individual(&waiting_path.join(&winner.name), &hall_of_fame_path.join(&winner.name))?;
            }
        }
        Ok(())
    }
    fn rollover_generation(&mut self) -> Result<(), Error> {
        self.generation += 1;
        if matches!(self.replacement, Replacement::Generation) {
            // Discard the current generation
            let population_path = self.get_population_path();
            for individual in self.population.drain(..) {
                individual.delete(&population_path)?;
            }
            // Move the waiting list files into the population directory
            let waiting_path = self.get_waiting_path();
            for individual in &self.waiting {
                let name = &individual.name;
                fs::rename(waiting_path.join(name), population_path.join(name))?;
            }
            // Move the waiting list into the population
            self.population = std::mem::take(&mut self.waiting);
        } else {
            // Clear the waiting list
            let waiting_path = self.get_waiting_path();
            for individual in self.waiting.drain(..) {
                individual.delete(&waiting_path)?;
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    /// Unique scratch directory which is removed on drop.
    struct TempDir(PathBuf);
    impl TempDir {
        fn new() -> Self {
            Self(Evolution::mktempdir())
        }
        fn path(&self) -> String {
            self.0.to_str().unwrap().to_string()
        }
    }
    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn evo(dir: &TempDir, flags: &[&str]) -> Evolution {
        let mut args = vec!["npc-evo".to_string(), dir.path()];
        args.extend(flags.iter().map(|s| s.to_string()));
        Evolution::new(args).unwrap()
    }

    /// Kill a new individual with the given score, returns its name.
    fn die(evo: &mut Evolution, score: Option<f64>) -> String {
        let mut individual = Individual::new();
        individual.metadata.as_mut().unwrap().score = score;
        individual.genome = Some(vec![1, 2, 3]);
        let name = individual.metadata().name.clone();
        evo.death(DeathRequest {
            individual: Some(individual),
        });
        name
    }

    fn dir_names(path: &Path) -> BTreeSet<String> {
        fs::read_dir(path)
            .unwrap()
            .map(|e| e.unwrap().file_name().into_string().unwrap())
            .collect()
    }

    fn board_names(evo: &Evolution) -> Vec<String> {
        evo.leaderboard.iter().map(|m| m.name.clone()).collect()
    }

    #[test]
    fn leaderboard_keeps_best_across_generations() {
        let dir = TempDir::new();
        let mut evo = evo(&dir, &["-p", "4", "-l", "3"]);
        // Generation 1
        let a = die(&mut evo, Some(1.0));
        let b = die(&mut evo, Some(5.0));
        let c = die(&mut evo, Some(3.0));
        let _d = die(&mut evo, Some(0.5));
        assert_eq!(board_names(&evo), [b.clone(), c.clone(), a.clone()]);
        // Generation 2 displaces the two lowest
        let e = die(&mut evo, Some(4.0));
        let f = die(&mut evo, Some(9.0));
        let _g = die(&mut evo, Some(0.1));
        let _h = die(&mut evo, Some(2.0));
        assert_eq!(board_names(&evo), [f, b, e]);
        // Directory contents agree with the in-memory leaderboard
        let on_disk = dir_names(&evo.get_leaderboard_path());
        assert_eq!(on_disk, board_names(&evo).into_iter().collect());
        // The evicted individuals are fully gone, the survivors are loadable
        for name in &on_disk {
            Individual::load(evo.get_leaderboard_path().join(name)).unwrap();
        }
    }

    #[test]
    fn leaderboard_ties_favor_incumbents_and_unscored_excluded() {
        let dir = TempDir::new();
        let mut evo = evo(&dir, &["-p", "3", "-l", "2"]);
        let first = die(&mut evo, Some(7.0));
        let second = die(&mut evo, Some(7.0));
        let _none = die(&mut evo, None);
        assert_eq!(board_names(&evo), [first.clone(), second.clone()]);
        // A tie with last place does not displace it, NaN is not a score
        die(&mut evo, Some(7.0));
        die(&mut evo, Some(f64::NAN));
        die(&mut evo, None);
        assert_eq!(board_names(&evo), [first, second]);
    }

    #[test]
    fn leaderboard_survives_restart() {
        let dir = TempDir::new();
        let expected = {
            let mut evo = evo(&dir, &["-p", "3", "-l", "2"]);
            die(&mut evo, Some(1.0));
            die(&mut evo, Some(2.0));
            die(&mut evo, Some(3.0));
            board_names(&evo)
        };
        let mut evo = evo(&dir, &[]);
        assert_eq!(board_names(&evo), expected);
        // New generation still merges with the loaded leaderboard
        die(&mut evo, Some(10.0));
        die(&mut evo, Some(0.0));
        die(&mut evo, Some(0.0));
        assert_eq!(evo.leaderboard[0].score, Some(10.0));
        assert_eq!(evo.leaderboard[1].score, Some(3.0));
        assert_eq!(evo.leaderboard.len(), 2);
    }

    #[test]
    fn leaderboard_disabled_when_size_zero() {
        let dir = TempDir::new();
        let mut evo = evo(&dir, &["-p", "2", "-l", "0"]);
        die(&mut evo, Some(1.0));
        die(&mut evo, Some(2.0));
        assert!(evo.leaderboard.is_empty());
        assert!(dir_names(&evo.get_leaderboard_path()).is_empty());
    }

    #[test]
    fn hall_of_fame_collects_best_of_each_generation() {
        let dir = TempDir::new();
        let mut evo = evo(&dir, &["-p", "3", "-f", "2"]);
        let a = die(&mut evo, Some(1.0));
        let b = die(&mut evo, Some(2.0));
        let _c = die(&mut evo, None);
        let hall = evo.get_hall_of_fame_path();
        assert_eq!(dir_names(&hall), [a.clone(), b.clone()].into_iter().collect());
        let d = die(&mut evo, Some(0.1));
        let e = die(&mut evo, Some(0.2));
        let f = die(&mut evo, Some(0.3));
        let _ = d;
        assert_eq!(dir_names(&hall), [a, b, e, f].into_iter().collect());
    }

    #[test]
    fn hall_of_fame_cohort_of_one_and_forced_rollover() {
        let dir = TempDir::new();
        let mut evo = evo(&dir, &["-p", "10", "-f", "5"]);
        let only = die(&mut evo, Some(1.0));
        evo.rollover().unwrap();
        assert_eq!(dir_names(&evo.get_hall_of_fame_path()), [only].into_iter().collect());
    }

    #[test]
    fn generation_replacement_still_swaps_population() {
        let dir = TempDir::new();
        let mut evo = evo(&dir, &["-p", "2", "-l", "1", "-f", "1"]);
        let a = die(&mut evo, Some(1.0));
        let b = die(&mut evo, Some(2.0));
        assert_eq!(dir_names(&evo.get_population_path()), [a, b].into_iter().collect());
        assert!(dir_names(&evo.get_waiting_path()).is_empty());
        let c = die(&mut evo, Some(3.0));
        let d = die(&mut evo, Some(4.0));
        assert_eq!(dir_names(&evo.get_population_path()), [c, d].into_iter().collect());
        assert_eq!(evo.get_generation(), 2);
    }

    #[test]
    fn steady_state_clears_waiting_directory() {
        for mode in ["random", "worst", "oldest", "growth", "frozen"] {
            let dir = TempDir::new();
            let mut evo = evo(&dir, &["-p", "3", "-r", mode, "-l", "2"]);
            for i in 0..7 {
                die(&mut evo, Some(i as f64));
            }
            // 7 deaths: two rollovers, one individual still waiting
            assert_eq!(evo.waiting.len(), 1, "{mode}");
            assert_eq!(dir_names(&evo.get_waiting_path()).len(), 1, "{mode}");
            assert_eq!(evo.leaderboard.len(), 2, "{mode}");
        }
    }

    #[test]
    fn replacement_accepts_unscored_individuals() {
        for mode in ["random", "worst", "oldest", "growth", "frozen"] {
            let dir = TempDir::new();
            let mut evo = evo(&dir, &["-p", "2", "-r", mode]);
            die(&mut evo, None);
            die(&mut evo, Some(1.0));

            // An unscored member is ranked as the worst by score_fn and should be
            // replaceable without panicking when the next individual arrives.
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                die(&mut evo, Some(2.0));
            }));
            assert!(result.is_ok(), "replacement {mode} panicked on a missing score");
        }
    }

    #[test]
    fn parents_option_controls_group_size() {
        for parents in [0usize, 1, 2, 3, 5] {
            let dir = TempDir::new();
            let flags = ["-p", "4", "--parents", &parents.to_string()].map(String::from);
            let flags: Vec<&str> = flags.iter().map(String::as_str).collect();
            let mut evo = evo(&dir, &flags);
            assert_eq!(evo.get_parents(), parents);
            for i in 0..4 {
                die(&mut evo, Some(i as f64 + 1.0));
            }
            // More spawns than one buffer refill, to exercise refilling
            for _ in 0..10 {
                assert_eq!(evo.spawn().len(), parents);
            }
        }
    }
}
