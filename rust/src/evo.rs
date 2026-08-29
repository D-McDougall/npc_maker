//! Evolution interface, for building and using evolutionary algorithms

use crate::indiv::Individual;
use process_anywhere::{Computer, Process};
use std::io::{self, BufRead, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;

#[derive(thiserror::Error, Debug)]
pub enum Error {
    #[error("{0}")]
    Subprocess(#[from] process_anywhere::Error),

    #[error("{0}")]
    Io(#[from] io::Error),

    #[error("{0}")]
    Json(#[from] serde_json::Error),
}

/// Interface for implementing evolutionary algorithms
#[allow(unused_variables)]
pub trait API {
    /// Pick a set of parent genomes to reproduce
    ///
    /// Returns a individuals. The returned individuals must have been given
    /// to the `death()` method, and must have a valid path. The number of
    /// individuals returned controls the action taken by the caller.
    ///
    /// | # Parents | Action                           |
    /// | --------: | -------------------------------- |
    /// | 0         | Use the initial genetic material |
    /// | 1         | Asexually reproduce the parent   |
    /// | 2         | Sexually reproduce the parents   |
    /// | 3+        | Unspecified                      |
    fn spawn(&mut self) -> Vec<&Individual>;

    /// Notify the evolutionary algorithm that the given individual died
    fn death(&mut self, individual: Individual);

    /// Receive a non-standard command
    fn custom(&mut self, command: String, arguments: Vec<serde_json::Value>) {
        panic!("unsupported operation: {command}")
    }

    /// This method is called just before the evolution process exits.
    ///
    /// Optional, does nothing by default.
    fn quit(&mut self) {}

    /// Runs an evolutionary algorithm as a program
    ///
    /// This never returns!
    fn main(&mut self) -> Result<(), Error> {
        let stdin = io::stdin();
        let mut handle = stdin.lock();
        let mut message = String::new();
        let retval: Result<(), Error> = 'mainloop: loop {
            // Wait for the next message from the environment.
            if let Err(err) = handle.read_line(&mut message) {
                break 'mainloop Err(err.into());
            }
            let mut json: Vec<serde_json::Value> = match serde_json::from_str(&message) {
                Ok(json) => json,
                Err(err) => break 'mainloop Err(err.into()),
            };
            assert!(!json.is_empty());
            let command = json.remove(0);
            let arguments = json;
            let Some(command) = command.as_str() else {
                panic!();
            };
            match command {
                "spawn" => {
                    let mut parents = self.spawn();
                    let mut response = vec![];
                    for indiv in parents.iter_mut() {
                        let path = indiv.path.as_ref().unwrap();
                        response.push(format!("{}", path.display()));
                    }
                    let response = match serde_json::to_string(&response) {
                        Ok(response) => response,
                        Err(err) => break 'mainloop Err(err.into()),
                    };
                    if let Err(err) = io::stdout().write_all(response.as_bytes()) {
                        break 'mainloop Err(err.into());
                    }
                }
                "death" => {
                    assert!(!arguments.is_empty());
                    for path in arguments {
                        let Some(path) = path.as_str() else {
                            panic!();
                        };
                        let indiv = match Individual::load(path) {
                            Ok(indiv) => indiv,
                            Err(err) => break 'mainloop Err(err.into()),
                        };
                        self.death(indiv);
                    }
                }
                _ => self.custom(command.to_string(), arguments),
            };
        };
        self.quit();
        retval
    }
}

/// An instance of an evolutionary algorithm
///
/// This runs the algorithm runs in a subprocess using the "process_anywhere"
/// library. Destroying this object terminates the subprocess.
pub struct Evolution {
    process: Box<Process>,
}

impl Evolution {
    /// Starts a new subprocess running the given command
    pub fn new(computer: Arc<Computer>, command: &[impl AsRef<str>]) -> Result<Self, Error> {
        let process = Process::new(computer, command).unwrap();
        Ok(Self { process })
    }

    /// Request a set of parents to mate together
    pub fn spawn(&mut self) -> Result<Vec<PathBuf>, Error> {
        self.process.send_line(r#"["spawn"]"#)?;
        let result = self.process.block_line()?;
        let parents = serde_json::from_str(&result)?;
        Ok(parents)
    }

    /// Notify the evolutionary algorithm that the given individual has died
    pub fn death(&mut self, individual: impl AsRef<Path>) -> Result<(), Error> {
        let individual = individual.as_ref();
        self.process.computer().send_file(individual)?;
        let message = format!(r#"["death", "{}"]"#, individual.display());
        self.process.send_line(&message)?;
        Ok(())
    }

    /// Send a non-standard command
    pub fn custom(&mut self, command: &str, args: &[serde_json::Value]) -> Result<serde_json::Value, Error> {
        todo!()
    }
}
