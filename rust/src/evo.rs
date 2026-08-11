//! Evolutionary algorithms and supporting tools.

use mate_selection::MateSelection;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader, BufWriter, Error, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};

/// Generate a universally unique name. This will never return the same name twice.
fn uuid4() -> String {
    let uuid: u128 = rand::random();
    format!("{uuid:032X}")
}

/// Container for a distinct life-form and all of its associated data.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct Individual {
    /// Name or UUID of this individual.
    pub name: String,

    /// Number of individuals who died before this one,
    /// or None if this individual has not yet died.
    #[serde(default)]
    pub ascension: Option<u64>,

    /// Name of the environment that this individual lives in.
    #[serde(default)]
    pub environment: String,

    /// Name of the body_type that this individual uses.
    #[serde(default)]
    pub body_type: String,

    /// Name or UUID of this individual's species.
    /// Mating may be restricted to individuals of the same species.
    #[serde(default)]
    pub species: String,

    /// Command line invocation of the controller program.
    #[serde(default)]
    pub controller: Vec<String>,

    /// Genetic parameters for this individual.
    #[serde(skip)]
    pub genome: OnceLock<Arc<[u8]>>,

    /// The environmental info dictionary. The environment updates this information.
    #[serde(default)]
    pub telemetry: HashMap<String, String>,

    /// The epigenetic info dictionary. The controller updates this information.
    #[serde(default)]
    pub epigenome: HashMap<String, String>,

    /// Reproductive fitness of this individual, as assessed by the environment.
    #[serde(default)]
    pub score: Option<String>,

    /// Number of cohorts that passed before this individual was born.
    #[serde(default)]
    pub generation: u64,

    /// The names of this individual's parents.
    #[serde(default)]
    pub parents: Vec<String>,

    /// The names of this individual's children.
    #[serde(default)]
    pub children: Vec<String>,

    /// Time of birth, as a UTC timestamp, or an empty string if this individual
    /// has not yet been born.
    #[serde(default)]
    pub birth_date: String,

    /// Time of death, as a UTC timestamp, or an empty string if this individual
    /// has not yet died.
    #[serde(default)]
    pub death_date: String,

    /// Custom / unofficial fields that are saved with the individual.
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,

    /// The file path this individual was loaded from or saved to, or None
    /// if this individual has not touched the file system.
    #[serde(skip)]
    pub path: Option<PathBuf>,
}

impl Individual {
    /// Create a new individual.
    pub fn new(environment: &str, body_type: &str, controller: &[&str], genome: Box<[u8]>) -> Individual {
        Individual {
            name: uuid4(),
            ascension: None,
            environment: environment.to_string(),
            body_type: body_type.to_string(),
            species: uuid4(),
            controller: controller.iter().map(|arg| arg.to_string()).collect(),
            genome: OnceLock::from(Arc::from(genome)),
            telemetry: HashMap::new(),
            epigenome: HashMap::new(),
            score: None,
            generation: 0,
            parents: Vec::new(),
            children: Vec::new(),
            birth_date: String::new(),
            death_date: String::new(),
            extra: HashMap::new(),
            path: None,
        }
    }

    /// Get the genetic parameters for this individual. This loads the genome
    /// from file if necessary.
    pub fn genome(&self) -> Arc<[u8]> {
        self.genome
            .get_or_init(|| {
                let path = self.path.as_ref().expect("missing genome");
                // Safe to unwrap this file access, because we already accessed
                // this file at least once since the start of this program run.
                let mut file = BufReader::new(File::open(path).unwrap());
                file.skip_until(b'\0').unwrap();
                let mut data = vec![];
                file.read_to_end(&mut data).unwrap();
                Arc::from(data)
            })
            .clone()
    }

    /// Asexually reproduce an individual.
    pub fn asex(&mut self, child_genome: &[u8]) -> Individual {
        let individual = Individual {
            name: uuid4(),
            ascension: None,
            environment: self.environment.clone(),
            body_type: self.body_type.clone(),
            species: self.species.clone(),
            controller: self.controller.clone(),
            genome: OnceLock::from(Arc::from(child_genome)),
            telemetry: HashMap::new(),
            epigenome: HashMap::new(),
            score: None,
            generation: self.generation + 1,
            parents: vec![self.name.clone()],
            children: vec![],
            birth_date: String::new(),
            death_date: String::new(),
            extra: HashMap::new(),
            path: None,
        };
        self.children.push(individual.name.clone());
        individual
    }

    /// Sexually reproduce two individuals.
    pub fn sex(&mut self, other: &mut Individual, child_genome: &[u8]) -> Individual {
        let individual = Individual {
            name: uuid4(),
            ascension: None,
            environment: self.environment.clone(),
            body_type: self.body_type.clone(),
            species: self.species.clone(),
            controller: self.controller.clone(),
            genome: OnceLock::from(Arc::from(child_genome)),
            telemetry: HashMap::new(),
            epigenome: HashMap::new(),
            score: None,
            generation: self.generation.max(other.generation) + 1,
            parents: vec![self.name.clone(), other.name.clone()],
            children: vec![],
            birth_date: String::new(),
            death_date: String::new(),
            extra: HashMap::new(),
            path: None,
        };
        self.children.push(individual.name.clone());
        other.children.push(individual.name.clone());
        individual
    }

    fn file_name(&self) -> String {
        format!("{}.indiv", self.name)
    }

    /// Save an individual to a file.
    ///
    /// Argument path is the directory to save in. Optional, use empty string
    /// for temporary file. The filename will be the individual's name with the
    /// ".indiv" file extension.
    ///
    /// Returns the file path of the saved individual.
    pub fn save(&mut self, path: impl AsRef<Path>) -> Result<&Path, Error> {
        let mut path: PathBuf = path.as_ref().into();
        // Fill in default path.
        if path.to_str() == Some("") {
            if let Some(save_file) = self.path.as_ref() {
                path = save_file.parent().unwrap().into();
            } else {
                path = std::env::temp_dir();
            }
        }
        // Load the genome from file before modifying the file system.
        self.genome();
        // Make the directory in case this is the first individual to be saved to it.
        if !path.exists() {
            std::fs::create_dir(&path)?;
        }
        // Make paths to temporary buffer and final file locations.
        let file_name = self.file_name();
        let mut temp = std::env::temp_dir();
        temp.push(format!("{file_name}.tmp"));
        path.push(file_name);
        //
        let file = File::create(&temp)?;
        let mut buf = BufWriter::new(file);
        serde_json::to_writer(&mut buf, self).unwrap();
        buf.write_all(b"\0")?;
        buf.write_all(&self.genome())?;
        let file = buf.into_inner()?; // flush the buffer
        file.sync_all()?; // push to disk
        std::fs::rename(&temp, &path)?; // move file into place
        self.path = Some(path);
        self.genome.take(); // free the genome
        Ok(self.path.as_ref().unwrap())
    }

    /// Load a previously saved individual.
    pub fn load(path: impl AsRef<Path>) -> Result<Individual, Error> {
        let path = path.as_ref().to_path_buf();
        let mut file = BufReader::new(File::open(&path)?);
        let mut text = vec![];
        file.read_until(b'\0', &mut text)?;
        text.pop_if(|&mut char| char == b'\0');
        let mut individual: Individual = serde_json::from_slice(&text)?;
        individual.path = Some(path);
        Ok(individual)
    }

    /// Get all individuals saved in a directory.
    pub fn load_dir(path: impl AsRef<Path>) -> Result<Vec<Individual>, Error> {
        let path = path.as_ref();
        if !path.exists() {
            return Ok(vec![]);
        }
        let mut individuals = vec![];
        for file in path.read_dir()? {
            let file = file?;
            if !file.file_type()?.is_file() {
                continue;
            }
            let file_name = file.file_name();
            let Some(file_name) = file_name.to_str() else {
                continue;
            };
            if file_name.ends_with(".indiv") {
                individuals.push(Individual::load(file.path())?);
            }
        }
        Ok(individuals)
    }

    /// Remove this individual and its associated save file.
    pub fn delete(self) -> Result<(), Error> {
        if let Some(path) = self.path {
            std::fs::remove_file(path)?;
        }
        Ok(())
    }

    /// Delete the individual if this is the last reference to it.
    pub fn drop(this: Arc<Mutex<Self>>) -> Result<(), Error> {
        if let Some(mutex) = Arc::into_inner(this) {
            let individual = mutex.into_inner().unwrap();
            individual.delete()?;
        }
        Ok(())
    }
}

/// Controls how a population replaces its members once it's full.
#[derive(Serialize, Deserialize, Debug, Copy, Clone, PartialEq, Eq)]
pub enum Replacement {
    /*
    /// Do not add or remove members.
    Frozen,
    */
    /// Do not replace members. The population grows without bounds.
    Unbounded,

    /// Replace members at random.
    Random,

    /// Replace the oldest member.
    Oldest,

    /// Replace the lowest scoring member.
    Worst,

    /// Replace generations entirely and all at once.
    Generation,
}

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
pub type Selection = dyn Fn(&[Arc<Mutex<Individual>>], usize) -> Vec<Vec<Arc<Mutex<Individual>>>> + Send + Sync;

/// Individuals may have custom scores functions with this type signature.
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

fn compare_scores(score_fn: &Score) -> impl Fn(&Arc<Mutex<Individual>>, &Arc<Mutex<Individual>>) -> std::cmp::Ordering {
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

// TOOD: Consider introducing a mutex lock into the population so that
// Evolution.spawn() and Evolution.death() are immutable. This would allow finer
// grained locking: move the file-system tasks out of the mutex-locked critical
// section.
//
// Pseudo Code:
//
// fn spawn(&self)
//      1) lock mutex
//      2) refill parents queue if empty
//      3) pop & return parent group
//      4) release mutex
//
// fn death(&self, individual)
//      1) individual.save()
//      2) lock mutex
//      3) reckon the population
//      4) release mutex
//      5) delete individuals
//

/// Container for an evolving population of individuals.
///
/// Features:
/// * Several strategies for replacing individuals with new ones,
/// * Persistence by saving to file,
/// * A Leaderboard and Hall of Fame.
pub struct Evolution {
    path: PathBuf,

    replacement: Replacement,

    selection: Arc<Selection>,

    score: Arc<Score>,

    population_size: usize,

    leaderboard_size: usize,

    hall_of_fame_size: usize,

    ascension: u64,

    generation: u64,

    members: Vec<Arc<Mutex<Individual>>>,

    waiting: Vec<Arc<Mutex<Individual>>>,

    leaderboard: Vec<Arc<Mutex<Individual>>>,

    hall_of_fame: Vec<Arc<Mutex<Individual>>>,

    parents: Vec<Vec<Arc<Mutex<Individual>>>>,
}

#[derive(Serialize, Deserialize)]
struct EvolutionMetadata {
    ascension: u64,
    generation: u64,
    members: Vec<String>,
    waiting: Vec<String>,
    leaderboard: Vec<String>,
    hall_of_fame: Vec<String>,
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
    pub fn new(
        path: impl AsRef<Path>,
        replacement: Option<Replacement>,
        selection: Option<Arc<Selection>>,
        score: Option<Arc<Score>>,
        population_size: usize,
        leaderboard_size: usize,
        hall_of_fame_size: usize,
    ) -> Result<Evolution, Error> {
        let mut path = path.as_ref().to_path_buf();
        // Fill in empty path with temp dir.
        if path.to_str() == Some("") {
            path = std::env::temp_dir();
            path.push(format!("pop{:x}", rand::random_range(0..u64::MAX)));
        }
        if !path.exists() {
            std::fs::create_dir(&path)?;
        }
        //
        let score = score.unwrap_or_else(|| Arc::new(default_score));
        //
        let selection = selection.unwrap_or_else(|| {
            const MEDIAN_PERCENT: f64 = 0.1;
            let median = (population_size as f64 * MEDIAN_PERCENT).round() as usize;
            let score_fn = score.clone();
            Arc::new(move |population, spawn| {
                let rng = &mut rand::rng();
                let scores: Vec<f64> = population
                    .iter()
                    .map(|individual| score_fn(&individual.lock().unwrap()))
                    .collect();
                let index = mate_selection::RankedExponential(median).pairs(rng, spawn, scores);
                index
                    .iter()
                    .map(|parents| parents.iter().map(|&i| population[i].clone()).collect())
                    .collect()
            })
        });
        let mut this = Evolution {
            path,
            replacement: replacement.unwrap_or(Replacement::Generation),
            selection,
            score,
            population_size,
            leaderboard_size,
            hall_of_fame_size,
            ascension: 0,
            generation: 0,
            members: Default::default(),
            waiting: Default::default(),
            leaderboard: Default::default(),
            hall_of_fame: Default::default(),
            parents: vec![],
        };
        this.load()?;
        Ok(this)
    }
    fn save(&self) -> Result<(), Error> {
        let get_name = |indiv: &Arc<Mutex<Individual>>| indiv.lock().unwrap().name.clone();
        let metadata = EvolutionMetadata {
            ascension: self.ascension,
            generation: self.generation,
            members: self.members.iter().map(get_name).collect(),
            waiting: self.waiting.iter().map(get_name).collect(),
            leaderboard: self.leaderboard.iter().map(get_name).collect(),
            hall_of_fame: self.hall_of_fame.iter().map(get_name).collect(),
        };
        let path = self.get_metadata_path();
        std::fs::write(path, serde_json::to_vec(&metadata).unwrap())?;
        Ok(())
    }
    fn load(&mut self) -> Result<(), Error> {
        let path = self.get_metadata_path();
        if !path.exists() {
            return Ok(());
        }
        let metadata: EvolutionMetadata = serde_json::from_slice(&std::fs::read(&path)?).unwrap();
        self.ascension = metadata.ascension;
        self.generation = metadata.generation;
        //
        let individuals: HashMap<String, Arc<Mutex<Individual>>> = Individual::load_dir(&self.path)?
            .into_iter()
            .map(|individual| (individual.name.to_string(), Arc::from(Mutex::from(individual))))
            .collect();
        let lookup = |individual: &String| individuals.get(individual).unwrap().clone();
        self.members = metadata.members.iter().map(lookup).collect();
        self.waiting = metadata.waiting.iter().map(lookup).collect();
        self.leaderboard = metadata.leaderboard.iter().map(lookup).collect();
        self.hall_of_fame = metadata.hall_of_fame.iter().map(lookup).collect();
        // Sort the historical data to enforce invariants.
        self.leaderboard.sort_by(compare_scores(self.score.as_ref()));
        self.hall_of_fame
            .sort_by_key(|x| x.lock().unwrap().ascension.unwrap_or(u64::MAX));
        Ok(())
    }
    /// Get the `path` argument or a temporary directory.
    pub fn get_path(&self) -> &Path {
        &self.path
    }
    fn get_metadata_path(&self) -> PathBuf {
        self.path.join("population.json")
    }
    /// Get the `replacement` argument.
    pub fn get_replacement(&self) -> Replacement {
        self.replacement
    }
    /// Get the `population_size` argument.
    pub fn get_population_size(&self) -> usize {
        self.population_size
    }
    /// Get the total number of individuals that have died.
    pub fn get_ascension(&self) -> u64 {
        self.ascension
    }
    /// Get the number of cohorts of `population_size` that have died.
    pub fn get_generation(&self) -> u64 {
        self.generation
    }
    /// Get the current members of the population.
    ///
    /// All modifications must be saved to file using `individual.save("")`
    pub fn get_members(&self) -> &[Arc<Mutex<Individual>>] {
        &self.members
    }
    /// Get the highest scoring individuals ever recorded. This is sorted
    /// descending by score, so that `leaderboard[0]` is the best individual.
    pub fn get_leaderboard(&self) -> &[Arc<Mutex<Individual>>] {
        &self.leaderboard
    }
    /// Get the highest scoring individuals from each generation. This is sorted
    /// by ascension, so that `hall_of_fame[0]` is the oldest.
    pub fn get_hall_of_fame(&self) -> &[Arc<Mutex<Individual>>] {
        &self.hall_of_fame
    }
    /// Get a list of parents to be mated together to produce a child.
    pub fn spawn(&mut self) -> Vec<Arc<Mutex<Individual>>> {
        // Refill parents buffer.
        if self.parents.is_empty() {
            let num_pairs = if self.get_replacement() == Replacement::Generation {
                self.get_population_size()
            } else {
                1
            };
            let members = self.get_members();
            assert!(!members.is_empty(), "population is empty");
            self.parents.extend_from_slice(&(*self.selection)(members, num_pairs));
        }
        let mut parents = self.parents.pop().unwrap();
        // Deduplicate the parents list.
        parents.sort_unstable_by_key(Arc::as_ptr);
        parents.dedup_by_key(|parent| Arc::as_ptr(parent));
        parents
    }
    /// Add a new individual to this population.
    pub fn death(&mut self, mut individual: Individual) -> Result<(), Error> {
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
            Replacement::Unbounded | Replacement::Random | Replacement::Worst | Replacement::Oldest => {
                self.members.push(individual.clone());
            }
            Replacement::Generation => {}
        }
        // Stage the individual for the next generation and bookkeeping.
        self.waiting.push(individual.clone());
        if self.waiting.len() >= self.population_size {
            self.rollover()?;
        }
        Ok(())
    }
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
        self.leaderboard.sort_by(compare_scores(self.score.as_ref()));
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
    fn uuid4_len() {
        for _ in 0..100 {
            assert_eq!(uuid4().len(), 32);
        }
    }
    #[test]
    fn uuid4_unique() {
        use std::collections::HashSet;
        let unique = 1000;
        assert_eq!((0..unique).map(|_| uuid4()).collect::<HashSet<String>>().len(), unique);
    }
    #[test]
    fn indiv_save_load() {
        let mut indiv1 = Individual::new("foo", "bar", &["ctrl", "prog"], Box::new(*b"beepboop"));
        indiv1.extra.insert("X".into(), "Y".into());
        let path = dbg!(indiv1.save(std::env::temp_dir())).unwrap();
        let indiv2 = Individual::load(path).unwrap();
        indiv1.genome();
        indiv2.genome();
        assert_eq!(indiv1, indiv2);
    }
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
        assert_eq!(cmp_indiv(pop1.get_leaderboard()), cmp_indiv(pop2.get_leaderboard()));
        assert_eq!(cmp_indiv(pop1.get_hall_of_fame()), cmp_indiv(pop2.get_hall_of_fame()));
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
            let abs_dif = a.iter().zip(b).map(|(&x, &y)| (x as f64 - y as f64).abs()).sum::<f64>();
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
        assert!(best.lock().unwrap().score.as_ref().unwrap().parse::<f64>().unwrap() > -100.0);
    }
}
