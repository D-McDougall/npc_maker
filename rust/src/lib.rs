#![allow(clippy::doc_lazy_continuation)]

//! The NPC Maker is a toolkit for building and interacting with simulated
//! environments populated by AI agents. It facilitates rapid development by
//! providing software interfaces that separate the components of an
//! artificial-life experiment. The NPC Maker also includes a collection of
//! ready-to-use tools and environments.

pub mod individual;

pub mod evolution {
    tonic::include_proto!("evolution");
}

pub mod genetics {
    tonic::include_proto!("genetics");
}

pub mod controller {
    tonic::include_proto!("controller");
}
