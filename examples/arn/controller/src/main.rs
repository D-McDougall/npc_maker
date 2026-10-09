use arn::{ArnController, Cli, DEFAULT_TEMPERATURE, parse_args};
use npc_maker::controller::controller_server::ControllerServer;
use std::net::SocketAddr;
use tonic::transport::Server;

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
    let controller = ArnController::new(options.temperature.unwrap_or(DEFAULT_TEMPERATURE));
    Server::builder()
        .add_service(ControllerServer::new(controller))
        .serve(addr)
        .await?;
    Ok(())
}
