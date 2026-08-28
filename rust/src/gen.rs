//! Genetic Interface, for analyzing and manipulating genetic material

use std::collections::HashMap;
use std::io::{BufRead, BufReader, BufWriter, Result, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::Mutex;

/// Interface for implementing genetic algorithms
#[allow(unused_variables)]
pub trait API {
    fn asex(&mut self, parent: String) -> (Vec<u8>, Vec<u8>);

    fn sex(&mut self, parent_1: String, parent_2: String) -> (Vec<u8>, Vec<u8>);

    /// Receive a custom message from the controller using a new message type
    ///
    /// Optional, panics by default
    fn custom(&mut self, message_type: char, message_body: &str) {
        panic!("unsupported operation: {message_type}")
    }

    /// This method is called just before the controller process exits
    ///
    /// Optional, does nothing by default
    fn quit(&mut self) {}

    /// Run a genetic algorithm program
    ///
    /// This method never returns!
    fn main(&mut self) -> Result<()> {
        todo!()
    }
}
