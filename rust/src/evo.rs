//! Evolution interface, for building and using evolutionary algorithms

use crate::indiv::Individual;
use std::path::{Path, PathBuf};
use std::io::{BufRead, BufReader, BufWriter, Write};
use process_anywhere::{Computer, Process};

pub struct Error {
    Io(io::Error)
}

/// Interface for implementing evolutionary algorithms
#[allow(unused_variables)]
pub trait API {
    /// Pick a set of parent genomes to reproduce
    ///
    /// Returns a list of file-paths to individual files. The returned
    /// individuals must have been given to the `death()` method. The number
    /// of individuals returned controls the action taken by the caller.
    ///
    /// | # Parents | Action |
    /// | ------: | ------ |
    /// | 0  | Use the initial genetic material |
    /// | 1  | Asexually reproduce the parent |
    /// | 2  | Sexually reproduce the parents |
    /// | 3+ | Unspecified |
    fn spawn(&mut self) -> Vec<&Individual>;

    /// Notify the evolutionary algorithm that the given individual died
    fn death(&mut self, individual: Individual);

    /// Receive a non-standard command.
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
            loop {
            // Wait for the next message from the environment.
            handle.read_line(&mut message)?;
            let json: Vec<serde_json::Value> = serde_json::from_str(&message).unwrap();
            let command = json.remove(0);
            todo!();
            match command {
                "spawn" => {}
                "death" => {
                    // self.death()
                }
                _ => {
                    // self.custom(command)
                }
            }
        }
        self.quit();
        Ok(())
    }
}

/// An instance of an evolutionary algorithm
///
/// Contains a running instance of an evolutionary algorithm running in a
/// subprocess. Destroying this object terminates the subprocess.
pub struct Evolution {
    process: Box<Process>,
}

impl Evolution {
    /// Starts a new subprocess running the given command
    pub fn new(computer: Arc<Computer>, command: &[&str]) -> Result<Self, ()> {
        let process = Process::new(computer, command).unwrap();
        Ok(Self {
            process
        })
    }

    /// Request a set of parents to mate together
    pub fn spawn(&mut self) -> Result<Vec<PathBuf>, ()> {
        self.process.send_line(r#"["spawn"]"#).unwrap();
        let result = self.process.block_line().unwrap();
        serde_json::from_str(&result).unwrap()
    }

    /// Notify the evolutionary algorithm that the given individual has died
    pub fn death(&mut self, individual: &Path) -> Result<(), ()> {
        self.process.computer().send_file(individual).unwrap();
        let message = format!(r#"["death", "{}"]"#, individual);
        self.process.send_line(&message).unwrap();
        todo!()
    }
}
