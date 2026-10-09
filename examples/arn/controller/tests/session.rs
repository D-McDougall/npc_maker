//! End-to-end tests: a real gRPC client talking to the server over loopback.

use arn::ArnController;
use npc_maker::controller::{
    AdvanceRequest, ControllerRequest, ControllerResponse, GetOutputsRequest, InitializeRequest, IoValue,
    SetInputsRequest, controller_client::ControllerClient, controller_request::Command,
    controller_server::ControllerServer, io_value::Value,
};
use tokio::net::TcpListener;
use tokio::sync::mpsc;
use tokio_stream::wrappers::{ReceiverStream, TcpListenerStream};
use tonic::{Code, Streaming, transport::Server};

const EPSILON: f64 = 1e-12;

/// Two uncoupled genes. Gene 0 is the input, genes 0 & 1 are outputs 0 & 1.
const PHENOME: &str = r#"{"T":1.0,"N":2,"I":[[0]],"O":[[0],[1]],"W":[0,0,0,0]}"#;

/// Start a server on a free port, returns the URL.
async fn serve() -> String {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    tokio::spawn(
        Server::builder()
            .add_service(ControllerServer::new(ArnController))
            .serve_with_incoming(TcpListenerStream::new(listener)),
    );
    format!("http://{address}")
}

/// The environment's end of one session.
struct Client {
    requests: mpsc::Sender<ControllerRequest>,
    responses: Streaming<ControllerResponse>,
    next_id: u64,
}

impl Client {
    async fn connect(url: &str) -> Self {
        let mut client = ControllerClient::connect(url.to_string()).await.unwrap();
        let (requests, receiver) = mpsc::channel(16);
        let responses = client
            .session(ReceiverStream::new(receiver))
            .await
            .unwrap()
            .into_inner();
        Self {
            requests,
            responses,
            next_id: 0,
        }
    }

    /// Send a command, `request_id` auto-increments from zero.
    async fn send(&mut self, command: Command) -> u64 {
        let request_id = self.next_id;
        self.next_id += 1;
        let request = ControllerRequest {
            request_id,
            command: Some(command),
        };
        self.requests.send(request).await.unwrap();
        request_id
    }

    async fn initialize(&mut self, phenome: &str) {
        let phenome = phenome.as_bytes().to_vec();
        self.send(Command::Initialize(InitializeRequest { phenome })).await;
    }

    async fn set_input(&mut self, id: u64, value: f64) {
        let inputs = vec![IoValue {
            id,
            value: Some(Value::Number(value)),
        }];
        self.send(Command::SetInputs(SetInputsRequest { inputs })).await;
    }

    async fn advance(&mut self, dt: f64) {
        self.send(Command::Advance(AdvanceRequest { dt })).await;
    }

    /// Get outputs and wait for the response.
    async fn outputs(&mut self, ids: Vec<u64>) -> (u64, Vec<f64>) {
        let request_id = self.send(Command::GetOutputs(GetOutputsRequest { ids })).await;
        let response = self.responses.message().await.unwrap().expect("stream ended early");
        let numbers = response
            .outputs
            .iter()
            .map(|io| match io.value {
                Some(Value::Number(x)) => x,
                ref other => panic!("expected a number, found {other:?}"),
            })
            .collect();
        assert_eq!(response.request_id, request_id);
        (request_id, numbers)
    }
}

fn assert_close(actual: &[f64], expected: &[f64]) {
    assert_eq!(actual.len(), expected.len());
    for (a, e) in actual.iter().zip(expected) {
        assert!((a - e).abs() < EPSILON, "{actual:?} != {expected:?}");
    }
}

#[tokio::test]
async fn pipelined_commands_are_processed_in_order() {
    let url = serve().await;
    let mut client = Client::connect(&url).await;
    // Send everything without waiting, the commands must still apply in order.
    client.initialize(PHENOME).await;
    client.set_input(0, 1.0).await;
    client.advance(1.0).await;
    // Initialize, set_inputs & advance get no response, so this is request 3.
    let (request_id, outputs) = client.outputs(vec![0, 1]).await;
    assert_eq!(request_id, 3);
    assert_close(&outputs, &[4.0 / 3.0, 2.0 / 3.0]);
    // The request_id keeps counting across commands.
    client.advance(0.0).await;
    let (request_id, _) = client.outputs(vec![]).await;
    assert_eq!(request_id, 5);
}

#[tokio::test]
async fn sessions_are_independent() {
    let url = serve().await;
    let mut a = Client::connect(&url).await;
    let mut b = Client::connect(&url).await;
    a.initialize(PHENOME).await;
    b.initialize(PHENOME).await;
    a.set_input(0, 1.0).await;
    a.advance(1.0).await;
    // Only `a` was driven, `b` is still in its initial state.
    assert_close(&a.outputs(vec![0]).await.1, &[4.0 / 3.0]);
    assert_close(&b.outputs(vec![0]).await.1, &[1.0]);
    // Different phenomes in the same process.
    let mut c = Client::connect(&url).await;
    c.initialize(r#"{"T":1.0,"N":3,"I":[],"O":[[0,1,2]],"W":[0,0,0,0,0,0,0,0,0]}"#)
        .await;
    assert_close(&c.outputs(vec![0]).await.1, &[1.0]);
}

#[tokio::test]
async fn an_error_ends_only_the_failing_session() {
    let url = serve().await;
    let mut good = Client::connect(&url).await;
    let mut bad = Client::connect(&url).await;
    good.initialize(PHENOME).await;
    bad.initialize(PHENOME).await;
    // Output interface 5 does not exist.
    bad.send(Command::GetOutputs(GetOutputsRequest { ids: vec![5] })).await;
    let status = bad.responses.message().await.unwrap_err();
    assert_eq!(status.code(), Code::InvalidArgument);
    // The server is still serving everyone else.
    assert_close(&good.outputs(vec![0]).await.1, &[1.0]);
}

#[tokio::test]
async fn invalid_phenome_ends_the_session() {
    let url = serve().await;
    let mut client = Client::connect(&url).await;
    client.initialize("not a phenome").await;
    let status = client.responses.message().await.unwrap_err();
    assert_eq!(status.code(), Code::InvalidArgument);
}

#[tokio::test]
async fn command_before_initialize_ends_the_session() {
    let url = serve().await;
    let mut client = Client::connect(&url).await;
    client.advance(1.0).await;
    let status = client.responses.message().await.unwrap_err();
    assert_eq!(status.code(), Code::FailedPrecondition);
}

#[tokio::test]
async fn closing_the_request_stream_ends_the_session_cleanly() {
    let url = serve().await;
    let Client {
        requests,
        mut responses,
        ..
    } = Client::connect(&url).await;
    drop(requests);
    assert!(responses.message().await.unwrap().is_none());
}
