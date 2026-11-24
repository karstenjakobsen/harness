# Codex file harness

One command starts a real Codex worker in Docker, prints its run ID, and waits for the harness to verify the result. The operator can disconnect after receiving the ID. The harness continues the run.

## Run the proof

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

1. The operator calls `start_run` on the harness's operator MCP endpoint. The harness saves the prompt, generates a UUID, and launches the fixed worker image. Docker supplies the container ID and image ID.
2. The worker runs `codex exec --json` and uses a per-run bearer token on the worker MCP endpoint. It can call `write_file` and `read_file` for the single path `result.txt`. The harness writes the file in that run's workspace and journals each call with its arguments and outcome.
3. After Docker reports the worker has exited, the harness closes its tool access, saves stdout and stderr, and opens the workspace file itself. A pass requires exit code zero, exactly `hello from the harness` in UTF-8 (22 bytes), and evidence of a successful write followed by a read of those bytes.
4. The harness persists the verdict and one-line summary before removing the worker container. `get_run` returns the launch record, exit status, tool journal, worker output, verification, and cleanup status under the original ID.

Only the harness mounts the Docker socket. The two MCP endpoints are on the Compose network with separate credentials. The worker uses an MCP-backed workspace and a read-only container filesystem with temporary scratch space. The harness keeps each run in the Compose `evidence` volume.

```text
/data/<run-id>/
  run.json              launch, container and image IDs, exit, verification, summary
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

The backend uses one harness process and the local Docker Engine. On restart it uses the run's container ID or deterministic name to resume monitoring and finish collection. The worker deadline is four minutes. This slice implements the direct Docker backend from the discussion. Nomad and the catalog/seed-skill experiment are follow-up work.
