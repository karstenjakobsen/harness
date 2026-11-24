# Codex file harness

The operator is the Python CLI invoked by `make run`. It submits a fixed task over MCP and prints its run ID. The agent in this test is the Codex worker. The prompt explicitly names `write_file`, then `read_file`. A passing trace demonstrates worker launch, tool delivery, evidence capture, and independent verification. Autonomous tool discovery and an agentic operator are separate experiments.

## Run with Nomad

Use a Linux host with Docker Compose 2.24.4 or newer, Make, and Python 3. The single Nomad server runs in Compose. The Nomad client runs on the host alongside the Docker daemon. Its Docker driver starts the same worker image on the existing MCP network. Only the host client needs access to the Docker socket. The harness reaches the server API on a separate Compose network. The server publishes its RPC port on host loopback for the client.

In one terminal, start the server and host client. Leave the client running. This command copies the matching Linux binary from the pinned server image, validates the client configuration, and invokes `sudo` for the foreground client. Its state lives in `/var/lib/harness-nomad`. The optional auth file becomes a named, read-only client volume.

```sh
make nomad-client CODEX_AUTH_FILE="$HOME/.codex/auth.json"
```

In another terminal, run the real worker and use its printed UUID to inspect the result.

```sh
make run BACKEND=nomad CODEX_AUTH_FILE="$HOME/.codex/auth.json"
make get RUN_ID=<uuid>
```

The harness registers a one-task batch job with task restarts and rescheduling disabled. It saves `job_id`, `allocation_id`, node ID, and allocation status in the same run record as the prompt and verifier result. The task's termination event supplies the exit code. The harness fetches stdout and stderr from the client through the server API, persists the verification, requests garbage collection of that allocation, and purges that job. The lookup reads the evidence volume and also works for earlier Docker runs.

The local development cluster trusts processes with access to the host loopback RPC port or the Compose control network. For a live worker, file-based sign-in keeps the Codex credential out of the Nomad job spec. If you use the alternative `CODEX_API_KEY` environment setting, Nomad receives the key as task environment in the job spec. The worker receives only its own run token for the MCP file tools.

Run `make smoke BACKEND=nomad` to check the positive and both negative cases. It restarts the harness and compares all three recovered JSON records with their pre-restart copies. For fixture runs the host client can be started with `make nomad-client` alone. To stop the development stack after all runs finish, press Ctrl-C in the client's terminal and run `make down BACKEND=nomad`. Both named data volumes persist.

[Nomad client requirements](https://developer.hashicorp.com/nomad/docs/deploy/production/requirements) · [Docker task driver](https://developer.hashicorp.com/nomad/docs/deploy/task-driver/docker) · [Client logs and allocation garbage collection](https://developer.hashicorp.com/nomad/api-docs/client)

### Recorded Nomad proof

On November 24, 2026, the CLI submitted run `61d60eb1-cd4a-467e-9c4f-c11ad29349ea`. Nomad linked job `harness-61d60eb1-cd4a-467e-9c4f-c11ad29349ea` to allocation `f0c404ed-c196-5d77-eb8b-d76db2c279ee`. The Codex event stream and MCP journal both recorded a write followed by a read. The task exited zero, and the post-exit verifier read the expected 22 bytes.

Nomad subsequently returned HTTP 404 for the job and the client allocation filesystem. After restarting the harness, the full JSON trace from `make get` had the same SHA-256 digest as before restart (computed over sorted-key JSON). The missing-file and trailing-newline workers also exited zero, and both received `verification failed`.

```sh
make get RUN_ID=61d60eb1-cd4a-467e-9c4f-c11ad29349ea
```

These IDs are stored in the evidence volume on the machine that ran the proof. After stopping the entire Nomad stack, use `make get BACKEND=nomad RUN_ID=…` to start the same configuration for lookup.

## Run with direct Docker

Use a local Linux-container Docker daemon with Compose and Make. For file-based sign-in, use an absolute path on the Docker daemon host. The worker runs as the invoking user's UID so it can read a mode-0600 auth file.

```sh
make run CODEX_AUTH_FILE="$HOME/.codex/auth.json"
```

This mounts that single file read-only in the Codex worker. Alternatively, export a dedicated `CODEX_API_KEY` and run `make run`. File-based credentials take precedence when both options are set. The operator and fixture workers receive neither credential.

Copy the UUID from the first `run_id=` line to retrieve the evidence as JSON.

```sh
make get RUN_ID=<uuid>
```

Replace `<uuid>` with the printed ID. The run command returns zero for a pass and nonzero for a failed run. The lookup command returns a record for either outcome. Use `make down` to stop Compose. A subsequent lookup starts the harness against the same evidence volume.

## What a pass proves

1. The operator calls `start_run` on the harness's operator MCP endpoint. The harness saves the prompt, generates a UUID, and launches the fixed worker image. The direct Docker backend records the container and image IDs. The Nomad backend records its job and allocation IDs.
2. The worker runs `codex exec --json` and uses a per-run bearer token on the worker MCP endpoint. It can call `write_file` and `read_file` for the single path `result.txt`. The harness writes the file in that run's workspace and journals each call with its arguments and outcome.
3. After the execution backend reports the worker has exited, the harness closes its tool access, saves stdout and stderr, and opens the workspace file itself. A pass requires exit code zero, exactly `hello from the harness` in UTF-8 (22 bytes), and evidence of a successful write followed by a read of those bytes.
4. The harness persists the verdict and one-line summary before backend cleanup. `get_run` returns the launch record, exit status, tool journal, worker output, verification, and cleanup status under the original ID.

In direct Docker mode the harness mounts the Docker socket. The two MCP endpoints are on the Compose network with separate credentials. The worker uses an MCP-backed workspace and a read-only container filesystem with temporary scratch space. The harness keeps each run in the Compose `evidence` volume.

```text
/data/<run-id>/
  run.json              launch, backend identifiers, exit, verification, summary
  tools.jsonl           timestamped tool arguments, results and errors
  stdout.jsonl          worker events, including the Codex event stream
  stderr.log            worker diagnostics
  workspace/result.txt  file opened by the verifier
```

## Exercise the failure cases

```sh
make smoke
```

The smoke test uses real Docker workers and the same MCP endpoints. It checks a correct write, a missing file, and a trailing newline. All three workers exit zero. The latter two must report `verification failed`, and each trace must still be retrievable after container removal. These deterministic workers run without a model credential. To inspect an individual failure, run `make run WORKER=fixture-wrong` and look up its ID.

## Local development

Install uv, then run the following from the project directory.

```sh
make setup    # Creates .venv with Python 3.14 and dependencies from uv.lock
make lint     # Ruff lint and format checks
make test     # Evidence and MCP authorization tests
```

The harness runs one process and gives each worker four minutes. On restart it resumes runs for the configured backend. A deterministic container or job name allows recovery from an interrupted submission. Catalog and seed-skill tests are a later slice.
