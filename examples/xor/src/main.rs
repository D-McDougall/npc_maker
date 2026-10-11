use npc_maker::controller::{
    controller_client::ControllerClient, controller_request::Command, io_value::Value, AdvanceRequest,
    ControllerRequest, GetOutputsRequest, InitializeRequest, IoValue, ResetRequest, SetInputsRequest,
};
use npc_maker::environment::{environment_client::EnvironmentClient, DeathRequest, ScoreRequest, SpawnRequest};
use std::error::Error;
use std::process::{Child, Command as ProcessCommand, Stdio};
use tokio::sync::mpsc;
use tokio_stream::wrappers::ReceiverStream;

const TSTOP: f64 = 100.0;
const DT: f64 = 0.1;

struct ControllerProcess(Child);

impl Drop for ControllerProcess {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

struct ControllerSession {
    requests: mpsc::Sender<ControllerRequest>,
    responses: mpsc::Receiver<Result<npc_maker::controller::ControllerResponse, String>>,
    request_id: u64,
}

impl ControllerSession {
    async fn connect(address: &str, phenome: Vec<u8>) -> Result<Self, Box<dyn Error>> {
        let endpoint = format!("http://{address}");
        let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(30);
        let mut client = loop {
            match ControllerClient::connect(endpoint.clone()).await {
                Ok(client) => break client,
                Err(_) if tokio::time::Instant::now() < deadline => {
                    tokio::time::sleep(std::time::Duration::from_millis(100)).await;
                }
                Err(error) => return Err(error.into()),
            }
        };
        let (requests, receiver) = mpsc::channel(16);
        let (response_sender, responses) = mpsc::channel(16);
        tokio::spawn(async move {
            let mut stream = match client.session(ReceiverStream::new(receiver)).await {
                Ok(response) => response.into_inner(),
                Err(error) => {
                    let _ = response_sender.send(Err(error.to_string())).await;
                    return;
                }
            };
            loop {
                match stream.message().await {
                    Ok(Some(response)) => {
                        if response_sender.send(Ok(response)).await.is_err() {
                            return;
                        }
                    }
                    Ok(None) => return,
                    Err(error) => {
                        let _ = response_sender.send(Err(error.to_string())).await;
                        return;
                    }
                }
            }
        });
        let mut session = Self {
            requests,
            responses,
            request_id: 0,
        };
        session.send(Command::Initialize(InitializeRequest { phenome })).await?;
        Ok(session)
    }

    async fn send(&mut self, command: Command) -> Result<u64, Box<dyn Error>> {
        let id = self.request_id;
        self.request_id += 1;
        self.requests
            .send(ControllerRequest {
                request_id: id,
                command: Some(command),
            })
            .await?;
        Ok(id)
    }

    async fn reset(&mut self) -> Result<(), Box<dyn Error>> {
        self.send(Command::Reset(ResetRequest {})).await?;
        Ok(())
    }

    async fn set_inputs(&mut self, first: f64, second: f64) -> Result<(), Box<dyn Error>> {
        self.send(Command::SetInputs(SetInputsRequest {
            inputs: vec![
                IoValue {
                    id: 0,
                    value: Some(Value::Number(first)),
                },
                IoValue {
                    id: 1,
                    value: Some(Value::Number(second)),
                },
            ],
        }))
        .await?;
        Ok(())
    }

    async fn advance(&mut self, dt: f64) -> Result<(), Box<dyn Error>> {
        self.send(Command::Advance(AdvanceRequest { dt })).await?;
        Ok(())
    }

    async fn get_output(&mut self) -> Result<f64, Box<dyn Error>> {
        let id = self
            .send(Command::GetOutputs(GetOutputsRequest { ids: vec![0] }))
            .await?;
        let response = self.responses.recv().await.ok_or("controller session ended before returning outputs")?
            .map_err(std::io::Error::other)?;
        if response.request_id != id {
            return Err("controller returned an out-of-order response".into());
        }
        let output = response
            .outputs
            .into_iter()
            .find(|output| output.id == 0)
            .ok_or("controller did not return output 0")?;
        match output.value {
            Some(Value::Number(value)) => Ok(value),
            _ => Err("XOR controller output must be numeric".into()),
        }
    }
}

async fn evaluate(controller: &mut ControllerSession, verbose: bool) -> Result<f64, Box<dyn Error>> {
    let mut distance = 0.0;
    for input_1 in [0.0, 1.0] {
        for input_2 in [0.0, 1.0] {
            controller.reset().await?;
            let mut previous = None;
            let mut answer = 0.0;
            for _ in 0..(TSTOP / DT).round() as usize {
                controller.set_inputs(input_1, input_2).await?;
                controller.advance(DT).await?;
                answer = controller.get_output().await?;
                if previous == Some(answer) {
                    break;
                }
                previous = Some(answer);
            }
            let correct = if input_1 != input_2 { 1.0 } else { 0.0 };
            answer = answer.clamp(0.0, 1.0);
            distance += (answer - correct).abs();
            if verbose {
                println!("{input_1:.0} xor {input_2:.0} = {answer}");
            }
        }
    }
    let score = (4.0 - distance).powi(2);
    if verbose {
        println!("score {score}");
    }
    Ok(score)
}

fn arguments() -> Result<(String, bool), Box<dyn Error>> {
    let mut listen = None;
    let mut verbose = false;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--listen" => listen = args.next(),
            "--verbose" => verbose = true,
            "-h" | "--help" => {
                println!("Usage: xor --listen HOST:PORT [--verbose]");
                std::process::exit(0);
            }
            _ => return Err(format!("unknown argument: {arg}").into()),
        }
    }
    Ok((listen.ok_or("--listen is required")?, verbose))
}

fn start_controller(command: &[String]) -> Result<(Child, String), Box<dyn Error>> {
    let listener = std::net::TcpListener::bind("127.0.0.1:0")?;
    let address = listener.local_addr()?;
    drop(listener);
    let address = address.to_string();
    let executable = command.first().ok_or("controller command is empty")?;
    let process = ProcessCommand::new(executable)
        .args(&command[1..])
        .arg("--listen")
        .arg(&address)
        .stdin(Stdio::null())
        .spawn()?;
    Ok((process, address))
}

async fn run() -> Result<(), Box<dyn Error>> {
    let (listen, verbose) = arguments()?;
    let mut environment = EnvironmentClient::connect(format!("http://{listen}")).await?;
    let mut active_command: Option<Vec<String>> = None;
    let mut process: Option<ControllerProcess> = None;
    let mut controller_address = String::new();

    loop {
        let individual = match environment
            .spawn(SpawnRequest {
                body_type: "xor".into(),
            })
            .await
        {
            Ok(response) => response.into_inner(),
            Err(status) if status.code() == tonic::Code::Unavailable => break,
            Err(status) => return Err(status.into()),
        };
        let metadata = individual.metadata.as_ref().ok_or("individual has no metadata")?;
        let command = metadata.controller.clone();
        if active_command.as_ref() != Some(&command) {
            drop(process.take());
            let (new_process, address) = start_controller(&command)?;
            process = Some(ControllerProcess(new_process));
            controller_address = address;
            active_command = Some(command);
        }

        let mut controller =
            ControllerSession::connect(&controller_address, individual.phenome.clone().unwrap_or_default()).await?;
        let score = evaluate(&mut controller, verbose).await?;
        drop(controller);
        environment
            .score(ScoreRequest {
                name: metadata.name.clone(),
                score,
            })
            .await?;
        environment
            .death(DeathRequest {
                name: metadata.name.clone(),
            })
            .await?;
    }

    drop(process);
    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    run().await
}
