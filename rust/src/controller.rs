//! User-facing API for implementing controller gRPC sessions.
//!
//! Implement `ControllerSession` for the stateful object representing one
//! environment/controller session. `Controller<T>` creates a fresh session
//! for each incoming stream; the adapter owns protobuf validation, streaming,
//! status conversion, and server configuration.

use std::{future::Future, net::SocketAddr, pin::Pin, sync::Arc, task::{Context, Poll, Waker}};

use tonic::{Request, Response, Status, Streaming, transport::Server};
use tokio_stream::wrappers::ReceiverStream;
use tokio::sync::mpsc;

use crate::MAX_MESSAGE_SIZE;

tonic::include_proto!("controller");

/// Implement this trait for the stateful logic of one controller session.
///
/// The generated protobuf `IoValue` is intentionally used directly so
/// implementations can efficiently return a `Vec<IoValue>` without an
/// additional conversion layer. Errors returned by these methods end the
/// current session and are reported as gRPC `INVALID_ARGUMENT`.
pub trait ControllerSession: Send + 'static {
    /// Reset the controller to its initial state.
    fn reset(&mut self) -> Result<(), String> {
        Ok(())
    }

    /// Advance the controller by `dt` seconds.
    fn advance(&mut self, dt: f64) -> Result<(), String> {
        Ok(())
    }

    /// Set sensory input values.
    fn set_inputs(&mut self, inputs: &[IoValue]) -> Result<(), String>;

    /// Return outputs corresponding to the requested IDs.
    ///
    /// Return one value for every requested ID. The adapter validates the
    /// returned IDs and restores request order before sending the response.
    fn get_outputs(&mut self, ids: &[u64]) -> Result<Vec<IoValue>, String>;
}

/// A configured controller server factory.
///
/// The factory is called once per new gRPC stream, after the mandatory
/// Initialize command arrives. It should create a new session from the
/// supplied phenome. Capturing immutable configuration in the factory is
/// supported.
pub struct Controller<T: ControllerSession> {
    factory: Arc<dyn Fn(&[u8]) -> Result<T, String> + Send + Sync>,
}

impl<T: ControllerSession> Clone for Controller<T> {
    fn clone(&self) -> Self {
        Self { factory: Arc::clone(&self.factory) }
    }
}

impl<T: ControllerSession> Controller<T> {
    /// Create a controller server factory from a session constructor.
    pub fn new<F>(factory: F) -> Self
    where
        F: Fn(&[u8]) -> Result<T, String> + Send + Sync + 'static,
    {
        Self { factory: Arc::new(factory) }
    }
}

struct ControllerService<T: ControllerSession> {
    controller: Controller<T>,
}

#[tonic::async_trait]
impl<T: ControllerSession> controller_server::Controller for ControllerService<T> {
    type SessionStream = ReceiverStream<Result<ControllerResponse, Status>>;

    async fn session(
        &self,
        request: Request<Streaming<ControllerRequest>>,
    ) -> Result<Response<Self::SessionStream>, Status> {
        let mut incoming = request.into_inner();
        let (tx, rx) = mpsc::channel(8);
        let factory = Arc::clone(&self.controller.factory);

        tokio::spawn(async move {
            let mut session: Option<T> = None;
            loop {
                let request = match incoming.message().await {
                    Ok(Some(request)) => request,
                    Ok(None) => break,
                    Err(status) => {
                        let _ = tx.send(Err(status)).await;
                        break;
                    }
                };

                let request_id = request.request_id;
                let result = process_request(&mut session, request, factory.as_ref());
                match result {
                    Ok(Some(response)) => {
                        if tx.send(Ok(response)).await.is_err() {
                            break;
                        }
                    }
                    Ok(None) => {}
                    Err(status) => {
                        let _ = tx.send(Err(status)).await;
                        break;
                    }
                }
                let _ = request_id;
            }
        });

        Ok(Response::new(ReceiverStream::new(rx)))
    }
}

fn process_request<T: ControllerSession>(
    session: &mut Option<T>,
    request: ControllerRequest,
    factory: &(dyn Fn(&[u8]) -> Result<T, String> + Send + Sync),
) -> Result<Option<ControllerResponse>, Status> {
    use controller_request::Command;

    let ControllerRequest { request_id, command } = request;
    let command = command.ok_or_else(|| Status::invalid_argument("missing command"))?;
    match command {
        Command::Initialize(request) => {
            if session.is_some() {
                return Err(Status::invalid_argument("controller is already initialized"));
            }
            let created = factory(&request.phenome).map_err(Status::invalid_argument)?;
            *session = Some(created);
            Ok(None)
        }
        Command::Reset(_) => {
            session.as_mut().ok_or_else(|| Status::invalid_argument("controller is not initialized"))?
                .reset().map_err(Status::invalid_argument)?;
            Ok(None)
        }
        Command::Advance(request) => {
            if !(request.dt.is_finite() && request.dt >= 0.0) {
                return Err(Status::invalid_argument("dt must be finite and non-negative"));
            }
            session.as_mut().ok_or_else(|| Status::invalid_argument("controller is not initialized"))?
                .advance(request.dt).map_err(Status::invalid_argument)?;
            Ok(None)
        }
        Command::SetInputs(request) => {
            let mut seen = std::collections::HashSet::with_capacity(request.inputs.len());
            for input in &request.inputs {
                if !seen.insert(input.id) {
                    return Err(Status::invalid_argument(format!("duplicate input ID {}", input.id)));
                }
                if input.value.is_none() {
                    return Err(Status::invalid_argument(format!("input {} has no value", input.id)));
                }
            }
            session.as_mut().ok_or_else(|| Status::invalid_argument("controller is not initialized"))?
                .set_inputs(&request.inputs).map_err(Status::invalid_argument)?;
            Ok(None)
        }
        Command::GetOutputs(request) => {
            let current = session.as_mut().ok_or_else(|| Status::invalid_argument("controller is not initialized"))?;
            let mut seen = std::collections::HashSet::with_capacity(request.ids.len());
            for id in &request.ids {
                if !seen.insert(*id) {
                    return Err(Status::invalid_argument(format!("duplicate output ID {id}")));
                }
            }
            let outputs = current.get_outputs(&request.ids).map_err(Status::invalid_argument)?;
            if outputs.len() != request.ids.len() {
                return Err(Status::internal(format!(
                    "get_outputs() returned {} values for {} requested IDs",
                    outputs.len(), request.ids.len()
                )));
            }
            let mut by_id = std::collections::HashMap::with_capacity(outputs.len());
            for output in outputs {
                if output.value.is_none() {
                    return Err(Status::internal(format!("get_outputs() returned no value for ID {}", output.id)));
                }
                if by_id.insert(output.id, output).is_some() {
                    return Err(Status::internal("get_outputs() returned duplicate output IDs"));
                }
            }
            let ordered = request.ids.iter().map(|id| {
                by_id.remove(id).ok_or_else(|| Status::internal(format!("get_outputs() omitted requested ID {id}")))
            }).collect::<Result<Vec<_>, _>>()?;
            if !by_id.is_empty() {
                return Err(Status::internal("get_outputs() returned unexpected output IDs"));
            }
            Ok(Some(ControllerResponse { request_id, outputs: ordered }))
        }
    }
}

/// Run a controller implementation at the supplied listen address.
///
/// Each incoming stream receives an independent session. The future completes
/// when the server shuts down or returns a transport error.
pub async fn serve<T: ControllerSession>(
    listen: SocketAddr,
    controller: Controller<T>,
) -> Result<(), tonic::transport::Error> {
    Server::builder()
        .add_service(
            controller_server::ControllerServer::new(ControllerService { controller })
                .max_encoding_message_size(MAX_MESSAGE_SIZE)
                .max_decoding_message_size(MAX_MESSAGE_SIZE),
        )
        .serve(listen)
        .await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Debug)]
    struct TestSession { phenome: Vec<u8>, value: f64 }

    impl TestSession {
        fn create(phenome: &[u8]) -> Result<Self, String> {
            if phenome == b"bad" { return Err("invalid phenome".into()); }
            Ok(Self { phenome: phenome.to_vec(), value: 0.0 })
        }
    }

    impl ControllerSession for TestSession {
        fn reset(&mut self) -> Result<(), String> { self.value = 0.0; Ok(()) }
        fn advance(&mut self, dt: f64) -> Result<(), String> { self.value += dt; Ok(()) }
        fn set_inputs(&mut self, inputs: &[IoValue]) -> Result<(), String> {
            for input in inputs {
                match input.value.as_ref() {
                    Some(io_value::Value::Number(value)) => self.value = *value,
                    Some(io_value::Value::Text(_)) | Some(io_value::Value::Blob(_)) => {},
                    None => return Err("missing value".into()),
                }
            }
            Ok(())
        }
        fn get_outputs(&mut self, ids: &[u64]) -> Result<Vec<IoValue>, String> {
            Ok(ids.iter().map(|id| IoValue { id: *id, value: Some(io_value::Value::Number(self.value)) }).collect())
        }
    }

    fn factory() -> Controller<TestSession> { Controller::new(|phenome| TestSession::create(phenome)) }

    fn request(command: controller_request::Command, request_id: u64) -> ControllerRequest {
        ControllerRequest { request_id, command: Some(command) }
    }

    #[test]
    fn initialize_then_get_outputs_echoes_id_and_order() {
        let mut session = None;
        let f = factory();
        assert!(process_request(&mut session, request(controller_request::Command::Initialize(InitializeRequest { phenome: b"ok".to_vec() }), 0), f.factory.as_ref()).unwrap().is_none());
        let response = process_request(&mut session, request(controller_request::Command::GetOutputs(GetOutputsRequest { ids: vec![2, 0] }), 73), f.factory.as_ref()).unwrap().unwrap();
        assert_eq!(response.request_id, 73);
        assert_eq!(response.outputs.iter().map(|o| o.id).collect::<Vec<_>>(), vec![2, 0]);
    }

    #[test]
    fn lifecycle_and_invalid_dt_are_rejected() {
        let f = factory();
        let mut session = None;
        let err = process_request(&mut session, request(controller_request::Command::Reset(ResetRequest {}), 0), f.factory.as_ref()).unwrap_err();
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
        process_request(&mut session, request(controller_request::Command::Initialize(InitializeRequest { phenome: vec![] }), 0), f.factory.as_ref()).unwrap();
        let err = process_request(&mut session, request(controller_request::Command::Initialize(InitializeRequest { phenome: vec![] }), 0), f.factory.as_ref()).unwrap_err();
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
        for dt in [-1.0, f64::NAN, f64::INFINITY] {
            let err = process_request(&mut session, request(controller_request::Command::Advance(AdvanceRequest { dt }), 0), f.factory.as_ref()).unwrap_err();
            assert_eq!(err.code(), tonic::Code::InvalidArgument);
        }
    }

    #[test]
    fn rejects_duplicate_ids_and_unset_values() {
        let f = factory();
        let mut session = None;
        process_request(&mut session, request(controller_request::Command::Initialize(InitializeRequest { phenome: vec![] }), 0), f.factory.as_ref()).unwrap();
        let err = process_request(&mut session, request(controller_request::Command::SetInputs(SetInputsRequest { inputs: vec![
            IoValue { id: 1, value: Some(io_value::Value::Number(1.0)) },
            IoValue { id: 1, value: Some(io_value::Value::Number(2.0)) },
        ]}), 0), f.factory.as_ref()).unwrap_err();
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
        let err = process_request(&mut session, request(controller_request::Command::SetInputs(SetInputsRequest { inputs: vec![
            IoValue { id: 1, value: None },
        ]}), 0), f.factory.as_ref()).unwrap_err();
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
        let err = process_request(&mut session, request(controller_request::Command::GetOutputs(GetOutputsRequest { ids: vec![1, 1] }), 0), f.factory.as_ref()).unwrap_err();
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
    }

    #[test]
    fn all_io_variants_are_passed_through() {
        let f = factory();
        let mut session = None;
        process_request(&mut session, request(controller_request::Command::Initialize(InitializeRequest { phenome: vec![] }), 0), f.factory.as_ref()).unwrap();
        let inputs = vec![
            IoValue { id: 1, value: Some(io_value::Value::Number(1.0)) },
            IoValue { id: 2, value: Some(io_value::Value::Text("hello".into())) },
            IoValue { id: 3, value: Some(io_value::Value::Blob(vec![1, 2])) },
        ];
        process_request(&mut session, request(controller_request::Command::SetInputs(SetInputsRequest { inputs }), 0), f.factory.as_ref()).unwrap();
    }

    #[test]
    fn constructor_error_is_invalid_argument_and_sessions_are_independent() {
        let f = factory();
        let mut first = None;
        let err = process_request(&mut first, request(controller_request::Command::Initialize(InitializeRequest { phenome: b"bad".to_vec() }), 0), f.factory.as_ref()).unwrap_err();
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
        process_request(&mut first, request(controller_request::Command::Initialize(InitializeRequest { phenome: b"one".to_vec() }), 0), f.factory.as_ref()).unwrap();
        let mut second = None;
        process_request(&mut second, request(controller_request::Command::Initialize(InitializeRequest { phenome: b"two".to_vec() }), 0), f.factory.as_ref()).unwrap();
        process_request(&mut first, request(controller_request::Command::SetInputs(SetInputsRequest { inputs: vec![IoValue { id: 0, value: Some(io_value::Value::Number(9.0)) }] }), 0), f.factory.as_ref()).unwrap();
        let out = process_request(&mut second, request(controller_request::Command::GetOutputs(GetOutputsRequest { ids: vec![0] }), 0), f.factory.as_ref()).unwrap().unwrap();
        assert_eq!(out.outputs[0].value, Some(io_value::Value::Number(0.0)));
    }
}
