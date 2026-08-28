//! Data structure to represent an individual life-form

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader, BufWriter, Read, Result, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};

/// Generate a universally unique name. This will never return the same name twice.
fn uuid4() -> String {
    let uuid: u128 = rand::random();
    format!("{uuid:032X}")
}

/// Container for a distinct life-form and all of its associated data
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct Individual {
    /// Name or UUID of this individual
    #[serde(default)]
    pub name: String,

    /// Number of individuals who died before this one,
    /// or None if this individual has not yet died
    #[serde(default)]
    pub ascension: Option<u64>,

    /// Name of the environment that this individual lives in
    #[serde(default)]
    pub environment: String,

    /// Name of the body_type that this individual uses
    #[serde(default)]
    pub body_type: String,

    /// Name or UUID of this individual's species.
    /// Mating may be restricted to individuals of the same species.
    #[serde(default)]
    pub species: String,

    /// Command line invocation of the controller program
    #[serde(default)]
    pub controller: Vec<String>,

    /// Genetic parameters for this individual
    #[serde(skip)]
    pub genome: OnceLock<Arc<[u8]>>,

    /// The environmental info dictionary. The environment updates this information.
    #[serde(default)]
    pub telemetry: HashMap<String, String>,

    /// The epigenetic info dictionary. The controller updates this information.
    #[serde(default)]
    pub epigenome: HashMap<String, String>,

    /// Reproductive fitness of this individual, as assessed by the environment
    #[serde(default)]
    pub score: Option<String>,

    /// Number of cohorts that passed before this individual was born
    #[serde(default)]
    pub generation: u64,

    /// The names of this individual's parents
    #[serde(default)]
    pub parents: Vec<String>,

    /// The names of this individual's children
    #[serde(default)]
    pub children: Vec<String>,

    /// Time of birth, as a UTC timestamp, or an empty string if this individual
    /// has not yet been born
    #[serde(default)]
    pub birth_date: String,

    /// Time of death, as a UTC timestamp, or an empty string if this individual
    /// has not yet died
    #[serde(default)]
    pub death_date: String,

    /// Custom / unofficial fields that are saved with the individual
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,

    /// The file path this individual was loaded from or saved to, or None
    /// if this individual has not touched the file system
    #[serde(skip)]
    pub path: Option<PathBuf>,
}

impl Individual {
    /// Create a new individual. This is used to initialize new populations
    pub fn new(environment: &str, body_type: &str, controller: &[&str], genome: Box<[u8]>) -> Individual {
        assert!(!controller.is_empty());
        assert!(!genome.is_empty());
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
    pub fn genome(&self) -> Result<Arc<[u8]>> {
        Ok(self
            .genome
            .get_or_init(|| {
                // Unwrap everything because "get_or_try_init" is unstable.
                let path = self.path.as_ref().expect("missing genome");
                let mut file = BufReader::new(File::open(path).unwrap());
                file.skip_until(b'\0').expect("missing genome");
                let mut data = vec![];
                file.read_to_end(&mut data).unwrap();
                Arc::from(data)
            })
            .clone())
    }

    /// Asexually reproduce an individual
    pub fn asex(&mut self, child_genome: &[u8]) -> Individual {
        assert!(!child_genome.is_empty());
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

    // TODO: Sex allows more than two parents, and should not crash with only one parent.

    /// Sexually reproduce two individuals
    pub fn sex(&mut self, other: &mut Individual, child_genome: &[u8]) -> Individual {
        assert!(!child_genome.is_empty());
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

    /// Save an individual to a file
    ///
    /// Argument path is the directory to save in. Optional, use empty string
    /// to either overwrite the previous save-file or to use a temporary directory.
    /// The filename will be the individual's name with the ".indiv" file extension.
    ///
    /// Returns the file path of the saved individual.
    pub fn save(&mut self, path: impl AsRef<Path>) -> Result<&Path> {
        let mut path: PathBuf = path.as_ref().into();
        // Fill in default path.
        if path.to_str() == Some("") {
            if let Some(save_file) = self.path.as_ref() {
                path = save_file.parent().unwrap().into();
            } else {
                path = std::env::temp_dir();
            }
        }
        // Load genome from file before modifying the file system.
        self.genome()?;
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
        buf.write_all(&self.genome()?)?;
        let file = buf.into_inner()?; // flush the buffer
        file.sync_all()?; // push to disk
        std::fs::rename(&temp, &path)?; // move file into place
        self.path = Some(path);
        self.genome.take(); // free the genome
        Ok(self.path.as_ref().unwrap())
    }

    /// Load a previously saved individual
    ///
    /// The file extension must be ".indiv"
    pub fn load(path: impl AsRef<Path>) -> Result<Individual> {
        let path = path.as_ref().to_path_buf();
        // assert!(path.get_ext() == ".indiv"); // TODO
        let mut file = BufReader::new(File::open(&path)?);
        let mut text = vec![];
        file.read_until(b'\0', &mut text)?;
        text.pop_if(|&mut char| char == b'\0');
        let mut individual: Individual = serde_json::from_slice(&text)?;
        individual.path = Some(path);
        Ok(individual)
    }

    /// Get all individuals saved in a directory
    pub fn load_dir(path: impl AsRef<Path>) -> Result<Vec<Individual>> {
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

    /// Remove this individual and its associated save file
    pub fn delete(self) -> Result<()> {
        if let Some(path) = self.path {
            std::fs::remove_file(path)?;
        }
        Ok(())
    }

    /// Delete the individual if this is the last reference to it
    pub fn drop(this: Arc<Mutex<Self>>) -> Result<()> {
        if let Some(mutex) = Arc::into_inner(this) {
            let individual = mutex.into_inner().unwrap();
            individual.delete()?;
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
        let mut a = Individual::new("env", "body", &["ctrl"], Box::new(*b"genome"));
        let path = a.save("").unwrap();
        let b = Individual::load(path).unwrap();
        assert_eq!(a, b);
        b.delete().unwrap();
    }
}
