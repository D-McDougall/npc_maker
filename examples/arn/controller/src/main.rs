use arn::{ArnController, Cli, parse_args};
use npc_maker::controller::controller_server::ControllerServer;
use std::net::SocketAddr;
use tonic::transport::Server;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    let listen = match parse_args(&args) {
        Ok(Cli::Serve(listen)) => listen,
        Ok(Cli::Print(text)) => {
            println!("{text}");
            return Ok(());
        }
        Err(message) => {
            eprintln!("Error: {message}");
            std::process::exit(2);
        }
    };
    let addr: SocketAddr = listen.parse().unwrap_or_else(|error| {
        eprintln!("Error: expected an address like 127.0.0.1:47001, found {listen}: {error}");
        std::process::exit(3);
    });
    Server::builder()
        .add_service(ControllerServer::new(ArnController))
        .serve(addr)
        .await?;
    Ok(())
}
