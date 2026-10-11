//! A simple API for implementing genetics gRPC services.
//!
//! Implement Genetics::reproduce to create founders and offspring. The
//! adapter handles protobuf conversion, gRPC errors, and server setup.

use std::net::SocketAddr;

use tonic::{Request, Response, Status, transport::Server};

use crate::MAX_MESSAGE_SIZE;
use crate::individual::Individual;

tonic::include_proto!("genetics");

/// Implement the algorithm-specific part of a genetics service.
///
/// An empty parent list requests a founder. The implementation is responsible
/// for constructing the returned individual, including its name and any
/// algorithm-specific genetic data. Empty genome, epigenome, and phenome fields
/// are allowed.
pub trait Genetics: Send + Sync + 'static {
    /// Create a founder or offspring from the supplied parents.
    ///
    /// Return an error message when the request is invalid for this algorithm.
    fn reproduce(&self, parents: Vec<Individual>) -> Result<Individual, String>;
}

/// Adapts the hand-written genetics API to the generated gRPC service.
struct GeneticsService<T> {
    genetics: T,
}

#[tonic::async_trait]
impl<T: Genetics> genetics_server::Genetics for GeneticsService<T> {
    async fn reproduce(&self, request: Request<ReproduceRequest>) -> Result<Response<ReproduceResponse>, Status> {
        let parents = request.into_inner().parents;
        let child = self.genetics.reproduce(parents).map_err(Status::invalid_argument)?;

        if child.metadata.as_ref().is_none_or(|metadata| metadata.name.is_empty()) {
            return Err(Status::internal(
                "reproduce() must return an Individual with a non-empty name",
            ));
        }

        Ok(Response::new(ReproduceResponse { child: Some(child) }))
    }
}

/// Run a genetics implementation as a gRPC server at the supplied address.
///
/// The future completes when the server shuts down or returns a transport
/// error. Message limits match the ARN example's existing configuration.
pub async fn serve<T: Genetics>(listen: SocketAddr, genetics: T) -> Result<(), tonic::transport::Error> {
    Server::builder()
        .add_service(
            genetics_server::GeneticsServer::new(GeneticsService { genetics })
                .max_encoding_message_size(MAX_MESSAGE_SIZE)
                .max_decoding_message_size(MAX_MESSAGE_SIZE),
        )
        .serve(listen)
        .await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::future::Future;
    use std::task::{Context, Poll, Waker};

    struct TestGenetics {
        result: Result<Individual, String>,
    }

    impl Genetics for TestGenetics {
        fn reproduce(&self, _parents: Vec<Individual>) -> Result<Individual, String> {
            self.result.clone()
        }
    }

    // The adapter's handler has no suspension points, so polling it once is
    // enough for these focused unit tests without adding a runtime dependency.
    fn run_ready<F: Future>(future: F) -> F::Output {
        let waker = Waker::noop();
        let mut context = Context::from_waker(waker);
        let mut future = Box::pin(future);
        match future.as_mut().poll(&mut context) {
            Poll::Ready(output) => output,
            Poll::Pending => panic!("test handler unexpectedly returned Pending"),
        }
    }

    #[test]
    fn reproduce_returns_child() {
        let service = GeneticsService {
            genetics: TestGenetics {
                result: Ok(Individual::new()),
            },
        };

        let response = run_ready(genetics_server::Genetics::reproduce(
            &service,
            Request::new(ReproduceRequest { parents: vec![] }),
        ))
        .unwrap()
        .into_inner();

        let child = response.child.expect("successful response should include a child");
        assert!(!child.metadata().name.is_empty());
    }

    #[test]
    fn reproduce_maps_algorithm_error_to_invalid_argument() {
        let service = GeneticsService {
            genetics: TestGenetics {
                result: Err("invalid parent genome".to_string()),
            },
        };

        let error = run_ready(genetics_server::Genetics::reproduce(
            &service,
            Request::new(ReproduceRequest { parents: vec![] }),
        ))
        .unwrap_err();

        assert_eq!(error.code(), tonic::Code::InvalidArgument);
        assert_eq!(error.message(), "invalid parent genome");
    }

    #[test]
    fn reproduce_rejects_child_without_name() {
        let service = GeneticsService {
            genetics: TestGenetics {
                result: Ok(Individual::default()),
            },
        };

        let error = run_ready(genetics_server::Genetics::reproduce(
            &service,
            Request::new(ReproduceRequest { parents: vec![] }),
        ))
        .unwrap_err();

        assert_eq!(error.code(), tonic::Code::Internal);
        assert_eq!(
            error.message(),
            "reproduce() must return an Individual with a non-empty name",
        );
    }
}
