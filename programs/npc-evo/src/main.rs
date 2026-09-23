use npc_maker::evo::API;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let mut program = npc_evo::Evolution::new(args).unwrap();
    program.main().unwrap();
}
