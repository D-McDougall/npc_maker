use std::{env, path::PathBuf};

fn main() {
    println!("cargo:rerun-if-changed=build.rs");

    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let proto_dir = manifest_dir.join("../proto").into_os_string();
    let proto_dir = proto_dir.to_str().unwrap();

    println!("cargo:rerun-if-changed={}", proto_dir);

    tonic_prost_build::configure()
        // .out_dir(manifest_dir.join("src/generated"))
        .compile_protos(
            &[
                "environment.proto",
                "evolution.proto",
                "genetics.proto",
                "individual.proto",
            ],
            &[proto_dir],
        )
        .unwrap();
}
