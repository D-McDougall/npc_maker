use npc_maker::{
    MAX_MESSAGE_SIZE,
    diagnostics::{
        self,
        diagnostics_server::{Diagnostics, DiagnosticsServer},
    },
    environment::{
        self,
        environment_server::{Environment, EnvironmentServer},
    },
    evolution::{self, evolution_client::EvolutionClient},
    experiment::Experiment,
    genetics::{self, genetics_client::GeneticsClient},
    individual::{Individual, Metadata},
};
use std::{
    collections::HashMap,
    env, fs,
    net::{SocketAddr, TcpListener},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Arc,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tokio::sync::{Mutex, watch};
use tonic::{
    Request, Response, Status,
    transport::{Channel, Server},
};

type RpcResult<T> = Result<Response<T>, Status>;

/// Time given to a child process to complete its shutdown work.
const CHILD_SHUTDOWN_GRACE_PERIOD: Duration = Duration::from_secs(2);

#[cfg(windows)]
const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
#[cfg(windows)]
const CTRL_BREAK_EVENT: u32 = 1;
#[cfg(windows)]
#[link(name = "kernel32")]
unsafe extern "system" {
    fn GenerateConsoleCtrlEvent(control_type: u32, process_group_id: u32) -> i32;
}

/// Owns a child process so every startup path eventually reaps it.
struct ChildProcess(Child);
impl ChildProcess {
    /// Launch a command, optionally creating and entering its working directory.
    fn start(command: &[String], cwd: Option<&Path>) -> Result<Self, String> {
        let (program, args) = command.split_first().ok_or("empty command")?;
        if let Some(path) = cwd {
            fs::create_dir_all(path).map_err(|e| e.to_string())?;
        }
        let mut cmd = Command::new(program);
        cmd.args(args).stdin(Stdio::null());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;

            // CTRL_BREAK_EVENT can target this group without signalling the
            // server or its other children.
            cmd.creation_flags(CREATE_NEW_PROCESS_GROUP);
        }
        if let Some(path) = cwd {
            cmd.current_dir(path);
        }
        let child = cmd.spawn().map_err(|e| format!("starting {program}: {e}"))?;
        Ok(Self(child))
    }
    /// Request that the process stop, then kill it only if it ignores the request.
    fn close(&mut self) {
        if self.0.try_wait().ok().flatten().is_none() {
            // Match Python's Popen.terminate(): SIGTERM lets services flush
            // state and release resources after npc-server receives Ctrl+C.
            #[cfg(unix)]
            unsafe {
                libc::kill(self.0.id() as libc::pid_t, libc::SIGTERM);
            }
            // Console children receive a CTRL_BREAK_EVENT, the Windows
            // analogue that can be addressed to one process group. It may
            // fail for a child without a shared console; the hard-kill
            // fallback below still ensures cleanup.
            #[cfg(windows)]
            unsafe {
                GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, self.0.id());
            }

            let deadline = Instant::now() + CHILD_SHUTDOWN_GRACE_PERIOD;
            loop {
                match self.0.try_wait() {
                    Ok(Some(_)) => return,
                    Err(_) => break,
                    Ok(None) if Instant::now() >= deadline => break,
                    Ok(None) => std::thread::sleep(Duration::from_millis(10)),
                }
            }

            // The platform-specific graceful request either was ignored or
            // could not be delivered, so force the child to exit now.
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}
impl Drop for ChildProcess {
    /// Keep cleanup reliable when initialization exits early with an error.
    fn drop(&mut self) {
        self.close();
    }
}

#[cfg(all(test, unix))]
mod child_process_tests {
    use super::ChildProcess;
    use std::{
        env, fs, thread,
        time::{Duration, SystemTime, UNIX_EPOCH},
    };

    #[test]
    fn close_allows_a_child_to_handle_sigterm() {
        let result = env::temp_dir().join(format!(
            "npc-server-shutdown-{}",
            SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()
        ));
        let command = vec![
            "sh".into(),
            "-c".into(),
            format!(
                "trap 'echo graceful > {} ; exit' TERM; while :; do :; done",
                result.display()
            ),
        ];
        let mut child = ChildProcess::start(&command, None).unwrap();
        thread::sleep(Duration::from_millis(10));

        child.close();

        assert_eq!(fs::read_to_string(&result).unwrap().trim(), "graceful");
        fs::remove_file(result).unwrap();
    }
}

/// Runtime configuration for one organism body type and its optional services.
struct Organism {
    body_type: String,
    controller: Vec<String>,
    evolution: Option<EvolutionClient<Channel>>,
    genetics: Option<GeneticsClient<Channel>>,
}
/// Apply the same message-size limits to both upstream gRPC clients.
trait ConfigureClient {
    fn configure(self) -> Self;
}
impl ConfigureClient for EvolutionClient<Channel> {
    fn configure(self) -> Self {
        self.max_encoding_message_size(MAX_MESSAGE_SIZE)
            .max_decoding_message_size(MAX_MESSAGE_SIZE)
    }
}
impl ConfigureClient for GeneticsClient<Channel> {
    fn configure(self) -> Self {
        self.max_encoding_message_size(MAX_MESSAGE_SIZE)
            .max_decoding_message_size(MAX_MESSAGE_SIZE)
    }
}
/// Server state shared by the Environment and Diagnostics RPC handlers.
struct State {
    config: Experiment,
    save_dir: PathBuf,
    organisms: HashMap<String, Organism>,
    living: HashMap<String, Metadata>,
    counts: HashMap<(String, String), u64>,
    max_scores: HashMap<String, f64>,
    children: Vec<ChildProcess>,
    environments: Vec<ChildProcess>,
    listen: String,
    failed: bool,
}
/// Clonable handler state. The watch sender asks the gRPC server to shut down
/// when an upstream Evolution or Genetics call fails.
#[derive(Clone)]
struct Shared {
    state: Arc<Mutex<State>>,
    shutdown: watch::Sender<bool>,
}
impl Shared {
    /// Mark an upstream failure as fatal and return an RPC error to the caller.
    fn fail_downstream(&self, error: tonic::Status) -> Status {
        eprintln!("npc-server: downstream service failure: {error}");
        let _ = self.shutdown.send(true);
        Status::unavailable(error.to_string())
    }
}

impl State {
    /// Prepare persistence and start the Evolution/Genetics subprocesses.
    /// Organism-specific commands override the experiment-wide defaults.
    async fn new(config: Experiment, save_dir: PathBuf) -> Result<Self, String> {
        fs::create_dir_all(&save_dir).map_err(|e| e.to_string())?;
        let mut organisms = HashMap::new();
        let mut children = Vec::new();
        for spec in &config.organisms {
            let body_type = spec.body_type.clone();
            let evo_cmd = if spec.evolution.is_empty() {
                &config.evolution
            } else {
                &spec.evolution
            };
            let gen_cmd = if spec.genetics.is_empty() {
                &config.genetics
            } else {
                &spec.genetics
            };
            let evolution = if evo_cmd.is_empty() {
                None
            } else {
                let (client, child) = start_service(
                    evo_cmd,
                    &format!("{body_type}-evolution"),
                    &save_dir,
                    EvolutionClient::new,
                )
                .await?;
                children.push(child);
                Some(client)
            };
            let genetics = if gen_cmd.is_empty() {
                None
            } else {
                let (client, child) = start_service(
                    gen_cmd,
                    &format!("{body_type}-genetics"),
                    &save_dir,
                    GeneticsClient::new,
                )
                .await?;
                children.push(child);
                Some(client)
            };
            organisms.insert(
                body_type.clone(),
                Organism {
                    body_type,
                    controller: if spec.controller.is_empty() {
                        config.controller.clone()
                    } else {
                        spec.controller.clone()
                    },
                    evolution,
                    genetics,
                },
            );
        }
        Ok(Self {
            config,
            save_dir,
            organisms,
            living: HashMap::new(),
            counts: HashMap::new(),
            max_scores: HashMap::new(),
            children,
            environments: Vec::new(),
            listen: String::new(),
            failed: false,
        })
    }
    /// Resolve an omitted body type when there is only one configured organism,
    /// otherwise validate that the requested type exists.
    fn body_type(&self, value: &str) -> Result<String, Status> {
        if value.is_empty() && self.organisms.len() == 1 {
            return Ok(self.organisms.values().next().unwrap().body_type.clone());
        }
        if self.organisms.contains_key(value) {
            return Ok(value.to_owned());
        }
        Err(Status::invalid_argument(if value.is_empty() {
            "missing body type".to_string()
        } else {
            format!("unknown body type \"{value}\"")
        }))
    }
    /// Return a copy of tracked metadata or reject an unknown/deceased name.
    fn living(&self, name: &str) -> Result<Metadata, Status> {
        self.living
            .get(name)
            .cloned()
            .ok_or_else(|| Status::invalid_argument(format!("unknown living individual \"{name}\"")))
    }
    /// Increment the diagnostic counter for one RPC and body type.
    fn count(&mut self, call: &str, body_type: &str) {
        *self.counts.entry((body_type.into(), call.into())).or_default() += 1;
    }
    /// Fill in body type and controller defaults on a newly created individual.
    fn set_defaults(&self, individual: &mut Individual) -> Result<(), Status> {
        let metadata = individual.metadata.get_or_insert_with(Metadata::default);
        let body_type = self.body_type(metadata.body_type.as_deref().unwrap_or(""))?;
        metadata.body_type = Some(body_type.clone());
        if metadata.controller.is_empty() {
            metadata.controller.clone_from(&self.organisms[&body_type].controller);
        }
        Ok(())
    }
    /// Persist the full individual record in its own directory.
    fn save(&self, individual: &Individual) -> Result<(), Status> {
        individual
            .save(&self.save_dir)
            .map_err(|e| Status::internal(format!("saving individual: {e}")))
    }
    /// Rewrite just the metadata file after score or telemetry changes.
    fn save_metadata(&self, metadata: &Metadata) -> Result<(), Status> {
        let path = self.save_dir.join(&metadata.name).join("metadata.json");
        let bytes = serde_json::to_vec_pretty(metadata).map_err(|e| Status::internal(e.to_string()))?;
        fs::write(path, bytes).map_err(|e| Status::internal(format!("saving metadata: {e}")))
    }
}

/// Start a local gRPC service and wait until its listening endpoint accepts
/// connections. Its working directory is a service-specific save subdirectory.
async fn start_service<C: ConfigureClient>(
    command: &[String],
    suffix: &str,
    save_dir: &Path,
    make_client: fn(Channel) -> C,
) -> Result<(C, ChildProcess), String> {
    // Let the operating system choose an available loopback port for the child.
    let port = TcpListener::bind("127.0.0.1:0")
        .map_err(|e| e.to_string())?
        .local_addr()
        .map_err(|e| e.to_string())?
        .port();
    let address = format!("127.0.0.1:{port}");
    let mut full_command = command.to_vec();
    // Child services use this command-line convention to select their gRPC port.
    full_command.extend(["--listen".into(), address.clone()]);
    let mut child = ChildProcess::start(&full_command, Some(&save_dir.join(suffix)))?;
    let endpoint = format!("http://{address}");
    let deadline = Instant::now() + Duration::from_secs(30);
    loop {
        // Fail promptly if startup failed instead of waiting through the timeout.
        if child.0.try_wait().ok().flatten().is_some() {
            return Err(format!("gRPC service exited before becoming ready: {:?}", command));
        }
        match Channel::from_shared(endpoint.clone())
            .map_err(|e| e.to_string())?
            .connect()
            .await
        {
            // A connected channel is ready to be used by the request handlers.
            Ok(channel) => return Ok((make_client(channel).configure(), child)),
            Err(_) if Instant::now() < deadline => tokio::time::sleep(Duration::from_millis(100)).await,
            Err(e) => {
                child.close();
                return Err(format!("gRPC service timeout: {e}"));
            }
        }
    }
}

#[tonic::async_trait]
impl Environment for Shared {
    /// Select parents, ask Genetics to create a child when configured, then
    /// apply defaults and persist the new individual before returning it.
    async fn spawn(&self, req: Request<environment::SpawnRequest>) -> RpcResult<Individual> {
        let body_req = req.into_inner().body_type;
        let (body_type, mut evo, mut genetics) = {
            let mut s = self.state.lock().await;
            let body_type = s.body_type(&body_req)?;
            s.count("Spawn", &body_type);
            let o = &s.organisms[&body_type];
            (body_type, o.evolution.clone(), o.genetics.clone())
        };
        // Copy the clients while holding the state lock, then release it before
        // awaiting an upstream call so other RPCs can continue to make progress.
        let parents = if let Some(client) = evo.as_mut() {
            client
                .spawn(Request::new(evolution::SpawnRequest {}))
                .await
                .map_err(|e| self.fail_downstream(e))?
                .into_inner()
                .parents
        } else {
            vec![]
        };
        // Without Genetics, replay the first selected parent's genome. With no
        // parents, create a founder with a fresh identity and no genetic data.
        let mut child = if let Some(client) = genetics.as_mut() {
            client
                .reproduce(Request::new(genetics::ReproduceRequest {
                    parents: parents.clone(),
                }))
                .await
                .map_err(|e| self.fail_downstream(e))?
                .into_inner()
                .child
                .unwrap_or_default()
        } else if let Some(parent) = parents.first() {
            let mut p = parent.clone();
            Individual::reproduce(&mut [&mut p]).tap_genome_from(parent)
        } else {
            Individual::new()
        };
        let mut s = self.state.lock().await;
        s.set_defaults(&mut child)?;
        set_birth_date(&mut child);
        s.save(&child)?;
        let metadata = child.metadata.as_ref().cloned().unwrap_or_default();
        s.living.insert(metadata.name.clone(), metadata);
        let _ = body_type;
        Ok(Response::new(child))
    }
    /// Load the named living parents, reproduce them, and save the child plus
    /// updated parent metadata (including their child counts).
    async fn mate(&self, req: Request<environment::MateRequest>) -> RpcResult<Individual> {
        let names = req.into_inner().parents;
        if names.is_empty() {
            return Err(Status::invalid_argument("at least one parent is required"));
        }
        let (body_type, mut parents, mut genetics) = {
            let mut s = self.state.lock().await;
            let first_meta = s.living(&names[0])?;
            let body_type = s.body_type(first_meta.body_type.as_deref().unwrap_or(""))?;
            s.count("Mate", &body_type);
            let mut parents = Vec::new();
            for name in &names {
                let m = s.living(name)?;
                parents.push(Individual::load(s.save_dir.join(&m.name)).map_err(|e| Status::internal(e.to_string()))?);
            }
            let genetics = s.organisms[&body_type].genetics.clone();
            (body_type, parents, genetics)
        };
        let mut child = if let Some(client) = genetics.as_mut() {
            client
                .reproduce(Request::new(genetics::ReproduceRequest {
                    parents: parents.clone(),
                }))
                .await
                .map_err(|e| self.fail_downstream(e))?
                .into_inner()
                .child
                .unwrap_or_default()
        } else {
            let first = parents
                .first()
                .cloned()
                .ok_or_else(|| Status::invalid_argument("at least one parent is required"))?;
            Individual::reproduce(&mut parents.iter_mut().collect::<Vec<_>>()).tap_clone_data(&first)
        };
        let mut s = self.state.lock().await;
        s.set_defaults(&mut child)?;
        set_birth_date(&mut child);
        s.save(&child)?;
        for parent in parents {
            if let Some(m) = parent.metadata {
                s.save_metadata(&m)?;
            }
        }
        let metadata = child.metadata.as_ref().cloned().unwrap_or_default();
        s.living.insert(metadata.name.clone(), metadata);
        let _ = body_type;
        Ok(Response::new(child))
    }
    /// Record the latest score and update the historical maximum for this type.
    async fn score(&self, req: Request<environment::ScoreRequest>) -> RpcResult<environment::ScoreResponse> {
        let request = req.into_inner();
        let mut s = self.state.lock().await;
        let mut metadata = s.living(&request.name)?;
        let body_type = s.body_type(metadata.body_type.as_deref().unwrap_or(""))?;
        s.count("Score", &body_type);
        if !request.score.is_nan() {
            let score = s.max_scores.entry(body_type).or_insert(f64::NEG_INFINITY);
            *score = score.max(request.score);
        }
        metadata.score = Some(request.score);
        s.save_metadata(&metadata)?;
        s.living.insert(metadata.name.clone(), metadata);
        Ok(Response::new(environment::ScoreResponse {}))
    }
    /// Merge telemetry key/value pairs into the individual's metadata.
    async fn telemetry(
        &self,
        req: Request<environment::TelemetryRequest>,
    ) -> RpcResult<environment::TelemetryResponse> {
        let request = req.into_inner();
        let mut s = self.state.lock().await;
        let mut metadata = s.living(&request.name)?;
        let body_type = s.body_type(metadata.body_type.as_deref().unwrap_or(""))?;
        s.count("Telemetry", &body_type);
        for item in request.data {
            metadata.telemetry.insert(item.key, item.value);
        }
        s.save_metadata(&metadata)?;
        s.living.insert(metadata.name.clone(), metadata);
        Ok(Response::new(environment::TelemetryResponse {}))
    }
    /// Epigenome updates are reserved for a future API version.
    async fn epigenome(
        &self,
        _req: Request<environment::EpigenomeRequest>,
    ) -> RpcResult<environment::EpigenomeResponse> {
        Err(Status::unimplemented("Epigenome updates are not implemented"))
    }
    /// Stamp the death time, notify Evolution, and remove the individual's
    /// persisted files after the downstream service accepts the record.
    async fn death(&self, req: Request<environment::DeathRequest>) -> RpcResult<environment::DeathResponse> {
        let request = req.into_inner();
        let (mut individual, mut evolution, path, body_type) = {
            let mut s = self.state.lock().await;
            let metadata = s.living(&request.name)?;
            let body_type = s.body_type(metadata.body_type.as_deref().unwrap_or(""))?;
            s.count("Death", &body_type);
            let path = s.save_dir.join(&metadata.name);
            let individual = Individual::load(&path).map_err(|e| Status::internal(e.to_string()))?;
            (individual, s.organisms[&body_type].evolution.clone(), path, body_type)
        };
        set_death_date(&mut individual);
        let dead_name = individual.metadata.as_ref().map(|m| m.name.clone()).unwrap_or_default();
        if let Some(client) = evolution.as_mut() {
            client
                .death(Request::new(evolution::DeathRequest {
                    individual: Some(individual),
                }))
                .await
                .map_err(|e| self.fail_downstream(e))?;
        }
        let mut s = self.state.lock().await;
        s.living.remove(&dead_name);
        Individual::delete(path).map_err(|e| Status::internal(e.to_string()))?;
        let _ = body_type;
        Ok(Response::new(environment::DeathResponse {}))
    }
}

#[tonic::async_trait]
impl Diagnostics for Shared {
    /// Count living individuals whose stored body type matches the query.
    async fn living_count(&self, req: Request<diagnostics::Organism>) -> RpcResult<diagnostics::Count> {
        let s = self.state.lock().await;
        let body = s.body_type(&req.into_inner().body_type)?;
        Ok(Response::new(diagnostics::Count {
            count: s
                .living
                .values()
                .filter(|m| m.body_type.as_deref() == Some(&body))
                .count() as u64,
        }))
    }
    /// The remaining diagnostics handlers share the same per-type counter lookup.
    async fn spawn_count(&self, r: Request<diagnostics::Organism>) -> RpcResult<diagnostics::Count> {
        self.count_for("Spawn", r).await
    }
    async fn mate_count(&self, r: Request<diagnostics::Organism>) -> RpcResult<diagnostics::Count> {
        self.count_for("Mate", r).await
    }
    async fn score_count(&self, r: Request<diagnostics::Organism>) -> RpcResult<diagnostics::Count> {
        self.count_for("Score", r).await
    }
    async fn telemetry_count(&self, r: Request<diagnostics::Organism>) -> RpcResult<diagnostics::Count> {
        self.count_for("Telemetry", r).await
    }
    async fn death_count(&self, r: Request<diagnostics::Organism>) -> RpcResult<diagnostics::Count> {
        self.count_for("Death", r).await
    }
    /// Return negative infinity until the first score has been reported.
    async fn maximum_score(&self, req: Request<diagnostics::Organism>) -> RpcResult<diagnostics::Score> {
        let s = self.state.lock().await;
        let body = s.body_type(&req.into_inner().body_type)?;
        Ok(Response::new(diagnostics::Score {
            score: *s.max_scores.get(&body).unwrap_or(&f64::NEG_INFINITY),
        }))
    }
}
impl Shared {
    /// Validate the body type and read one call counter, defaulting to zero.
    async fn count_for(&self, call: &str, req: Request<diagnostics::Organism>) -> RpcResult<diagnostics::Count> {
        let s = self.state.lock().await;
        let body = s.body_type(&req.into_inner().body_type)?;
        Ok(Response::new(diagnostics::Count {
            count: *s.counts.get(&(body, call.into())).unwrap_or(&0),
        }))
    }
}

/// Helpers for the two no-Genetics fallback paths.
trait IndividualExt {
    fn tap_genome_from(self, parent: &Individual) -> Individual;
    fn tap_clone_data(self, parent: &Individual) -> Individual;
}
/// Copy only the genome for a Spawn replay, matching the server's clone policy.
impl IndividualExt for Individual {
    fn tap_genome_from(mut self, parent: &Individual) -> Individual {
        self.genome = parent.genome.clone();
        self
    }
    /// Copy genome, epigenome, and phenome bytes for a direct Mate clone.
    fn tap_clone_data(mut self, parent: &Individual) -> Individual {
        self.genome = parent.genome.clone();
        self.epigenome = parent.epigenome.clone();
        self.phenome = parent.phenome.clone();
        self
    }
}
/// Timestamps are stored as seconds/nanoseconds since the Unix epoch.
fn set_birth_date(i: &mut Individual) {
    if let Some(m) = i.metadata.as_mut() {
        m.birth_date = Some(now_timestamp());
    }
}
/// Record the time immediately before sending the final record to Evolution.
fn set_death_date(i: &mut Individual) {
    if let Some(m) = i.metadata.as_mut() {
        m.death_date = Some(now_timestamp());
    }
}
/// Return the current wall-clock time in Protobuf Timestamp form.
fn now_timestamp() -> pbjson_types::Timestamp {
    let d = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    pbjson_types::Timestamp {
        seconds: d.as_secs() as i64,
        nanos: d.subsec_nanos() as i32,
    }
}
/// Ask the OS for a currently unused loopback port.
fn free_port() -> Result<u16, String> {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|s| s.local_addr())
        .map(|a| a.port())
        .map_err(|e| e.to_string())
}
/// Keep the command-line usage string in one place for errors and --help.
fn usage() -> &'static str {
    "Usage: npc-server [-v|--verbose] [--listen HOST:PORT] [--workers NUM] CONFIG SAVE_DIR"
}

#[tokio::main]
async fn main() {
    let result = run().await;
    if let Err((code, error)) = result {
        eprintln!("{error}");
        std::process::exit(code);
    }
}
/// Parse options, load the experiment, start children, and serve both APIs.
async fn run() -> Result<(), (i32, String)> {
    let mut verbose = false;
    let mut listen: Option<String> = None;
    let mut workers = 1usize;
    let mut positional = Vec::new();
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "-v" | "--verbose" => verbose = true,
            "--listen" => {
                listen = Some(
                    args.next()
                        .ok_or((2, format!("expected address after --listen\n{}", usage())))?,
                )
            }
            "--workers" => {
                let value = args
                    .next()
                    .ok_or((2, format!("expected number after --workers\n{}", usage())))?;
                workers = value
                    .parse()
                    .map_err(|_| (2, format!("invalid worker count \"{value}\"\n{}", usage())))?;
            }
            "-h" | "--help" => {
                println!("{}", usage());
                return Ok(());
            }
            _ if arg.starts_with('-') => return Err((2, format!("unknown option: {arg}\n{}", usage()))),
            _ => positional.push(arg),
        }
    }
    if positional.len() != 2 {
        return Err((2, usage().into()));
    }
    let config_path = PathBuf::from(&positional[0]);
    let save_dir = PathBuf::from(&positional[1]);
    let config_data = fs::read(&config_path).map_err(|e| (5, format!("{e}")))?;
    let config: Experiment =
        serde_json::from_slice(&config_data).map_err(|e| (5, format!("invalid experiment config: {e}")))?;
    eprintln!(
        "INFO: Starting NPC server with configuration:\n{}",
        serde_json::to_string_pretty(&config).unwrap_or_default()
    );
    if verbose {
        eprintln!("DEBUG: configuration loaded from {}", config_path.display());
    }
    // Start downstream services before binding the public server, so malformed
    // commands and unavailable services fail during startup.
    let state = State::new(config.clone(), save_dir).await.map_err(|e| (5, e))?;
    let requested = listen.unwrap_or_else(|| format!("127.0.0.1:{}", free_port().unwrap_or(0)));
    let mut addr: SocketAddr = requested
        .parse()
        .map_err(|e| (7, format!("invalid listen address: {e}")))?;
    if addr.port() == 0 {
        addr.set_port(free_port().map_err(|e| (7, e))?);
    }
    let (shutdown_tx, mut shutdown_rx) = watch::channel(false);
    let shared = Shared {
        state: Arc::new(Mutex::new(state)),
        shutdown: shutdown_tx,
    };
    let shutdown_shared = shared.clone();
    let shutdown = async move {
        // Ctrl+C is a normal shutdown; a watch update means a downstream RPC
        // failed and the process should return a failure status after cleanup.
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {},
            _ = shutdown_rx.changed() => {},
        }
        let mut s = shutdown_shared.state.lock().await;
        s.failed = *shutdown_rx.borrow();
        for mut env in s.environments.drain(..).rev() {
            env.close();
        }
        for child in s.children.iter_mut().rev() {
            child.close();
        }
    };
    let service = Server::builder()
        .add_service(
            EnvironmentServer::new(shared.clone())
                .max_encoding_message_size(MAX_MESSAGE_SIZE)
                .max_decoding_message_size(MAX_MESSAGE_SIZE),
        )
        .add_service(
            DiagnosticsServer::new(shared.clone())
                .max_encoding_message_size(MAX_MESSAGE_SIZE)
                .max_decoding_message_size(MAX_MESSAGE_SIZE),
        );
    let server = tokio::spawn(service.serve_with_shutdown(addr, shutdown));
    let bound = format!("{}:{}", addr.ip(), addr.port());
    {
        // Start the environment only after the server endpoint is established
        // in configuration, passing it the address that it should connect to.
        let mut s = shared.state.lock().await;
        s.listen = bound.clone();
        for worker in 0..workers {
            let mut command = s.config.environment.clone();
            command.extend(["--listen".into(), bound.clone()]);
            let child = ChildProcess::start(&command, None)
                .map_err(|e| (5, format!("starting environment worker {}: {e}", worker + 1)))?;
            s.environments.push(child);
        }
    }
    eprintln!("INFO: Serving Environment and Diagnostics on {bound}");
    match server.await {
        Ok(Ok(())) => {}
        Ok(Err(e)) => return Err((7, e.to_string())),
        Err(e) => return Err((1, e.to_string())),
    }
    let mut s = shared.state.lock().await;
    for mut child in s.environments.drain(..).rev() {
        child.close();
    }
    for child in s.children.iter_mut().rev() {
        child.close();
    }
    if s.failed {
        Err((1, "downstream service failure".into()))
    } else {
        Ok(())
    }
}
