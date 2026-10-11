#![allow(clippy::doc_lazy_continuation)]
#![allow(clippy::useless_borrows_in_formatting)]

//! The NPC Maker is a toolkit for building and interacting with simulated
//! environments populated by AI agents. It facilitates rapid development by
//! providing software interfaces that separate the components of an
//! artificial-life experiment. The NPC Maker also includes a collection of
//! ready-to-use tools and environments.

pub mod individual;
pub mod genetics;

pub mod evolution {
    tonic::include_proto!("evolution");
}

pub mod controller {
    tonic::include_proto!("controller");
}

pub mod environment {
    tonic::include_proto!("environment");
}

const MAX_MESSAGE_SIZE: usize = 8 *1024*1024;
