//! Controller Interface, for making and using control systems
//!
//! Each controller runs in its own computer process and uses its standard I/O
//! channels to communicate with the environment. The interface reserves the
//! standard input and output channels for its normal operations.
//! Controllers should use stderr to report any unformatted or diagnostic
//! messages (see [eprintln!()]).
//! By default, controllers inherit stderr from the environment.

use std::collections::HashMap;
use std::io::{BufRead, BufReader, BufWriter, Result, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::Mutex;

fn clean_path(path: impl AsRef<Path>) -> Result<PathBuf> {
    let path = path.as_ref();
    // Expand home directory.
    let mut path_iter = path.components();
    if let Some(root) = path_iter.next() {
        if root == std::path::Component::Normal(std::ffi::OsStr::new("~")) {
            let mut path = std::env::home_dir().expect("File Error: failed to find the user's home directory");
            path.extend(path_iter);
            let path = path.canonicalize()?;
            return Ok(path);
        }
    }
    let path = path.canonicalize()?;
    Ok(path)
}

/// Interface for executing controller programs.
///
/// This object runs an instance of a controller and provides methods for using it.
///
/// This object's destruction causes the controller to terminate.
#[derive(Debug)]
pub struct Controller {
    environment: PathBuf,
    population: String,
    command: Vec<String>,
    ctrl: Child,
    stdin: BufWriter<ChildStdin>,
    stdout: BufReader<ChildStdout>,
}

impl Controller {
    /// Argument `environment` is the file path of the current environment specification file.
    ///
    /// Argument `population` is a name and a key into the environment spec's "populations" table.
    ///
    /// Argument `command` is the command line invocation for the controller program. \
    /// The first string in the list is the program, the remaining strings are its command line arguments.
    pub fn new(environment: impl AsRef<Path>, population: &str, command: Vec<String>) -> Result<Self> {
        // Clean the arguments.
        let environment = clean_path(environment)?;
        let population = population.to_string();
        let program = clean_path(&command[0])?;
        let environment_path = environment.to_str().unwrap();
        debug_assert!(!environment_path.contains('\n'));
        debug_assert!(!population.contains('\n'));

        // Setup and run the controller command in a subprocess.
        let mut cmd = Command::new(&program);
        cmd.args(&command[1..]);
        cmd.stdin(Stdio::piped());
        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::inherit());
        let mut ctrl = cmd.spawn()?;
        let mut stdin = BufWriter::new(ctrl.stdin.take().unwrap());
        let stdout = BufReader::new(ctrl.stdout.take().unwrap());

        //
        writeln!(stdin, "E{environment_path}")?;
        writeln!(stdin, "P{population}")?;

        Ok(Self {
            environment,
            population,
            command,
            ctrl,
            stdin,
            stdout,
        })
    }

    /// Get the `environment` argument.
    pub fn get_environment(&self) -> &Path {
        &self.environment
    }

    /// Get the `population` argument.
    pub fn get_population(&self) -> &str {
        &self.population
    }

    /// Get the `command` argument.
    pub fn get_command(&self) -> &[String] {
        &self.command
    }

    /// Check if the controller process is still running.
    pub fn is_alive(&mut self) -> Result<bool> {
        let exit_status_code = self.ctrl.try_wait()?;
        Ok(exit_status_code.is_none())
    }

    /// Initialize the control system with a new genome. \
    /// This discards the currently loaded model.
    ///
    /// Argument value must be a single line.
    pub fn genome(&mut self, value: &[u8]) -> Result<()> {
        writeln!(self.stdin, "G{}", value.len())?;
        self.stdin.write_all(value)?;
        Ok(())
    }

    /// Reset the control system to its initial state.
    pub fn reset(&mut self) -> Result<()> {
        writeln!(self.stdin, "R")?;
        Ok(())
    }

    /// Advance the control system's internal state.
    pub fn advance(&mut self, dt: f64) -> Result<()> {
        writeln!(self.stdin, "A{dt}")?;
        Ok(())
    }

    /// Write a single value to a GIN in the controller.
    pub fn set_input(&mut self, gin: u64, value: &str) -> Result<()> {
        debug_assert!(!value.contains('\n'));
        writeln!(self.stdin, "I{gin}\n{value}")?;
        Ok(())
    }

    /// Write an array of bytes to a GIN in the controller.
    pub fn set_binary(&mut self, gin: u64, value: &[u8]) -> Result<()> {
        writeln!(self.stdin, "B{gin}:\n{}", value.len())?;
        self.stdin.write_all(value)?;
        Ok(())
    }

    /// Retrieve a list of outputs, as identified by their GIN.
    ///
    /// This method blocks on IO.
    pub fn get_outputs(&mut self, gin_list: &[u64]) -> Result<HashMap<u64, String>> {
        // Request the outputs.
        for gin in gin_list {
            writeln!(self.stdin, "O{gin}")?;
        }
        self.stdin.flush()?;
        // Wait for the controller to respond.
        let mut outputs = HashMap::<u64, String>::new();
        let mut message = String::new();
        while outputs.len() < gin_list.len() {
            message.clear();
            self.stdout.read_line(&mut message)?;
            message.pop(); // Discard the trailing newline.
            debug_assert!(&message[..1] == "O");
            let gin = message[1..].parse().unwrap();
            message.clear();
            self.stdout.read_line(&mut message)?;
            message.pop(); // Discard the trailing newline.
            outputs.insert(gin, std::mem::take(&mut message));
        }
        Ok(outputs)
    }

    /// Save the current state of the control system to file.
    pub fn save(&mut self) -> Result<()> {
        writeln!(self.stdin, "S")?;
        self.stdin.flush()?;
        Ok(())
    }

    ///  Load the state of the control system from file.
    pub fn load(&mut self, save_state: &[u8]) -> Result<()> {
        writeln!(self.stdin, "L{}", save_state.len())?;
        self.stdin.write_all(save_state)?;
        Ok(())
    }

    /// Send a custom message to the controller using a new message type.
    pub fn custom(&mut self, message_type: char, message_body: &str) -> Result<()> {
        debug_assert!(message_type == message_type.to_ascii_uppercase());
        debug_assert!(!"EPGRAIBOSL".contains(message_type));
        debug_assert!(!message_body.contains('\n'));
        writeln!(self.stdin, "{message_type}{message_body}")?;
        Ok(())
    }
}

/// Structure of all messages sent from environments to controllers.
///
/// These messages are transmitted over the controller's stdin channel.
#[derive(Debug, Clone, PartialEq)]
pub enum Message {
    Environment { environment: PathBuf },
    Population { population: String },
    Genome { value: Box<[u8]> },
    Reset,
    Advance { dt: f64 },
    SetInput { gin: u64, value: String },
    SetBinary { gin: u64, value: Box<[u8]> },
    GetOutput { gin: u64 },
    Save,
    Load { save_state: Box<[u8]> },
    Custom { message_type: char, body: String },
    Quit,
}

impl Message {
    /// Format this message and write it to the given stream.
    pub fn write(&self, writer: &mut impl Write) -> Result<()> {
        match self {
            Self::Environment { environment } => {
                writeln!(writer, "E{}", environment.to_str().unwrap())?;
            }
            Self::Population { population } => {
                writeln!(writer, "P{population}")?;
            }
            Self::Genome { value } => {
                writeln!(writer, "G{}", value.len())?;
                writer.write_all(value)?;
            }
            Self::Reset => {
                writeln!(writer, "R")?;
            }
            Self::Advance { dt } => {
                writeln!(writer, "A{dt}")?;
            }
            Self::SetInput { gin, value } => {
                writeln!(writer, "I{gin}\n{value}")?;
            }
            Self::SetBinary { gin, value } => {
                writeln!(writer, "B{gin}\n{}", value.len())?;
                writer.write_all(value)?;
            }
            Self::GetOutput { gin } => {
                writeln!(writer, "O{gin}")?;
            }
            Self::Save => {
                writeln!(writer, "S")?;
            }
            Self::Load { save_state } => {
                writeln!(writer, "L{}", save_state.len())?;
                writer.write_all(save_state)?;
            }
            Self::Custom { message_type, body } => {
                writeln!(writer, "{message_type}{body}")?;
            }
            Self::Quit => {}
        }
        Ok(())
    }

    /// Parse the next message from the given input stream. Blocking.
    pub fn read(reader: &mut impl BufRead) -> Result<Message> {
        let mut line = String::new();
        while line.is_empty() {
            let bytes_read = reader.read_line(&mut line)?;
            if bytes_read == 0 {
                return Ok(Self::Quit);
            }
            line.pop(); // Remove the trailing newline.
        }
        let msg_type = line.chars().next().unwrap();
        let msg_body = &line[msg_type.len_utf8()..];
        let msg_data = match msg_type.to_ascii_uppercase() {
            'E' => Self::Environment {
                environment: msg_body.trim().into(),
            },
            'P' => Self::Population {
                population: msg_body.trim().to_string(),
            },
            'G' => {
                let num_bytes = msg_body.trim().parse::<usize>().unwrap();
                let value = crate::read_bytes(reader, num_bytes)?;
                Self::Genome { value }
            }
            'R' => Self::Reset,
            'I' => {
                let gin = msg_body.trim().parse::<u64>().unwrap();
                let mut value = String::new();
                reader.read_line(&mut value)?;
                value.pop(); // Remove the trailing newline.
                Self::SetInput { gin, value }
            }
            'B' => {
                let gin = msg_body.trim().parse::<u64>().unwrap();
                let mut num_bytes = String::new();
                reader.read_line(&mut num_bytes)?;
                let num_bytes = num_bytes.trim().parse::<usize>().unwrap();
                let value = crate::read_bytes(reader, num_bytes)?;
                Self::SetBinary { gin, value }
            }
            'A' => Self::Advance {
                dt: msg_body.trim().parse::<f64>().unwrap(),
            },
            'O' => Self::GetOutput {
                gin: msg_body.trim().parse::<u64>().unwrap(),
            },
            'S' => Self::Save,
            'L' => {
                let num_bytes = msg_body.trim().parse::<usize>().unwrap();
                let save_state = crate::read_bytes(reader, num_bytes)?;
                Self::Load { save_state }
            }
            _ => Self::Custom {
                message_type: msg_type,
                body: msg_body.to_string(),
            },
        };
        Ok(msg_data)
    }
}

// Store these in global variables so that the main function is can be re-entered in case of error.
static ENVIRONMENT: Mutex<Option<PathBuf>> = Mutex::new(None);
static POPULATION: Mutex<Option<String>> = Mutex::new(None);

/// Interface for implementing controllers.
#[allow(unused_variables)]
pub trait API {
    /// Run a controller program.
    ///
    /// This method handles communications between the controller (this program) and
    /// the environment. It reads and parses messages from stdin, interfaces with
    /// your implementation of the API trait, and writes messages to stdout.
    ///
    /// This method never returns!
    fn main(&mut self) -> Result<()> {
        loop {
            // Wait for the next message from the environment.
            let message = Message::read(&mut std::io::stdin().lock())?;
            match message {
                Message::Environment { environment } => {
                    ENVIRONMENT.lock().unwrap().replace(environment);
                }
                Message::Population { population } => {
                    POPULATION.lock().unwrap().replace(population);
                }
                Message::Genome { value } => {
                    // Wait for the locks.
                    let environment_lock = ENVIRONMENT.lock().unwrap();
                    let population_lock = POPULATION.lock().unwrap();
                    // Borrow the data.
                    let environment = environment_lock.as_ref();
                    let population = population_lock.as_ref();
                    // Fill in missing values.
                    let environment = match environment {
                        Some(ref_path_buf) => ref_path_buf.as_path(),
                        None => Path::new(""),
                    };
                    let population = match population {
                        Some(ref_string) => ref_string.as_str(),
                        None => "",
                    };
                    self.genome(environment, population, value);
                }
                Message::Reset => {
                    self.reset();
                }
                Message::Advance { dt } => {
                    debug_assert!(dt >= 0.0);
                    self.advance(dt);
                }
                Message::SetInput { gin, value } => {
                    self.set_input(gin, value);
                }
                Message::SetBinary { gin, value } => {
                    self.set_binary(gin, value);
                }
                Message::GetOutput { gin } => {
                    let value = self.get_output(gin);
                    debug_assert!(!value.contains('\n'));
                    println!("O{gin}\n{value}");
                    std::io::stdout().flush()?;
                }
                Message::Save => {
                    let save_state = self.save();
                    println!("S{}", save_state.len());
                    std::io::stdout().write_all(&save_state)?;
                    std::io::stdout().flush()?;
                }
                Message::Load { save_state } => {
                    self.load(save_state);
                }
                Message::Custom { message_type, body } => {
                    self.custom(message_type, &body);
                }
                Message::Quit => {
                    break;
                }
            }
        }
        self.quit();
        Ok(())
    }

    /// Discard the current model and load a new one.
    ///
    /// The environment and population will not change during the lifetime of
    /// the controller's computer process.
    ///
    /// Argument value is the parameters for the new control system.
    fn genome(&mut self, environment: &Path, population: &str, value: Box<[u8]>);

    /// Reset the currently loaded model to it's initial state.
    fn reset(&mut self);

    /// Argument dt is the time period to advance over, measured in seconds.
    fn advance(&mut self, dt: f64);

    /// Receive data from the environment into the controller.
    fn set_input(&mut self, gin: u64, value: String);

    /// Receive an array of bytes from the environment into the controller.
    ///
    /// Optional, panics by default.
    #[allow(clippy::boxed_local)]
    fn set_binary(&mut self, gin: u64, value: Box<[u8]>) {
        panic!("unsupported operation: set_binary")
    }

    /// The environment has requested that the controller send it an output.
    fn get_output(&mut self, gin: u64) -> String;

    /// Save the current state of the controller to file.
    ///
    /// Optional, panics by default.
    fn save(&mut self) -> Box<[u8]> {
        panic!("unsupported operation: save")
    }

    /// Load the state of a controller from file.
    ///
    /// Optional, panics by default.
    #[allow(clippy::boxed_local)]
    fn load(&mut self, save_state: Box<[u8]>) {
        panic!("unsupported operation: load")
    }

    /// Receive a custom message from the controller using a new message type.
    ///
    /// Optional, panics by default.
    fn custom(&mut self, message_type: char, message_body: &str) {
        panic!("unsupported operation: {message_type}")
    }

    /// This method is called just before the controller process exits.
    ///
    /// Optional, does nothing by default.
    fn quit(&mut self) {}
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn message_roundtrip() {
        let test_messages = [
            Message::Environment {
                environment: PathBuf::from("test/jungle123"),
            },
            Message::Environment {
                environment: PathBuf::from(""),
            },
            Message::Environment {
                environment: PathBuf::from("/ \" _^ .?`~@!#$%^&*()_+-=[{]};:',<.>/?"),
            },
            Message::Population {
                population: "zebra".to_string(),
            },
            Message::Population {
                population: "".to_string(),
            },
            Message::Population {
                population: ". .".to_string(),
            },
            //
            Message::Genome {
                value: Box::new([0, 1, 2]),
            },
            Message::Genome {
                value: "test123".as_bytes().into(),
            },
            Message::Genome {
                value: "".as_bytes().into(),
            },
            Message::Genome {
                value: "] } ){([\\n\" ".as_bytes().into(),
            },
            //
            Message::Reset,
            //
            Message::Advance { dt: 0.123 },
            Message::Advance { dt: -0.123 },
            Message::Advance { dt: 0.0 },
            Message::Advance { dt: 123456789e12 },
            //
            Message::SetInput {
                gin: 42,
                value: "42".to_string(),
            },
            Message::SetInput {
                gin: 43,
                value: "-1234.56e-4".to_string(),
            },
            // Test that single strings are processed exactly as they are.
            Message::SetInput {
                gin: 44,
                value: "".to_string(),
            },
            Message::SetInput {
                gin: 45,
                value: " ".to_string(),
            },
            Message::SetInput {
                gin: 46,
                value: ": ".to_string(),
            },
            Message::SetInput {
                gin: 47,
                value: "\t".to_string(),
            },
            Message::SetInput {
                gin: 48,
                value: "~!@#$%^&*()_+-={}[]:'<>,./?|".to_string(),
            },
            // Test that it does NOT parse quotes.
            Message::SetInput {
                gin: 50,
                value: r#"""#.to_string(),
            },
            // Test that it does NOT interpret backslashes as escapes.
            Message::SetInput {
                gin: 49,
                value: r#"\"#.to_string(),
            },
            Message::SetInput {
                gin: 50,
                value: r#"\n"#.to_string(),
            },
            //
            Message::SetBinary {
                gin: 100,
                value: "123456789".as_bytes().into(),
            },
            Message::SetBinary {
                gin: 100,
                value: "".as_bytes().into(),
            },
            Message::SetBinary {
                gin: 100,
                value: " ".as_bytes().into(),
            },
            Message::SetBinary {
                gin: 100,
                value: "\"\\n\n\x00".as_bytes().into(),
            },
            //
            Message::GetOutput { gin: 0 },
            Message::GetOutput { gin: 100 },
            Message::GetOutput { gin: u64::MAX },
            //
            Message::Save,
            //
            Message::Load {
                save_state: "\\tmp\\my_save_file.".as_bytes().into(),
            },
            //
            Message::Custom {
                message_type: '~',
                body: ":hello custom message:".to_string(),
            },
            Message::Custom {
                message_type: '$',
                body: "".to_string(),
            },
            Message::Custom {
                message_type: '!',
                body: " \t ".to_string(),
            },
        ];

        for original in test_messages {
            let mut message = vec![];
            original.write(&mut message).unwrap();
            let returned = Message::read(&mut message.as_slice()).unwrap();
            assert_eq!(original, returned);
        }
    }
}
