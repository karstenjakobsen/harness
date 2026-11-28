# Slice 14 verification

The worker and experiment code is implemented. The API-key Kiro MCP probe and the two API-key deliveries are pending credentials. [Slice 14 checklist](SLICE14_TODO.md)

## Docker checks

Both worker images built on `linux/amd64`. Both CLIs printed their versions in ordinary Docker as UID/GID `1000:1000` with networking disabled. With dummy credentials, the shared entrypoint rejected `ultra` for both `gpt-5.6-luna` and `claude-sonnet-4.6` before starting a model session.

| Local image | CLI version | Build digest |
| --- | --- | --- |
| `harness-worker:codex-slice14` | `codex-cli 0.166.0` | `sha256:1aec54064f6f2a631b54986586bc598028283735820a2f35c595271bf3371789` |
| `harness-worker:kiro-slice14` | `kiro-cli 3.7.0` | `sha256:a2fd717c6e9b2db835e6f37a7cf09862977e39277377602a9792588d155c40b3` |

The Kiro Dockerfile uses the candidate base that passed the CLI checks. The audited brief read is the remaining compatibility check for that base. Codex validates explicit selections against the catalog bundled with its image. Kiro validates the documented effort levels for Claude Sonnet 4.6 and Claude Opus 4.6, 4.7 and 4.8. Availability under the configured provider account is established by a live run. [Kiro model and effort reference](https://kiro.dev/docs/cli/chat/model-selection/)

## Offline tests

```sh
bash docs/phase2/SLICE14_EVIDENCE.sh
```

`make check` passed. `make test` passed 293 tests with 14 live or Nomad tests deselected. The suite ran with loopback sockets enabled for the local MCP tests.

The tests exercise explicit Codex API-key and saved-login configurations, explicit Kiro API-key configuration, two different model and effort selections per worker, and the existing Codex invocation and receipt recovery. A fixture drives a real Harness MCP server with a simulated Nomad task to verify grant and artifact attribution, exact retrieval after cleanup, and delivery with incomplete activity. A separate fixture exercises replay display for a Kiro tool event.

## Live commands

Start the development Nomad cluster with `make nomad-up`, or set `HARNESS_NOMAD_ADDR` to the intended running cluster. Set the provider keys in the environment or set `SLICE14_KIRO_KEY_FILE` and `SLICE14_CODEX_KEY_FILE` to private files. The brief probe uses only the Kiro credential. Each command creates a workspace under `dev/.harness/phase2/` and prints the rendered job and selected evidence fields.

```sh
bash docs/phase2/SLICE14_EVIDENCE.sh --probe
bash docs/phase2/SLICE14_EVIDENCE.sh --live
```

The `--live` run first checks the disposable Kiro brief probe. It then prepares two delivery attempts against the same work item and exports each artifact before starting the next worker. Native stdout and stderr, the Nomad allocation snapshot, the Harness audit and the post-cleanup export are retained under the corresponding attempt’s receipt directory.

The live preflight stopped before submission because `KIRO_API_KEY` was unset. `CODEX_API_KEY` was also unset. There is no live MCP, Nomad exit, artifact or native replay evidence for Slice 14 yet.
