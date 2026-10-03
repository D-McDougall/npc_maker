use std::{env, path::PathBuf};

fn main() {
    if let Err(error) = main_inner() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

fn main_inner() -> Result<(), Box<dyn std::error::Error>> {
    println!("cargo:rerun-if-changed=build.rs");

    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR")?);
    let proto_dir = manifest_dir.join("../proto");

    println!("cargo:rerun-if-changed={}", proto_dir.display());

    let descriptor_path = PathBuf::from(env::var("OUT_DIR")?).join("proto_descriptor.bin");

    // Use the vendored protoc so no system install is required.
    let mut config = tonic_prost_build::Config::new();
    config.protoc_executable(protoc_bin_vendored::protoc_bin_path()?);
    let well_known_types = protoc_bin_vendored::include_path()?;

    tonic_prost_build::configure()
        .file_descriptor_set_path(&descriptor_path)
        .compile_well_known_types(true)
        .extern_path(".google.protobuf", "::pbjson_types")
        .compile_with_config(
            config,
            &[
                "environment.proto",
                "evolution.proto",
                "genetics.proto",
                "individual.proto",
            ],
            &[proto_dir.to_str().unwrap(), well_known_types.to_str().unwrap()],
        )?;

    let descriptors = std::fs::read(&descriptor_path)?;

    pbjson_build::Builder::new()
        .register_descriptors(&descriptors)?
        .build(&[".individual", ".environment", ".evolution", ".genetics"])?;

    Ok(())
}
