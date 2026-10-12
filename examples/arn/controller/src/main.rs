use arn_controller::{Cli, DEFAULT_TEMPERATURE, Session, parse_args};
use npc_maker::controller::{Controller, ControllerRequest, InitializeRequest, controller_request::Command, serve};
use std::net::SocketAddr;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    let options = match parse_args(&args) {
        Ok(Cli::Serve(options)) => options,
        Ok(Cli::Print(text)) => {
            println!("{text}");
            return Ok(());
        }
        Err(message) => {
            eprintln!("Error: {message}");
            std::process::exit(2);
        }
    };
    let addr: SocketAddr = options.listen.parse().unwrap_or_else(|error| {
        eprintln!(
            "Error: expected an address like 127.0.0.1:47001, found {}: {error}",
            options.listen
        );
        std::process::exit(3);
    });
    let temperature = options.temperature.unwrap_or(DEFAULT_TEMPERATURE);
    let controller = Controller::new(move |phenome: &[u8]| {
        let mut session = Session::new(temperature);
        session.handle(ControllerRequest {
            request_id: 0,
            command: Some(Command::Initialize(InitializeRequest { phenome: phenome.to_vec() })),
        }).map_err(|status| status.message().to_string())?;
        Ok(session)
    });
    serve(addr, controller).await?;
    Ok(())
}
