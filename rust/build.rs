use std::{env, path::PathBuf};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("cargo:rerun-if-changed=build.rs");

    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR")?);
    let proto_dir = manifest_dir.join("../proto");

    println!("cargo:rerun-if-changed={}", proto_dir.display());

    let descriptor_path = PathBuf::from(env::var("OUT_DIR")?).join("proto_descriptor.bin");

    tonic_prost_build::configure()
        .file_descriptor_set_path(&descriptor_path)
        .compile_well_known_types(true)
        .extern_path(".google.protobuf", "::pbjson_types")
        .compile_protos(
            &[
                "environment.proto",
                "evolution.proto",
                "genetics.proto",
                "individual.proto",
            ],
            &[proto_dir.to_str().unwrap()],
        )?;

    let descriptors = std::fs::read(&descriptor_path)?;

    pbjson_build::Builder::new()
        .register_descriptors(&descriptors)?
        .build(&[".individual", ".environment", ".evolution", ".genetics"])?;

    Ok(())
}
