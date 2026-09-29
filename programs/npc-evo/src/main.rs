use tokio_stream::{Stream, StreamExt, wrappers::ReceiverStream};
use tonic::{Request, Response, Status, transport::Server};
use std::pin::Pin;

use npc_maker::evo::{evolution_server::EvolutionServer, SpawnRequest, DeathResponse, Individual};

struct MyImpl {}
impl npc_maker::evo::evolution_server::Evolution for MyImpl {

    type SpawnStream = Pin<Box<dyn Stream<Item = Result<Individual, Status>> + Send>>;

    fn spawn<'life0, 'async_trait>(
        &'life0 self,
        request: Request<SpawnRequest>,
    ) -> Pin<Box<dyn Future<Output = Result<Response<Self::SpawnStream>, Status>> + Send + 'async_trait>>
    where
        Self: 'async_trait,
        'life0: 'async_trait,
    {
        todo!()
    }

    fn death<'life0, 'async_trait>(
        &'life0 self,
        request: Request<Individual>,
    ) -> Pin<Box<dyn Future<Output = Result<Response<DeathResponse>, Status>> + Send + 'async_trait>>
    where
        Self: 'async_trait,
        'life0: 'async_trait,
    {
        todo!()
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    // npc_evo::Evolution::new(args).unwrap();
    println!("Starting npc-evo on port ");
    let addr = "[::1]:50051".parse()?;
    let mut program = MyImpl {};

    Server::builder()
        .add_service(EvolutionServer::new(program))
        .serve(addr)
        .await?;

    Ok(())
}
