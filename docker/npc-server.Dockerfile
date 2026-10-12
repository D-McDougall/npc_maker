# Build the workspace binary with the Rust version required by Cargo.toml.
FROM rust:1.91-bookworm AS builder
WORKDIR /src

# Copy the repo into the build root
COPY . .
RUN cargo build --locked --release --package npc-server

# Keep the runtime image small and run the server without root privileges.
FROM debian:bookworm-slim AS runtime
RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --no-create-home --home-dir /nonexistent npc \
    && mkdir /data \
    && chown 10001:10001 /data

COPY --from=builder /src/target/release/npc-server /usr/local/bin/npc-server

WORKDIR /app
USER 10001:10001

# Mount the experiment file at /config/experiment.json and persistent data at
# /data. Override the command arguments when using different container paths.
VOLUME ["/data"]
EXPOSE 50051

# Forward container stop signal as a keyboard interrupt so the service can shut down cleanly.
STOPSIGNAL SIGINT

ENTRYPOINT ["npc-server"]
CMD ["--listen", "0.0.0.0:50051", "/config/experiment.json", "/data"]
