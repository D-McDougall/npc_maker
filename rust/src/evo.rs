//! Evolution interface, for building and using evolutionary algorithms

use process_anywhere::{Computer, Process};
use serde::Serialize;
use std::io::{self, BufRead, StdinLock, StdoutLock, Write};
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
    fn spawn(&mut self) -> Vec<PathBuf>;

    /// Notify the evolutionary algorithm that the given individual died
    fn death(&mut self, individual: PathBuf);

    /// Receive a non-standard command
    fn custom(&mut self, command: String, arguments: Vec<serde_json::Value>) -> serde_json::Value {
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
        // Lock the standard IO channels
        let stdin = io::stdin();
        let stdout = io::stdout();
        let mut stdin_handle = stdin.lock();
        let mut stdout_handle = stdout.lock();
        /// Helper function for reading input messages from the environment
        fn read_json(stdin_handle: &mut StdinLock) -> Result<(String, Vec<serde_json::Value>), Error> {
            let mut message = String::new();
            stdin_handle.read_line(&mut message)?;
            let mut json: Vec<serde_json::Value> = serde_json::from_str(&message)?;
            assert!(!json.is_empty());
            let command = json.remove(0);
            let arguments = json;
            let Some(command) = command.as_str() else {
                panic!();
            };
            Ok((command.to_string(), arguments))
        }
        /// Helper function for outputting single-line JSON messages
        fn print_json<T: Serialize>(stdout_handle: &mut StdoutLock, message: &T) -> Result<(), Error> {
            let mut json = serde_json::to_string(message)?;
            json.push('\n');
            stdout_handle.write_all(json.as_bytes())?;
            stdout_handle.flush()?;
            Ok(())
        }
        // Command-response loop
        let retval: Result<(), Error> = loop {
            let (command, arguments) = match read_json(&mut stdin_handle) {
                Ok(pair) => pair,
                Err(err) => break Err(err),
            };
            match command.as_str() {
                "spawn" => {
                    let parents = self.spawn();
                    // Convert PathBuf to String
                    let response: Vec<String> = parents.iter().map(|path| format!("{}", path.display())).collect();
                    // Transmit message
                    if let Err(err) = print_json(&mut stdout_handle, &response) {
                        break Err(err);
                    }
                }
                "death" => {
                    assert!(!arguments.is_empty());
                    for path in arguments {
                        let Some(path) = path.as_str() else {
                            panic!();
                        };
                        self.death(path.into());
                    }
                }
                _ => {
                    let response = self.custom(command, arguments);
                    if let Err(err) = print_json(&mut stdout_handle, &response) {
                        break Err(err);
                    }
                }
            }
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
        let response = self.process.block_line()?;
        let parents = serde_json::from_str(&response)?;
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
        let command = serde_json::to_value(command)?;
        // Assemble the message command & arguments
        let mut message = Vec::with_capacity(args.len() + 1);
        message.push(command);
        message.extend_from_slice(args);
        let json = serde_json::to_string(&message)?;
        self.process.send_line(&json)?;
        let response = self.process.block_line()?;
        let value = serde_json::from_str(&response)?;
        Ok(value)
    }
}
