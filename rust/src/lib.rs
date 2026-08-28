//! The NPC Maker is a toolkit for building and interacting with simulated
//! environments populated by AI agents. It facilitates rapid development by
//! providing software interfaces that separate the components of an
//! artificial-life experiment. The NPC Maker also includes a collection of
//! ready-to-use tools and environments.

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
