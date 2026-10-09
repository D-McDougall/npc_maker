//! Artificial regulatory network control system for the NPC Maker.
//!
//! This implements the gRPC `controller.Controller` service. Each `Session` RPC
//! is one controller instance, with its own private network state, so a single
//! process can serve every AI agent in an environment.
//!
//! All errors are session-level: a failure terminates the session with a gRPC
//! `Status`, and errors are never returned in the response stream.

use ndarray::{Array1, Array2};
use npc_maker::controller::{
    ControllerRequest, ControllerResponse, IoValue, controller_request::Command, controller_server::Controller,
    io_value::Value,
};
use serde::Deserialize;
use tokio::sync::mpsc;
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Request, Response, Status, Streaming};

pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Temperature to use when neither the phenome nor the command line gives one.
pub const DEFAULT_TEMPERATURE: f64 = 1.0;

pub const HELP: &str = r#"Artificial regulatory network control system for the NPC Maker

USAGE: arn [OPTIONS]

SERVER OPTIONS:
    --listen <ADDRESS:PORT>       Bind to IP address and port (default 127.0.0.1:47001)
    --host <ADDRESS>              Bind to IP address
    --port <PORT>                 Bind to port number

NETWORK OPTIONS:
    --temperature <T>             Temperature for phenomes which do not specify
                                  one, a non-negative number (default 1.0)

GENERAL OPTIONS:
        --version                 Print version information
    -h, --help                    Print this help message
"#;

/// The decoded phenome.
#[derive(Deserialize)]
#[allow(non_snake_case)]
struct Phenome {
    /// Temperature, optional. If missing then the default temperature is used.
    T: Option<f64>,

    /// Number of genes
    N: usize,

    /// Input gene names
    I: Vec<Vec<usize>>,

    /// Output gene names
    O: Vec<Vec<usize>>,

    /// Weights matrix, flattened in row-major order
    W: Vec<f64>,
}

/// The dynamical system.
#[derive(Debug)]
pub struct RegulatoryNetwork {
    temperature: f64,
    matrix: Array2<f64>,
    inputs: Vec<Vec<usize>>,
    outputs: Vec<Vec<usize>>,
    queue: Vec<(usize, f64)>,
    state: Array1<f64>,
}

impl RegulatoryNetwork {
    /// Build a network from a UTF-8 JSON phenome.
    ///
    /// The temperature comes from the phenome if it specifies one, which takes
    /// precedence, and otherwise it is `default_temperature`.
    pub fn from_phenome(phenome: &[u8], default_temperature: f64) -> Result<Self, Status> {
        let Phenome {
            T: temperature,
            N,
            I,
            O,
            W,
        } = serde_json::from_slice(phenome)
            .map_err(|error| Status::invalid_argument(format!("invalid phenome: {error}")))?;
        let temperature = temperature.unwrap_or(default_temperature);
        if !(temperature.is_finite() && temperature >= 0.0) {
            return Err(Status::invalid_argument(
                "invalid temperature: T must be finite and non-negative",
            ));
        }
        if N == 0 {
            return Err(Status::invalid_argument("invalid phenome: N must be positive"));
        }
        if N.checked_mul(N) != Some(W.len()) {
            return Err(Status::invalid_argument(format!(
                "invalid phenome: W has {} elements, expected N*N = {}*{}",
                W.len(),
                N,
                N
            )));
        }
        for (label, interfaces) in [("I", &I), ("O", &O)] {
            for genes in interfaces {
                if let Some(bad) = genes.iter().find(|gene| **gene >= N) {
                    return Err(Status::invalid_argument(format!(
                        "invalid phenome: {label} contains gene index {bad}, but N = {N}"
                    )));
                }
            }
        }
        let matrix = Array2::from_shape_vec((N, N), W)
            .map_err(|error| Status::invalid_argument(format!("invalid phenome: {error}")))?;
        Ok(Self {
            temperature,
            matrix,
            inputs: I,
            outputs: O,
            queue: vec![],
            state: Array1::from_elem(N, 1.0),
        })
    }

    fn num_states(&self) -> usize {
        self.state.len()
    }

    /// Return to the initial state, discarding any queued inputs.
    pub fn reset(&mut self) {
        self.queue.clear();
        self.state.fill(1.0);
    }

    /// Queue sensory inputs. They take effect on the next call to `advance`.
    ///
    /// Either all of the inputs are queued or, on error, none are.
    pub fn set_inputs(&mut self, values: &[IoValue]) -> Result<(), Status> {
        let mut queue = Vec::with_capacity(values.len());
        for IoValue { id, value } in values {
            let index = usize::try_from(*id)
                .ok()
                .filter(|index| *index < self.inputs.len())
                .ok_or_else(|| {
                    Status::invalid_argument(format!("unknown input interface {id}, there are {}", self.inputs.len()))
                })?;
            let Some(Value::Number(number)) = value else {
                return Err(Status::invalid_argument(format!(
                    "input interface {id} requires a number"
                )));
            };
            if !number.is_finite() {
                return Err(Status::invalid_argument(format!(
                    "input interface {id} requires a finite number"
                )));
            }
            queue.push((index, *number));
        }
        self.queue.extend(queue);
        Ok(())
    }

    /// Read motor outputs. Each output is the mean concentration of its genes,
    /// or zero if the interface has no genes.
    pub fn get_outputs(&self, ids: &[u64]) -> Result<Vec<IoValue>, Status> {
        ids.iter()
            .map(|id| {
                let indices = usize::try_from(*id)
                    .ok()
                    .and_then(|index| self.outputs.get(index))
                    .ok_or_else(|| {
                        Status::invalid_argument(format!(
                            "unknown output interface {id}, there are {}",
                            self.outputs.len()
                        ))
                    })?;
                let value = if indices.is_empty() {
                    0.0
                } else {
                    indices.iter().map(|gene| self.state[*gene]).sum::<f64>() / indices.len() as f64
                };
                Ok(IoValue {
                    id: *id,
                    value: Some(Value::Number(value)),
                })
            })
            .collect()
    }

    /// Advance the state of the network by `dt` seconds.
    pub fn advance(&mut self, dt: f64) -> Result<(), Status> {
        if !(dt.is_finite() && dt >= 0.0) {
            return Err(Status::invalid_argument(format!(
                "dt must be finite and non-negative, found {dt}"
            )));
        }
        let mut input_delta = Array1::<f64>::zeros(self.num_states());
        for (index, value) in self.queue.drain(..) {
            for gene_index in &self.inputs[index] {
                input_delta[*gene_index] += dt * self.temperature * value
            }
        }
        let state_delta = dt * self.temperature * &self.state * self.matrix.dot(&self.state);
        self.state = &self.state + state_delta + input_delta;
        for x in &mut self.state {
            *x = x.max(0.0);
        }
        self.state *= self.num_states() as f64 / self.state.sum();
        Ok(())
    }
}

/// The state of one controller session.
///
/// This holds no I/O, so that it can be tested without a network connection.
#[derive(Debug)]
pub struct Session {
    /// Temperature for phenomes which do not specify one.
    temperature: f64,
    network: Option<RegulatoryNetwork>,
}

impl Default for Session {
    fn default() -> Self {
        Self::new(DEFAULT_TEMPERATURE)
    }
}

impl Session {
    /// Start a session. The `temperature` is used if the phenome does not
    /// specify one.
    pub fn new(temperature: f64) -> Self {
        Self {
            temperature,
            network: None,
        }
    }

    /// Process one command.
    ///
    /// Only `GetOutputs` commands produce a response. Any `Err` is a
    /// session-level failure, and the caller must end the session.
    pub fn handle(&mut self, request: ControllerRequest) -> Result<Option<ControllerResponse>, Status> {
        let ControllerRequest { request_id, command } = request;
        let Some(command) = command else {
            return Err(Status::invalid_argument("missing command"));
        };
        match command {
            // A session is initialized exactly once.
            Command::Initialize(_) if self.network.is_some() => {
                Err(Status::failed_precondition("controller is already initialized"))
            }
            Command::Initialize(request) => {
                self.network = Some(RegulatoryNetwork::from_phenome(&request.phenome, self.temperature)?);
                Ok(None)
            }
            // Resetting an uninitialized controller does nothing, by definition.
            Command::Reset(_) => {
                if let Some(network) = &mut self.network {
                    network.reset();
                }
                Ok(None)
            }
            Command::Advance(request) => {
                self.network()?.advance(request.dt)?;
                Ok(None)
            }
            Command::SetInputs(request) => {
                self.network()?.set_inputs(&request.inputs)?;
                Ok(None)
            }
            Command::GetOutputs(request) => {
                let outputs = self.network()?.get_outputs(&request.ids)?;
                Ok(Some(ControllerResponse { request_id, outputs }))
            }
        }
    }

    fn network(&mut self) -> Result<&mut RegulatoryNetwork, Status> {
        self.network
            .as_mut()
            .ok_or_else(|| Status::failed_precondition("controller is not initialized"))
    }
}

/// The gRPC service. Each session owns its own network, the only thing shared
/// between sessions is the default temperature.
#[derive(Debug)]
pub struct ArnController {
    temperature: f64,
}

impl ArnController {
    /// Serve sessions, using `temperature` for every phenome which does not
    /// specify one.
    pub fn new(temperature: f64) -> Self {
        Self { temperature }
    }
}

impl Default for ArnController {
    fn default() -> Self {
        Self::new(DEFAULT_TEMPERATURE)
    }
}

#[tonic::async_trait]
impl Controller for ArnController {
    type SessionStream = ReceiverStream<Result<ControllerResponse, Status>>;

    async fn session(
        &self,
        request: Request<Streaming<ControllerRequest>>,
    ) -> Result<Response<Self::SessionStream>, Status> {
        let mut inbound = request.into_inner();
        let (outbound, receiver) = mpsc::channel(16);
        let temperature = self.temperature;
        tokio::spawn(async move {
            let mut session = Session::new(temperature);
            // Commands are processed sequentially, in the order received.
            // The loop ends when the environment closes the stream, when the
            // connection fails, or on the first session-level error.
            while let Ok(Some(request)) = inbound.message().await {
                match session.handle(request) {
                    Ok(None) => {}
                    Ok(Some(response)) => {
                        if outbound.send(Ok(response)).await.is_err() {
                            break; // Environment hung up
                        }
                    }
                    Err(status) => {
                        let _ = outbound.send(Err(status)).await;
                        break;
                    }
                }
            }
        });
        Ok(Response::new(ReceiverStream::new(receiver)))
    }
}

/// Settings for running the server.
#[derive(Debug, PartialEq)]
pub struct Options {
    /// Address to serve on, as "host:port".
    pub listen: String,

    /// Temperature for phenomes which do not specify one. If this is `None`
    /// then use `DEFAULT_TEMPERATURE`.
    pub temperature: Option<f64>,
}

/// The result of parsing the command line.
#[derive(Debug, PartialEq)]
pub enum Cli {
    /// Run the server.
    Serve(Options),

    /// Print this text and exit successfully.
    Print(String),
}

/// Parse the argument of the `--temperature` flag.
fn parse_temperature(text: &str) -> Result<f64, String> {
    match text.parse::<f64>() {
        Ok(temperature) if temperature.is_finite() && temperature >= 0.0 => Ok(temperature),
        _ => Err(format!(
            "expected a finite non-negative number for --temperature, found {text}"
        )),
    }
}

/// Parse the command line arguments, where `args[0]` is the program name.
pub fn parse_args(args: &[String]) -> Result<Cli, String> {
    let (mut host, mut port, mut listen, mut temperature) = (None, None, None, None);
    let mut args = args.iter().skip(1);
    while let Some(flag) = args.next() {
        let slot = match flag.as_str() {
            "--host" => &mut host,
            "--port" => &mut port,
            "--listen" => &mut listen,
            "--temperature" => &mut temperature,
            "--version" => return Ok(Cli::Print(VERSION.to_string())),
            "-h" | "--help" => return Ok(Cli::Print(HELP.to_string())),
            _ => return Err(format!("unrecognized argument: {flag}")),
        };
        if slot.is_some() {
            return Err(format!("duplicate flag {flag}"));
        }
        let Some(value) = args.next() else {
            return Err(format!("expected a value after {flag}"));
        };
        *slot = Some(value.clone());
    }
    if listen.is_some() && (host.is_some() || port.is_some()) {
        return Err("options --host & --port are incompatible with --listen".to_string());
    }
    let listen = match listen {
        Some(listen) => listen,
        None => {
            if let Some(port) = &port
                && port.parse::<u16>().is_err()
            {
                return Err(format!("expected port number [0-65535], found {port}"));
            }
            let host = host.unwrap_or_else(|| "127.0.0.1".to_string());
            let port = port.unwrap_or_else(|| "47001".to_string());
            format!("{host}:{port}")
        }
    };
    let temperature = temperature.map(|text| parse_temperature(&text)).transpose()?;
    Ok(Cli::Serve(Options { listen, temperature }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use npc_maker::controller::{AdvanceRequest, GetOutputsRequest, InitializeRequest, ResetRequest, SetInputsRequest};

    const EPSILON: f64 = 1e-12;

    fn phenome(t: f64, n: usize, i: &str, o: &str, w: &[f64]) -> Vec<u8> {
        format!(r#"{{"T":{t},"N":{n},"I":{i},"O":{o},"W":{w:?}}}"#).into_bytes()
    }

    fn request(command: Command) -> ControllerRequest {
        ControllerRequest {
            request_id: 0,
            command: Some(command),
        }
    }

    fn init(phenome: Vec<u8>) -> ControllerRequest {
        request(Command::Initialize(InitializeRequest { phenome }))
    }

    fn advance(dt: f64) -> ControllerRequest {
        request(Command::Advance(AdvanceRequest { dt }))
    }

    fn number(id: u64, value: f64) -> IoValue {
        IoValue {
            id,
            value: Some(Value::Number(value)),
        }
    }

    fn inputs(values: Vec<IoValue>) -> ControllerRequest {
        request(Command::SetInputs(SetInputsRequest { inputs: values }))
    }

    fn outputs(request_id: u64, ids: Vec<u64>) -> ControllerRequest {
        ControllerRequest {
            request_id,
            command: Some(Command::GetOutputs(GetOutputsRequest { ids })),
        }
    }

    /// Run `get_outputs` and unwrap the numbers.
    fn read(session: &mut Session, ids: Vec<u64>) -> Vec<f64> {
        let response = session.handle(outputs(0, ids)).unwrap().unwrap();
        response
            .outputs
            .into_iter()
            .map(|io| match io.value {
                Some(Value::Number(x)) => x,
                other => panic!("expected a number, found {other:?}"),
            })
            .collect()
    }

    fn assert_close(actual: &[f64], expected: &[f64]) {
        assert_eq!(actual.len(), expected.len());
        for (a, e) in actual.iter().zip(expected) {
            assert!((a - e).abs() < EPSILON, "{actual:?} != {expected:?}");
        }
    }

    /// Two genes, no coupling, gene 0 is the input and gene 1 is the output.
    fn simple() -> Vec<u8> {
        phenome(1.0, 2, "[[0]]", "[[1]]", &[0.0; 4])
    }

    #[test]
    fn initial_state_is_one() {
        let mut session = Session::default();
        assert!(session.handle(init(simple())).unwrap().is_none());
        assert_close(&read(&mut session, vec![0]), &[1.0]);
    }

    #[test]
    fn inputs_apply_on_advance_then_renormalize() {
        let mut session = Session::default();
        session.handle(init(simple())).unwrap();
        assert!(session.handle(inputs(vec![number(0, 1.0)])).unwrap().is_none());
        // Nothing happens until advance.
        assert_close(&read(&mut session, vec![0]), &[1.0]);
        assert!(session.handle(advance(1.0)).unwrap().is_none());
        // Gene 0: 1 + dt*T*1 = 2, gene 1: 1. Renormalized to sum N = 2.
        assert_close(&read(&mut session, vec![0]), &[2.0 / 3.0]);
        // The queue was drained, so a second advance only renormalizes.
        session.handle(advance(1.0)).unwrap();
        assert_close(&read(&mut session, vec![0]), &[2.0 / 3.0]);
    }

    #[test]
    fn dynamics_follow_the_weights_matrix() {
        // Gene 0 grows: delta = dt*T*c0*(W c)_0 = 0.5*2*1*1 = 1.
        let mut session = Session::default();
        let w = [1.0, 0.0, 0.0, 0.0];
        session.handle(init(phenome(2.0, 2, "[]", "[[0],[1]]", &w))).unwrap();
        session.handle(advance(0.5)).unwrap();
        assert_close(&read(&mut session, vec![0, 1]), &[4.0 / 3.0, 2.0 / 3.0]);
    }

    #[test]
    fn negative_concentrations_are_clamped() {
        let mut session = Session::default();
        let w = [-3.0, 0.0, 0.0, 0.0];
        session.handle(init(phenome(1.0, 2, "[]", "[[0],[1]]", &w))).unwrap();
        session.handle(advance(1.0)).unwrap();
        // [1-3, 1] clamps to [0, 1] and renormalizes to [0, 2].
        assert_close(&read(&mut session, vec![0, 1]), &[0.0, 2.0]);
    }

    #[test]
    fn outputs_average_their_genes_and_empty_is_zero() {
        let mut session = Session::default();
        let w = [0.0; 9];
        session
            .handle(init(phenome(1.0, 3, "[[0],[1],[2]]", "[[0,1],[],[2,2]]", &w)))
            .unwrap();
        session.handle(inputs(vec![number(0, 3.0)])).unwrap();
        session.handle(advance(1.0)).unwrap();
        // State [4,1,1] renormalized by 3/6 to [2, 0.5, 0.5].
        assert_close(&read(&mut session, vec![0, 1, 2]), &[1.25, 0.0, 0.5]);
        // Requests may repeat and reorder IDs.
        assert_close(&read(&mut session, vec![2, 0, 2]), &[0.5, 1.25, 0.5]);
        // An empty list gets an empty response.
        assert!(read(&mut session, vec![]).is_empty());
    }

    #[test]
    fn response_echoes_request_id_and_output_ids() {
        let mut session = Session::default();
        session.handle(init(simple())).unwrap();
        let response = session.handle(outputs(41, vec![0])).unwrap().unwrap();
        assert_eq!(response.request_id, 41);
        assert_eq!(response.outputs[0].id, 0);
    }

    #[test]
    fn reset_restores_state_and_clears_queued_inputs() {
        let mut session = Session::default();
        session.handle(init(simple())).unwrap();
        session.handle(inputs(vec![number(0, 5.0)])).unwrap();
        session.handle(advance(1.0)).unwrap();
        session.handle(inputs(vec![number(0, 5.0)])).unwrap();
        assert!(
            session
                .handle(request(Command::Reset(ResetRequest {})))
                .unwrap()
                .is_none()
        );
        assert_close(&read(&mut session, vec![0]), &[1.0]);
        // The pending input was discarded, so advancing changes nothing.
        session.handle(advance(1.0)).unwrap();
        assert_close(&read(&mut session, vec![0]), &[1.0]);
    }

    #[test]
    fn reset_before_initialize_is_a_noop() {
        let mut session = Session::default();
        assert!(
            session
                .handle(request(Command::Reset(ResetRequest {})))
                .unwrap()
                .is_none()
        );
    }

    #[test]
    fn commands_before_initialize_fail() {
        for command in [advance(1.0), inputs(vec![]), outputs(0, vec![])] {
            let status = Session::default().handle(command).unwrap_err();
            assert_eq!(status.code(), tonic::Code::FailedPrecondition);
        }
    }

    #[test]
    fn initialize_twice_fails() {
        let mut session = Session::default();
        session.handle(init(simple())).unwrap();
        // The same phenome, a different phenome, and a broken phenome are all
        // refused for the same reason: the session is already initialized.
        for second in [simple(), phenome(2.0, 3, "[]", "[]", &[0.0; 9]), b"hello".to_vec()] {
            let status = session.handle(init(second)).unwrap_err();
            assert_eq!(status.code(), tonic::Code::FailedPrecondition);
        }
    }

    #[test]
    fn initialize_twice_fails_even_after_other_commands() {
        let mut session = Session::default();
        session.handle(init(simple())).unwrap();
        session.handle(inputs(vec![number(0, 1.0)])).unwrap();
        session.handle(advance(1.0)).unwrap();
        session.handle(request(Command::Reset(ResetRequest {}))).unwrap();
        let status = session.handle(init(simple())).unwrap_err();
        assert_eq!(status.code(), tonic::Code::FailedPrecondition);
    }

    #[test]
    fn failed_initialize_does_not_count_as_initialized() {
        // Sessions end on error, but the handler itself must not be left
        // half-initialized by a phenome which was rejected.
        let mut session = Session::default();
        let status = session.handle(init(b"hello".to_vec())).unwrap_err();
        assert_eq!(status.code(), tonic::Code::InvalidArgument);
        session.handle(init(simple())).unwrap();
        assert_close(&read(&mut session, vec![0]), &[1.0]);
    }

    /// Two uncoupled genes, where gene 0 is the input, and both genes are outputs.
    /// This phenome does not specify a temperature.
    fn no_temperature() -> Vec<u8> {
        br#"{"N":2,"I":[[0]],"O":[[0],[1]],"W":[0,0,0,0]}"#.to_vec()
    }

    /// The same network as `no_temperature`, with the temperature specified.
    fn with_temperature(temperature: f64) -> Vec<u8> {
        phenome(temperature, 2, "[[0]]", "[[0],[1]]", &[0.0; 4])
    }

    /// Drive gene 0 with an input of 1 for one second, returns the outputs.
    fn drive(session: &mut Session, phenome: Vec<u8>) -> Vec<f64> {
        session.handle(init(phenome)).unwrap();
        session.handle(inputs(vec![number(0, 1.0)])).unwrap();
        session.handle(advance(1.0)).unwrap();
        read(session, vec![0, 1])
    }

    #[test]
    fn missing_temperature_uses_the_default() {
        // T = 1: gene 0 is 1+1 = 2 and gene 1 is 1, renormalized by 2/3.
        let expected = [4.0 / 3.0, 2.0 / 3.0];
        assert_close(&drive(&mut Session::default(), no_temperature()), &expected);
        assert_close(
            &drive(&mut Session::new(DEFAULT_TEMPERATURE), no_temperature()),
            &expected,
        );
        // The default is the same as an explicit T of 1.
        assert_close(&drive(&mut Session::default(), with_temperature(1.0)), &expected);
    }

    #[test]
    fn missing_temperature_uses_the_session_temperature() {
        // T = 2: gene 0 is 1+2 = 3 and gene 1 is 1, renormalized by 2/4.
        let outputs = drive(&mut Session::new(2.0), no_temperature());
        assert_close(&outputs, &[1.5, 0.5]);
        // T = 0: the network is frozen.
        let outputs = drive(&mut Session::new(0.0), no_temperature());
        assert_close(&outputs, &[1.0, 1.0]);
    }

    #[test]
    fn null_temperature_is_missing() {
        let phenome = br#"{"T":null,"N":2,"I":[[0]],"O":[[0],[1]],"W":[0,0,0,0]}"#.to_vec();
        assert_close(&drive(&mut Session::new(2.0), phenome), &[1.5, 0.5]);
    }

    #[test]
    fn phenome_temperature_takes_precedence() {
        // The phenome says T = 1, so the session temperature of 5 is ignored.
        let outputs = drive(&mut Session::new(5.0), with_temperature(1.0));
        assert_close(&outputs, &[4.0 / 3.0, 2.0 / 3.0]);
        // Even a phenome temperature of zero is a choice, not a missing value.
        let outputs = drive(&mut Session::new(5.0), with_temperature(0.0));
        assert_close(&outputs, &[1.0, 1.0]);
    }

    #[test]
    fn invalid_temperatures_are_rejected() {
        // A bad temperature is rejected wherever it came from.
        let status = Session::new(-1.0).handle(init(no_temperature())).unwrap_err();
        assert_eq!(status.code(), tonic::Code::InvalidArgument);
        let status = Session::new(f64::NAN).handle(init(no_temperature())).unwrap_err();
        assert_eq!(status.code(), tonic::Code::InvalidArgument);
        let status = Session::new(1.0)
            .handle(init(phenome(f64::INFINITY, 2, "[]", "[]", &[0.0; 4])))
            .unwrap_err();
        assert_eq!(status.code(), tonic::Code::InvalidArgument);
    }

    #[test]
    fn missing_command_fails() {
        let status = Session::default()
            .handle(ControllerRequest {
                request_id: 0,
                command: None,
            })
            .unwrap_err();
        assert_eq!(status.code(), tonic::Code::InvalidArgument);
    }

    #[test]
    fn invalid_phenomes_are_rejected() {
        let w4 = [0.0; 4];
        let bad: Vec<(&str, Vec<u8>)> = vec![
            ("not json", b"hello".to_vec()),
            ("empty", vec![]),
            ("missing field", br#"{"T":1.0,"N":1}"#.to_vec()),
            ("negative T", phenome(-1.0, 2, "[]", "[]", &w4)),
            ("N is zero", phenome(1.0, 0, "[]", "[]", &[])),
            ("W too short", phenome(1.0, 2, "[]", "[]", &[0.0; 3])),
            ("W too long", phenome(1.0, 2, "[]", "[]", &[0.0; 5])),
            ("input gene out of range", phenome(1.0, 2, "[[2]]", "[]", &w4)),
            ("output gene out of range", phenome(1.0, 2, "[]", "[[0,9]]", &w4)),
        ];
        for (description, bytes) in bad {
            let status = RegulatoryNetwork::from_phenome(&bytes, DEFAULT_TEMPERATURE).unwrap_err();
            assert_eq!(status.code(), tonic::Code::InvalidArgument, "{description}");
            let status = Session::default().handle(init(bytes)).unwrap_err();
            assert_eq!(status.code(), tonic::Code::InvalidArgument, "{description}");
        }
    }

    #[test]
    fn invalid_inputs_are_rejected_atomically() {
        let mut session = Session::default();
        session.handle(init(simple())).unwrap();
        let bad = vec![
            ("unknown id", vec![number(1, 1.0)]),
            ("huge id", vec![number(u64::MAX, 1.0)]),
            (
                "text",
                vec![IoValue {
                    id: 0,
                    value: Some(Value::Text("1.0".into())),
                }],
            ),
            (
                "blob",
                vec![IoValue {
                    id: 0,
                    value: Some(Value::Blob(vec![1])),
                }],
            ),
            ("unset", vec![IoValue { id: 0, value: None }]),
            ("nan", vec![number(0, f64::NAN)]),
            ("infinity", vec![number(0, f64::INFINITY)]),
            // The first value is valid, but the batch is rejected as a whole.
            ("partial", vec![number(0, 1.0), number(7, 1.0)]),
        ];
        for (description, values) in bad {
            let status = session.handle(inputs(values)).unwrap_err();
            assert_eq!(status.code(), tonic::Code::InvalidArgument, "{description}");
        }
        session.handle(advance(1.0)).unwrap();
        assert_close(&read(&mut session, vec![0]), &[1.0]);
    }

    #[test]
    fn invalid_output_ids_are_rejected() {
        let mut session = Session::default();
        session.handle(init(simple())).unwrap();
        for ids in [vec![1], vec![0, 1], vec![u64::MAX]] {
            let status = session.handle(outputs(0, ids)).unwrap_err();
            assert_eq!(status.code(), tonic::Code::InvalidArgument);
        }
    }

    #[test]
    fn invalid_dt_is_rejected() {
        let mut session = Session::default();
        session.handle(init(simple())).unwrap();
        for dt in [-0.1, f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
            let status = session.handle(advance(dt)).unwrap_err();
            assert_eq!(status.code(), tonic::Code::InvalidArgument, "dt={dt}");
        }
        // Zero is a valid time step.
        session.handle(advance(0.0)).unwrap();
    }

    fn args(args: &[&str]) -> Vec<String> {
        std::iter::once("arn")
            .chain(args.iter().copied())
            .map(String::from)
            .collect()
    }

    #[test]
    fn cli_listen_address() {
        let serve = |s: &str| {
            Ok(Cli::Serve(Options {
                listen: s.to_string(),
                temperature: None,
            }))
        };
        assert_eq!(parse_args(&args(&[])), serve("127.0.0.1:47001"));
        assert_eq!(
            parse_args(&args(&["--listen", "127.0.0.1:5000"])),
            serve("127.0.0.1:5000")
        );
        assert_eq!(parse_args(&args(&["--port", "5000"])), serve("127.0.0.1:5000"));
        assert_eq!(parse_args(&args(&["--host", "0.0.0.0"])), serve("0.0.0.0:47001"));
        assert_eq!(parse_args(&args(&["--host", "::1", "--port", "80"])), serve("::1:80"));
    }

    #[test]
    fn cli_temperature() {
        let serve = |listen: &str, temperature: Option<f64>| {
            Ok(Cli::Serve(Options {
                listen: listen.to_string(),
                temperature,
            }))
        };
        // Optional, so the default is to leave it unset.
        assert_eq!(parse_args(&args(&[])), serve("127.0.0.1:47001", None));
        assert_eq!(
            parse_args(&args(&["--temperature", "2.5"])),
            serve("127.0.0.1:47001", Some(2.5))
        );
        assert_eq!(
            parse_args(&args(&["--temperature", "0"])),
            serve("127.0.0.1:47001", Some(0.0))
        );
        assert_eq!(
            parse_args(&args(&["--temperature", "1e-3"])),
            serve("127.0.0.1:47001", Some(0.001))
        );
        // It combines with every way of choosing the address, in any order.
        assert_eq!(
            parse_args(&args(&["--temperature", "3", "--listen", "127.0.0.1:5000"])),
            serve("127.0.0.1:5000", Some(3.0))
        );
        assert_eq!(
            parse_args(&args(&["--port", "5000", "--temperature", "3"])),
            serve("127.0.0.1:5000", Some(3.0))
        );
    }

    #[test]
    fn cli_errors() {
        for bad in [
            &["--bogus"][..],
            &["--listen"],
            &["--port", "99999"],
            &["--port", "abc"],
            &["--listen", "a:1", "--port", "2"],
            &["--listen", "a:1", "--host", "b"],
            &["--port", "1", "--port", "2"],
            &["--temperature"],
            &["--temperature", "hot"],
            &["--temperature", ""],
            &["--temperature", "-1"],
            &["--temperature", "NaN"],
            &["--temperature", "inf"],
            &["--temperature", "1", "--temperature", "2"],
        ] {
            assert!(parse_args(&args(bad)).is_err(), "{bad:?}");
        }
    }

    #[test]
    fn cli_help_and_version() {
        assert_eq!(parse_args(&args(&["--version"])), Ok(Cli::Print(VERSION.to_string())));
        assert_eq!(parse_args(&args(&["-h"])), Ok(Cli::Print(HELP.to_string())));
        assert_eq!(parse_args(&args(&["--help"])), Ok(Cli::Print(HELP.to_string())));
    }
}
