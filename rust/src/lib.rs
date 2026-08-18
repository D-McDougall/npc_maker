//! The NPC Maker is a framework for interacting with simulated environments
//! that contain AI agents. It defines software interfaces that separate the
//! components of an artificial-life experiment, and provides APIs for using
//! them.

pub mod ctrl;
pub mod env;
pub mod evo;
pub mod r#gen;
pub mod indiv;

fn read_bytes(reader: &mut impl std::io::BufRead, len: usize) -> std::io::Result<Box<[u8]>> {
    use std::mem::{MaybeUninit, transmute};
    let mut data = unsafe { transmute::<Vec<MaybeUninit<u8>>, Vec<u8>>(vec![MaybeUninit::uninit(); len]) };
    reader.read_exact(&mut data)?;
    Ok(data.into())
}
