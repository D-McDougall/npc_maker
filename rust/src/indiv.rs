//! Data structure and persistence for an individual life-form.

use serde::{Deserialize, Serialize};
use std::ffi::OsString;
use std::collections::HashMap;
use std::io::{BufRead, BufReader, BufWriter, Read, Result, Write, Error};
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

    /// Save an individual to a file.
    ///
    /// The method creates the directory and writes four files:
    ///
    /// ```text
    /// <path>/
    /// ├── metadata.json
    /// ├── genome
    /// ├── epigenome
    /// └── phenome
    /// ```
    ///
    pub fn save(&self, path: impl AsRef<Path>, genome: &[u8], epigenome: &[u8], phenome: &[u8]) -> Result<()> {
        let path = path.as_ref();

        // Make the directory in case this is the first individual to be saved to it.
        if !path.exists() {
            std::fs::create_dir(&path)?;
        }

        // 
        let path = path.join(&self.name);
        fs::create_dir(&path)?;

        // Serialize the protobuf message using protobuf-JSON.
        let metadata = serde_json::to_vec_pretty(self)?;

        fs::write(path.join("metadata.json"), metadata)?;
        fs::write(path.join("genome"), genome)?;
        fs::write(path.join("epigenome"), epigenome)?;
        fs::write(path.join("phenome"), phenome)?;

        Ok(())
    }

    /// Loads an individual's metadata, genome, epigenome, and phenome
    /// from the specified directory.
    pub fn load(path: impl AsRef<Path>) -> Result<(Self, Box<[u8]>, Box<[u8]>, Box<[u8]>)> {
        let path = path.as_ref();

        let metadata_file = File::open(path.join("metadata.json"))?;
        let individual = serde_json::from_reader(metadata_file)?;

        let genome = fs::read(path.join("genome"))?.into_boxed_slice();
        let epigenome = fs::read(path.join("epigenome"))?.into_boxed_slice();
        let phenome = fs::read(path.join("phenome"))?.into_boxed_slice();

        Ok((individual, genome, epigenome, phenome))
    }

    /// Remove this individual's data directory
    pub fn delete(path: impl AsRef<Path>) -> Result<()> {
        let path = path.as_ref();
        // Check for the expected files before deleting the directory
        let expected = [
            "metadata.json",
            "genome",
            "epigenome",
            "phenome",
        ];
        fn unexpected_file(name: &OsString) -> Result<()> {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                format!("unexpected file in individual directory: {}", name.to_string_lossy()),
            ));
        }
        let mut entries = fs::read_dir(path)?;
        for entry in &mut entries {
            let entry = entry?;
            let name = entry.file_name();
            if !expected.iter().any(|expected| name == *expected) {
                return unexpected_file(&name);
            }
            if !entry.file_type()?.is_file() {
                return unexpected_file(&name);
            }
        }
        for name in expected {
            fs::remove_file(path.join(name))?;
        }
        fs::remove_dir(path)?;
        Ok(())
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
        let individual = Individual {
            name: name.to_string(),
            environment: Some("test-environment".to_string()),
            body_type: Some("test-body".to_string()),
            controller: vec!["test-controller".to_string()],
            score: Some(42.5),
            telemetry: [
                ("temperature".to_string(), "20".to_string()),
            ]
            .into_iter()
            .collect(),
            species: Some("test-species".to_string()),
            parents: vec!["foo".to_string(), "bar".to_string()],
            children: Some(3),
            generation: Some(4),
            ascension: Some(5),
            ..Default::default()
        };

        let genome = b"genome data";
        let epigenome = b"epigenome data";
        let phenome = b"phenome data";

        let path = temp_dir().join("individual");

        individual
            .save(&path, genome, epigenome, phenome)
            .unwrap();

        let (loaded, loaded_genome, loaded_epigenome, loaded_phenome) =
            Individual::load(path.join(&name)).unwrap();

        assert_eq!(loaded, individual);
        assert_eq!(&*loaded_genome, genome);
        assert_eq!(&*loaded_epigenome, epigenome);
        assert_eq!(&*loaded_phenome, phenome);

        Individual::delete(path.join(&name)).unwrap();
        Individual::load(path.join(&name)).unwrap_err();
    }
}
