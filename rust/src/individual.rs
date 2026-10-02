//! Data structure and persistence for an individual life-form.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::ffi::OsString;
use std::io::{BufRead, BufReader, BufWriter, Error, Read, Result, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};
use std::{fs, fs::File};

tonic::include_proto!("individual");
tonic::include_proto!("individual.serde");

/// Generate a universally unique name. This will never return the same name twice.
fn uuid4() -> String {
    let uuid: u128 = rand::random();
    format!("{uuid:032X}")
}

impl Individual {
    /// Create a new individual. This is used to initialize new populations
    pub fn new(environment: &str, body_type: &str, controller: &[&str], genome: Box<[u8]>) -> Individual {
        todo!()
        // assert!(!controller.is_empty());
        // assert!(!genome.is_empty());
        // let mut this = Individual::default();
        // this.name = uuid4();
        // this.environment = environment.to_string();
        // this.body_type = body_type.to_string();
        // this.species = uuid4();
        // this.controller = controller.iter().map(|arg| arg.to_string()).collect();
    }

    ///
    pub fn reproduce(&mut self, child_genome: &[u8]) -> Individual {
        todo!()
        // assert!(!child_genome.is_empty());
        // let individual = Individual {
        //     name: uuid4(),
        //     ascension: None,
        //     environment: self.environment.clone(),
        //     body_type: self.body_type.clone(),
        //     species: self.species.clone(),
        //     controller: self.controller.clone(),
        //     genome: OnceLock::from(Arc::from(child_genome)),
        //     telemetry: HashMap::new(),
        //     epigenome: HashMap::new(),
        //     score: None,
        //     generation: self.generation + 1,
        //     parents: vec![self.name.clone()],
        //     children: vec![],
        //     birth_date: String::new(),
        //     death_date: String::new(),
        //     extra: HashMap::new(),
        //     path: None,
        // };
        // self.children.push(individual.name.clone());
        // individual
    }

    pub fn score(&self) -> Option<f64> {
        self.metadata.as_ref().unwrap().score.clone()
    }
    pub fn ascension(&self) -> Option<u64> {
        self.metadata.as_ref()?.ascension.clone()
    }

    /// Save an individual to file.
    ///
    /// The format for an individual consists of a directory named after the
    /// individual's name, located beneath the directory supplied to `save()`.
    /// The directory contains four files: metadata.json, which contains the
    /// individual's metadata serialized using the protobuf JSON mapping, and
    /// genome, epigenome, and phenome, which contain the corresponding data
    /// as raw binary.
    ///
    /// This method creates the directory and writes four files:
    ///
    /// ```text
    /// <parent>/
    /// └── <individual.name>/
    ///     ├── metadata.json
    ///     ├── genome
    ///     ├── epigenome
    ///     └── phenome
    /// ```
    pub fn save(&self, path: impl AsRef<Path>) -> Result<()> {
        let path = path.as_ref();

        // Make the directory in case this is the first individual to be saved to it.
        if !path.exists() {
            std::fs::create_dir(&path)?;
        }

        // Make directory with this individual's name
        let name = self.metadata.as_ref().unwrap().name.as_str();
        let path = path.join(name);
        fs::create_dir(&path)?; // Do not allow overwrite

        // Serialize the protobuf message using protobuf-JSON.
        let Some(metadata) = &self.metadata else {
            todo!();
        };
        let metadata = serde_json::to_vec_pretty(&metadata)?;

        // Write all data to file
        fs::write(path.join("metadata.json"), metadata)?;
        fs::write(path.join("genome"), self.genome.as_ref().unwrap_or(&vec![]))?;
        fs::write(path.join("epigenome"), self.epigenome.as_ref().unwrap_or(&vec![]))?;
        fs::write(path.join("phenome"), self.phenome.as_ref().unwrap_or(&vec![]))?;
        Ok(())
    }

    /// Loads an individual's metadata, genome, epigenome, and phenome
    /// from the specified directory.
    ///
    /// Returns a tuple of: `(metadata, genome, epigenome, phenome)`
    pub fn load(path: impl AsRef<Path>) -> Result<Individual> {
        let path = path.as_ref();

        let metadata_file = File::open(path.join("metadata.json"))?;
        let metadata = serde_json::from_reader(metadata_file)?;

        let genome = fs::read(path.join("genome"))?;
        let epigenome = fs::read(path.join("epigenome"))?;
        let phenome = fs::read(path.join("phenome"))?;

        Ok(Individual {
            metadata: Some(metadata),
            genome: Some(genome),
            epigenome: Some(epigenome),
            phenome: Some(phenome),
        })
    }

    /// Load every individual stored in the given directory.
    ///
    /// Non-directory entries are ignored. If any subdirectory cannot be
    /// loaded as an individual, the method returns the corresponding error.
    pub fn load_dir(path: impl AsRef<Path>) -> Result<Vec<Metadata>> {
        let mut directories = fs::read_dir(path)?
            .filter_map(|entry| match entry {
                Ok(entry) => match entry.file_type() {
                    Ok(file_type) if file_type.is_dir() => Some(Ok(entry.path())),
                    Ok(_) => None,
                    Err(error) => Some(Err(error)),
                },
                Err(error) => Some(Err(error)),
            })
            .collect::<Result<Vec<_>>>()?;

        // Read the metadata for each individual
        let mut retval = Vec::with_capacity(directories.len());
        for path in directories {
            let metadata_file = File::open(path.join("metadata.json"))?;
            retval.push(serde_json::from_reader(metadata_file)?);
        }
        Ok(retval)
    }

    /// Remove this individual's data directory
    pub fn delete(path: impl AsRef<Path>) -> Result<()> {
        let path = path.as_ref();
        // Check for the metadata file before deleting the directory
        if !path.join("metadata.json").exists() {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                format!("expected metadata.json in individual directory: {}", path.display()),
            ));
        }
        fs::remove_file(path.join("metadata.json"))?;
        fs::remove_file(path.join("genome"))?;
        fs::remove_file(path.join("epigenome"))?;
        fs::remove_file(path.join("phenome"))?;
        fs::remove_dir(path)?;
        Ok(())
    }
}

impl Metadata {
    /// Remove this individual's data directory
    pub fn delete(self, path: impl AsRef<Path>) -> Result<()> {
        Individual::delete(path.as_ref().join(&self.name))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::env::temp_dir;

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
    fn save_load_round_trip() {
        let name = uuid4();
        let metadata = Some(Metadata {
            name: name.to_string(),
            environment: Some("test-environment".to_string()),
            body_type: Some("test-body".to_string()),
            controller: vec!["test-controller".to_string()],
            score: Some(42.5),
            telemetry: [("temperature".to_string(), "20".to_string())].into_iter().collect(),
            species: Some("test-species".to_string()),
            parents: vec!["foo".to_string(), "bar".to_string()],
            children: Some(3),
            generation: Some(4),
            ascension: Some(5),
            ..Default::default()
        });
        let genome = Some(b"genome data".to_vec());
        let epigenome = Some(b"epigenome data".to_vec());
        let phenome = Some(b"phenome data".to_vec());
        let individual = Individual {
            metadata,
            genome,
            epigenome,
            phenome,
        };

        let path = temp_dir().join("individual");

        individual.save(&path, genome, epigenome, phenome).unwrap();

        let (loaded, loaded_genome, loaded_epigenome, loaded_phenome) = Individual::load(path.join(&name)).unwrap();

        assert_eq!(loaded, individual);
        assert_eq!(&*loaded_genome, genome);
        assert_eq!(&*loaded_epigenome, epigenome);
        assert_eq!(&*loaded_phenome, phenome);

        Individual::delete(path.join(&name)).unwrap();
        Individual::load(path.join(&name)).unwrap_err();
    }
}
