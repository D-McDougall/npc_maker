use npc_maker::evo::Evolution;
use npc_maker::indiv::Individual;
use process_anywhere::{Computer, Forwarder};
use std::path::PathBuf;

#[test]
fn test_protocol() {
    let comp = Computer::new_local();
    let prog = std::env::var("CARGO_BIN_EXE_evo").unwrap();
    let mut evo = Evolution::new(comp, &[prog]).unwrap();
    let empty: Vec<PathBuf> = vec![];
    assert_eq!(dbg!(evo.spawn()).unwrap(), empty);
    assert_eq!(dbg!(evo.spawn()).unwrap(), empty);

    let mut indiv = Individual::new("", "", &[""], Box::new(*b" "));
    indiv.score = Some("1".to_string());
    indiv.save("").unwrap();
    evo.death(indiv.path.unwrap()).unwrap();
    evo.custom("rollover", &[]).unwrap();
    assert!(!dbg!(evo.spawn()).unwrap().is_empty());
}
