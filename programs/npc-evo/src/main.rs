use npc_maker::evolution::{
    DeathRequest, DeathResponse, Individual, SpawnRequest, SpawnResponse, evolution_server::EvolutionServer,
};
use std::path::PathBuf;
use std::sync::Mutex;
use tonic::{Request, Response, Status, transport::Server};

type TonicResult<T> = Result<Response<T>, Status>;

struct EvolutionServerImpl(Mutex<npc_evo::Evolution>);

macro_rules! exit_error {
    ($code:expr, $msg:expr $(, $($args:tt)*)?) => {
        {
            eprintln!($msg $(, $($args)*)?);
            std::process::exit($code);
        }
    };
}

#[tonic::async_trait]
impl npc_maker::evolution::evolution_server::Evolution for EvolutionServerImpl {
    async fn spawn(&self, _request: Request<SpawnRequest>) -> TonicResult<SpawnResponse> {
        let parents = self.0.lock().unwrap().spawn();
        // Load parents into individual objects
        let parents: Vec<Individual> = todo!();
        Ok(Response::new(SpawnResponse { parents }))
    }
    async fn death(&self, request: Request<DeathRequest>) -> TonicResult<DeathResponse> {
        let individual = todo!();
        self.0.lock().unwrap().death(individual);
        Ok(Response::new(DeathResponse{}))
    }
}

#[derive(Debug, Default)]
struct ServerOptions {
    host: Option<String>,
    port: Option<u16>,
    listen: Option<String>,
    tls_cert: Option<PathBuf>,
    tls_key: Option<PathBuf>,
}
impl ServerOptions {
    fn parse(args: &mut Vec<String>) -> Self {
        let mut this = Self::default();
        let mut index = 1; // Start at 1, arg 0 is the program name
        // Skip optional file path argument
        if let Some(arg1) = args.get(index) {
            if !arg1.starts_with("-") {
                index += 1;
            }
        }
        while let Some(flag) = args.get(index) {
            match flag.as_str() {
                "--host" => {
                    if this.host.is_some() {
                        exit_error!(2, "Error: duplicate flag {}", flag);
                    }
                    let Some(value) = args.get(index + 1) else {
                        exit_error!(3, "Error: expected host address");
                    };
                    this.host = Some(value.into());
                }
                "--port" => {
                    if this.port.is_some() {
                        exit_error!(2, "Error: duplicate flag {}", flag);
                    }
                    let Some(value) = args.get(index + 1) else {
                        exit_error!(3, "Error: expected port number");
                    };
                    let Ok(number) = value.parse() else {
                        exit_error!(3, "Error: expected port number [0-65535], found {}", value);
                    };
                    this.port = Some(number);
                }
                "--listen" => {
                    if this.listen.is_some() {
                        exit_error!(2, "Error: duplicate flag {}", flag);
                    }
                    let Some(value) = args.get(index + 1) else {
                        exit_error!(3, "Error: expected host:port");
                    };
                    this.listen = Some(value.into());
                }
                "--tls-cert" => {
                    if this.tls_cert.is_some() {
                        exit_error!(2, "Error: duplicate flag {}", flag);
                    }
                    let Some(value) = args.get(index + 1) else {
                        exit_error!(3, "Error: expected path to TLS certification file");
                    };
                    this.tls_cert = Some(value.into());
                }
                "--tls-key" => {
                    if this.tls_key.is_some() {
                        exit_error!(2, "Error: duplicate flag {}", flag);
                    }
                    let Some(value) = args.get(index + 1) else {
                        exit_error!(3, "Error: expected path to TLS private key file");
                    };
                    this.tls_key = Some(value.into());
                }
                _ => {
                    index += 1;
                    continue;
                }
            }
            args.remove(index); // Remove the flag
            args.remove(index); // Remove the value
        }
        // Check for mutually exclusive arguments
        if (this.host.is_some() || this.port.is_some()) && this.listen.is_some() {
            exit_error!(4, "Error: options --host & --port are incompatible with --listen");
        }
        // Prepare the listen option
        if this.listen.is_none() {
            let host = this.host.as_ref().map(String::as_str).unwrap_or("127.0.0.1");
            let port = this.port.unwrap_or(47001);
            this.listen = Some(format!("{}:{}", host,port));
        }
        this
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args: Vec<String> = std::env::args().collect();
    let options = ServerOptions::parse(&mut args);

    let addr = options.listen.unwrap().parse()?;
    let program = npc_evo::Evolution::new(args).unwrap_or_else(|msg| exit_error!(5, "{}", msg));
    let wrapper = EvolutionServerImpl(Mutex::new(program));

    Server::builder()
        .add_service(EvolutionServer::new(wrapper))
        .serve(addr)
        .await?;

    Ok(())
}
