# Slice 14 verification

On 2026-11-28, the Kiro API-key probe read its Harness brief, and Codex and Kiro each delivered the city assignment through worker MCP. Both delivery artifacts were retrieved and verified after cleanup. [Slice 14 checklist](SLICE14_TODO.md)

## Docker checks

Both worker images built on `linux/amd64`. Both CLIs printed their versions in ordinary Docker as UID/GID `1000:1000` with networking disabled. With dummy credentials, the shared entrypoint rejected `ultra` for both `gpt-5.6-luna` and `claude-sonnet-4.6` before starting a model session.

| Local image | CLI version | Build digest |
| --- | --- | --- |
| `harness-worker:codex-slice14` | `codex-cli 0.166.0` | `sha256:1aec54064f6f2a631b54986586bc598028283735820a2f35c595271bf3371789` |
| `harness-worker:kiro-slice14` | `kiro-cli 3.7.0` | `sha256:a2fd717c6e9b2db835e6f37a7cf09862977e39277377602a9792588d155c40b3` |

The Kiro Dockerfile uses the pinned base that passed the CLI checks and the live brief probe. Codex validates explicit selections against the catalog bundled with its image. Kiro checks the documented combinations before launch and checks the settings reported by the live CLI when available. [Kiro model and effort reference](https://kiro.dev/docs/cli/chat/model-selection/)

## Offline tests

```sh
bash docs/phase2/SLICE14_EVIDENCE.sh
```

`make check` passed. `make test` passed 293 tests with 14 live or Nomad tests deselected. The suite ran with loopback sockets enabled for the local MCP tests.

The tests exercise explicit Codex API-key and saved-login configurations, explicit Kiro API-key configuration, two different model and effort selections per worker, and the existing Codex invocation and receipt recovery. A fixture drives a real Harness MCP server with a simulated Nomad task to verify grant and artifact attribution, exact retrieval after cleanup, and delivery with incomplete activity. A separate fixture exercises replay display for a Kiro tool event.

## Live commands

Put one key per file under the repository’s ignored `.harness/credentials/` directory. Use `codex.key` for Codex and `kiro.key` for Kiro. Set the directory mode to `0700` and file modes to `0600`. The evidence script uses these files by default. To override a default, set the provider key in `CODEX_API_KEY` or `KIRO_API_KEY`, or select another file with `SLICE14_CODEX_KEY_FILE` or `SLICE14_KIRO_KEY_FILE`. An explicit file takes precedence over the environment key.

Start the development Nomad cluster with `make nomad-up`, or set `HARNESS_NOMAD_ADDR` to the intended running cluster. The brief probe uses only the Kiro credential. The script detects Docker Desktop and selects `http://host.docker.internal:8001/mcp`. The Kiro worker accepts the connection through a loopback relay to the host service. Set `HARNESS_PHASE2_MCP_URL` to override the worker endpoint. Each command creates a workspace under `dev/.harness/phase2/` and prints the rendered job and selected evidence fields.

```sh
bash docs/phase2/SLICE14_EVIDENCE.sh --probe
bash docs/phase2/SLICE14_EVIDENCE.sh --live
```

The `--live` run first checks the disposable Kiro brief probe. It then prepares two delivery attempts against the same work item and exports each artifact before starting the next worker. Native stdout and stderr, the Nomad allocation snapshot, the Harness audit and the post-cleanup export are retained under the corresponding attempt’s receipt directory.

## Captured live results

The live run used Nomad 2.1.1 and Docker Desktop, with both provider keys read from the shared credential directory. The retained workspace is `dev/.harness/phase2/slice14-wIZNB6`. The final script run completed the brief probe before the Codex image build stopped with a Buildx error. The same build passed on retry, and the two deliveries were resumed from the successful probe receipt in this workspace.

| Attempt | Model and effort | Nomad allocation | Exit | Grant | Artifact |
| --- | --- | --- | --- | --- | --- |
| `phase2-1bb27fd5c6da4a14995a8380b8489dda` | `claude-opus-4.8`, `low` | `d614b481-0344-3c81-2cb3-4cc32cd1bbf7` | 0 | 1 | Brief only |
| `slice14-codex` | `gpt-5.6-luna`, `low` | `6a526957-fa30-414d-399f-4d82c3e83094` | 0 | 2 | 1 |
| `slice14-kiro` | `claude-opus-4.8`, `low` | `f9d35a2c-de2c-d6e1-0121-104ca79f0ad7` | 0 | 3 | 2 |

- Kiro 3.7.0 reported Opus 4.8 and `low` as its effective settings in both sessions. The Codex 0.166.0 receipt records the requested settings. Each attempt recorded one worker session, zero AI operator sessions and zero task restarts.
- Harness audited a returned `get_work_brief` on grant 1. Both deliveries recorded returned `get_work_brief`, `read_skill("worker-handoff", 1)`, and `submit_work_result` calls under their own grants. Both deliveries used work item 1 and goal revision 1.
- Both exports matched the five UTF-8 city lines and SHA-256 `9437f83af86c3ef8a1b091b44cc915bc38e8fac637a345b4c7c6ac7dc552967d`. The jobs and allocations returned HTTP 404 after cleanup. Scratch and runtime credentials had been removed, and the goal remained active at revision 1.
- Both native streams were captured for each attempt. Replaying Kiro’s saved stdout after cleanup located `@worker/get_work_brief` on line 29 and its `completed` update on line 35, which agrees with the Harness audit. The retained jobs, receipts and worker streams contained neither provider key.
- The delivered Codex image digest was `sha256:af5df61701c5b64442b4699ffd5eb476a58514b565e48e014bc0871597d90540`. Both Kiro jobs used `sha256:cb93952cec87acdbf5df72387fbf64259ea8a8e1e2c78ac9d717f2a99282f882`.

The first two probes exposed Docker Desktop’s host routing and Kiro’s requirement for HTTPS or local HTTP MCP. The first probe also reported that Sonnet 4.6 offered no effort levels for the API-key session. The final run used the loopback relay and Opus 4.8.

## Verification after splitting the launchers

On 2026-11-28, `bash docs/phase2/SLICE14_EVIDENCE.sh --live` rebuilt both images from their separate launchers. The successful run is retained under `dev/.harness/phase2/slice14-EJBGpK`. The Kiro brief probe and both API-key deliveries exited 0. Both delivery artifacts matched the expected city bytes after cleanup. Kiro reported Opus 4.8 at `low` on the successful probe and delivery.

The first probe of the split read its brief but reported `high` after the CLI was asked for `low`. The runner flagged the mismatch. The retry used the same Kiro image and requested settings and passed.
