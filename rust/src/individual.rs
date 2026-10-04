//! Data structure and persistence for an individual life-form.

use std::io::{Result, Write};
use std::path::Path;
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
    ///
    /// The caller must set the genome, epigenome, and phenome attributes.
    pub fn new() -> Individual {
        Individual {
            metadata: Some(Metadata {
                name: uuid4(),
                species: Some(uuid4()),
                generation: 0,
                ..Default::default()
            }),
            ..Default::default()
        }
    }

    /// Reproduce the given individuals.
    ///
    /// Argument parents is a list of Individuals. The child inherits its
    /// environment, body type, controller, and species from the first parent,
    /// and is one generation older than its oldest parent (the parent with the
    /// highest generation, where an unset generation counts as zero). Parents
    /// are recorded in the order given, which may include repeats. Each distinct
    /// parent counts the child once in its `children`.
    ///
    /// Returns the child.
    ///
    /// The child's other fields are unset, in particular it does not inherit the
    /// parents' score, telemetry, epigenome, or extra fields. If the first parent
    /// has no species then neither does the child.
    ///
    /// The caller must set the genome, epigenome, and phenome attributes.
    ///
    /// The parents are modified: each one's `children` is incremented. Rust does
    /// not allow the same `&mut Individual` to be passed twice, so a repeated
    /// parent must be passed as separate copies of the individual. Every copy is
    /// updated, so that none of them is missing the new child.
    pub fn reproduce(parents: &mut [&mut Individual]) -> Individual {
        let first = parents[0].metadata();
        let generation = parents
            .iter()
            .map(|parent| parent.metadata().generation.unwrap_or(0))
            .max()
            .unwrap()
            + 1;
        let child = Individual {
            metadata: Some(Metadata {
                name: uuid4(),
                environment: first.environment.clone(),
                body_type: first.body_type.clone(),
                controller: first.controller.clone(),
                species: first.species.clone(),
                parents: parents.iter().map(|parent| parent.metadata().name.clone()).collect(),
                generation: Some(generation),
                ..Default::default()
            }),
            ..Default::default()
        };

        for parent in parents.iter_mut() {
            let metadata = parent.metadata.as_mut().unwrap();
            metadata.children = Some(metadata.children.unwrap_or(0) + 1);
        }
        child
    }

    pub fn metadata(&self) -> &Metadata {
        parent.metadata.as_ref().expect("Individual must have metadata")
    }
    pub fn score(&self) -> Option<f64> {
        self.metadata().score.clone()
    }
    pub fn ascension(&self) -> Option<u64> {
        self.metadata().ascension.clone()
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
        let name = self.metadata().name.as_str();
        let path = path.join(name);
        fs::create_dir(&path)?; // Do not allow overwrite

        // Serialize the protobuf message using protobuf-JSON.
        let metadata = serde_json::to_vec_pretty(self.metadata())?;

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
        let directories = fs::read_dir(path)?
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

        individual.save(&path).unwrap();

        let loaded = Individual::load(path.join(&name)).unwrap();

        assert_eq!(loaded, individual);

        Individual::delete(path.join(&name)).unwrap();
        Individual::load(path.join(&name)).unwrap_err();
    }

    /// Metadata of an individual, which must have some.
    fn meta(individual: &Individual) -> &Metadata {
        // TODO: Claude: Please replace this function and all calls to it with
        // the new method: `Individual.metadata()`
        individual.metadata.as_ref().unwrap()
    }

    /// An individual with every metadata field populated.
    fn full_individual(name: &str, generation: Option<u64>) -> Individual {
        Individual {
            metadata: Some(Metadata {
                name: name.to_string(),
                environment: Some("test-env".to_string()),
                body_type: Some("test-body".to_string()),
                controller: vec!["test-ctrl".to_string(), "--flag".to_string()],
                score: Some(42.5),
                telemetry: [("temperature".to_string(), "20".to_string())].into_iter().collect(),
                species: Some(format!("{name}-species")),
                parents: vec!["grandparent".to_string()],
                children: Some(3),
                generation,
                ascension: Some(5),
                birth_date: Some(Default::default()),
                death_date: Some(Default::default()),
                extra: Some(Default::default()),
            }),
            genome: Some(b"genome".to_vec()),
            epigenome: Some(b"epigenome".to_vec()),
            phenome: Some(b"phenome".to_vec()),
        }
    }

    #[test]
    fn new_individual() {
        let individual = Individual::new();
        let metadata = individual.metadata();
        assert_eq!(metadata.name.len(), 32);
        assert!(
            metadata
                .name
                .chars()
                .all(|c| c.is_ascii_digit() || ('A'..='F').contains(&c))
        );
        let species = metadata.species.as_ref().unwrap();
        assert_eq!(species.len(), 32);
        assert_ne!(species, &metadata.name);
        // Everything else is unset
        assert_eq!(
            *metadata,
            Metadata {
                name: metadata.name.clone(),
                species: metadata.species.clone(),
                ..Default::default()
            }
        );
        assert_eq!(individual.genome, None);
        assert_eq!(individual.epigenome, None);
        assert_eq!(individual.phenome, None);
    }

    #[test]
    fn new_individuals_are_unique() {
        use std::collections::HashSet;
        let individuals: Vec<_> = (0..1000).map(|_| Individual::new()).collect();
        let names: HashSet<_> = individuals.iter().map(|i| meta(i).name.clone()).collect();
        let species: HashSet<_> = individuals.iter().map(|i| meta(i).species.clone()).collect();
        assert_eq!(names.len(), 1000);
        assert_eq!(species.len(), 1000);
    }

    #[test]
    fn reproduce_one_parent() {
        let mut parent = full_individual("PARENT", Some(3));
        let before = parent.clone();
        let child = Individual::reproduce(&mut [&mut parent]);
        let (child, parent_meta) = (meta(&child), meta(&parent));
        // Inherited
        assert_eq!(child.environment.as_deref(), Some("test-env"));
        assert_eq!(child.body_type.as_deref(), Some("test-body"));
        assert_eq!(child.controller, vec!["test-ctrl", "--flag"]);
        assert_eq!(child.species.as_deref(), Some("PARENT-species"));
        // Lineage
        assert_eq!(child.parents, vec!["PARENT"]);
        assert_eq!(child.generation, Some(4));
        assert_ne!(child.name, "PARENT");
        assert_eq!(child.name.len(), 32);
        // Not inherited
        assert_eq!(child.score, None);
        assert!(child.telemetry.is_empty());
        assert_eq!(child.children, None);
        assert_eq!(child.ascension, None);
        assert_eq!(child.birth_date, None);
        assert_eq!(child.death_date, None);
        assert_eq!(child.extra, None);
        // The parent counted the child, and is otherwise unchanged
        assert_eq!(parent_meta.children, Some(4));
        let mut expected = meta(&before).clone();
        expected.children = Some(4);
        assert_eq!(*parent_meta, expected);
        assert_eq!(parent.genome, before.genome);
    }

    #[test]
    fn reproduce_does_not_set_genetic_data() {
        let mut parent = full_individual("PARENT", Some(0));
        let child = Individual::reproduce(&mut [&mut parent]);
        assert_eq!(child.genome, None);
        assert_eq!(child.epigenome, None);
        assert_eq!(child.phenome, None);
    }

    #[test]
    fn reproduce_unset_generation_counts_as_zero() {
        let mut parent = Individual::new();
        let child = Individual::reproduce(&mut [&mut parent]);
        assert_eq!(meta(&child).generation, Some(1));
        let mut grandparent = Individual::new();
        meta_mut(&mut grandparent).generation = Some(0);
        let child = Individual::reproduce(&mut [&mut grandparent]);
        assert_eq!(meta(&child).generation, Some(1));
    }

    fn meta_mut(individual: &mut Individual) -> &mut Metadata {
        individual.metadata.as_mut().unwrap()
    }

    #[test]
    fn reproduce_many_parents() {
        let mut mother = full_individual("MOTHER", Some(2));
        let mut father = full_individual("FATHER", Some(7));
        meta_mut(&mut father).environment = Some("other-env".to_string());
        meta_mut(&mut father).children = None;
        let mut third = full_individual("THIRD", None);
        let child = Individual::reproduce(&mut [&mut mother, &mut father, &mut third]);
        let child = meta(&child);
        // The first parent is the template, not the oldest parent.
        assert_eq!(child.environment.as_deref(), Some("test-env"));
        assert_eq!(child.species.as_deref(), Some("MOTHER-species"));
        // Parents are in the order given, and generation comes from the oldest.
        assert_eq!(child.parents, vec!["MOTHER", "FATHER", "THIRD"]);
        assert_eq!(child.generation, Some(8));
        // Every parent counted the child, starting from zero if unset.
        assert_eq!(meta(&mother).children, Some(4));
        assert_eq!(meta(&father).children, Some(1));
        assert_eq!(meta(&third).children, Some(4));
    }

    #[test]
    fn reproduce_repeated_parent() {
        // Separate copies of the same individual
        let mut a = full_individual("TWIN", Some(1));
        let mut b = a.clone();
        let child = Individual::reproduce(&mut [&mut a, &mut b]);
        assert_eq!(meta(&child).parents, vec!["TWIN", "TWIN"]);
        assert_eq!(meta(&child).generation, Some(2));
        // Each copy counts the child once, so they remain identical.
        assert_eq!(meta(&a).children, Some(4));
        assert_eq!(a, b);
    }

    #[test]
    fn reproduce_without_parent_species() {
        // The child inherits the lack of species, it is not given a new one.
        let mut parent = full_individual("PARENT", Some(0));
        meta_mut(&mut parent).species = None;
        meta_mut(&mut parent).environment = None;
        let child = Individual::reproduce(&mut [&mut parent]);
        assert_eq!(meta(&child).species, None);
        assert_eq!(meta(&child).environment, None);
    }

    #[test]
    fn reproduce_children_have_distinct_names() {
        let mut parent = Individual::new();
        let a = Individual::reproduce(&mut [&mut parent]);
        let b = Individual::reproduce(&mut [&mut parent]);
        assert_ne!(meta(&a).name, meta(&b).name);
        assert_eq!(meta(&parent).children, Some(2));
    }

    #[test]
    #[should_panic(expected = "at least one parent")]
    fn reproduce_requires_parents() {
        Individual::reproduce(&mut []);
    }

    #[test]
    #[should_panic(expected = "parents must have metadata")]
    fn reproduce_requires_metadata() {
        let mut parent = Individual::default();
        Individual::reproduce(&mut [&mut parent]);
    }

    #[test]
    fn reproduce_save_load_round_trip() {
        let mut parent = full_individual("PARENT", Some(0));
        let mut child = Individual::reproduce(&mut [&mut parent]);
        child.genome = Some(b"child genome".to_vec());
        child.epigenome = Some(b"child epigenome".to_vec());
        child.phenome = Some(b"child phenome".to_vec());
        let path = temp_dir().join(format!("individual-{}", uuid4()));
        child.save(&path).unwrap();
        let loaded = Individual::load(path.join(&meta(&child).name)).unwrap();
        assert_eq!(loaded, child);
        std::fs::remove_dir_all(&path).unwrap();
    }
}
