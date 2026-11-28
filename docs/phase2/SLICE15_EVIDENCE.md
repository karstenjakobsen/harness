# Slice 15 evidence — Codex API key from a Nomad Variable

This experiment uses one manually provisioned variable in the local Nomad cluster’s `default` namespace. With ACLs and TLS disabled, clients that can reach the API can read or change it over HTTP. Keep this setup on the local development cluster. [Nomad variable API](https://developer.hashicorp.com/nomad/api-docs/variables/variables) · [Checklist](SLICE15_TODO.md)

## Manual provisioning and run

Start the local cluster with `make nomad-up`. From the repo root, create the variable from the existing private key file. The compare-and-set value of zero protects an existing variable from replacement. The command prints the path and status.

```sh
.venv/bin/python - .harness/credentials/codex.key <<'PY'
import sys
from pathlib import Path

import httpx

path = "harness/dev/providers/codex"
key = Path(sys.argv[1]).read_text().strip()
if not key or any(char.isspace() for char in key):
    raise SystemExit("Expected one Codex API key in the private file.")
with httpx.Client(
    base_url="http://127.0.0.1:14646/v1/", trust_env=False, timeout=10
) as nomad:
    response = nomad.put(
        f"var/{path}", params={"cas": 0}, json={"Path": path, "Items": {"api_key": key}}
    )
    if response.status_code == 409:
        saved = nomad.get(f"var/{path}")
        if saved.status_code != 200 or saved.json().get("Items", {}).get("api_key") != key:
            raise SystemExit("The existing Nomad variable differs from the supplied key.")
        print(f"Verified existing Nomad variable {path}.")
    elif response.is_success:
        print(f"Created Nomad variable {path}.")
    else:
        raise SystemExit(f"Nomad variable create failed with HTTP {response.status_code}.")
PY
bash docs/phase2/SLICE15_EVIDENCE.sh --live
```

The script renders one worker job with `--nomad-variable` and submits it directly. Nomad renders `harness/dev/providers/codex` item `api_key` into `secrets/provider-key` once at launch. The bootstrap reads the file through `NOMAD_SECRETS_DIR` and supplies `CODEX_API_KEY` to Codex. Harness issues and revokes the separate attempt credential as usual. The shared variable remains available for the next local run.

## Live result

On 2026-11-28, Nomad 2.1.1 ran one Codex 0.166.0 session with explicit model `gpt-5.6-luna` and effort `low`. The launcher environment had both Codex and OpenAI key variables unset, and the run supplied no local key file. Nomad reported exit 0 and zero restarts. No AI operator session ran.

| Field | Observed value |
| --- | --- |
| Workspace | `dev/.harness/phase2/slice15-RzQ5u0` |
| Attempt | `phase2-fc4eec84dcdf4ecc864a7a52d53c56bd` |
| Nomad job | `phase2-852e73a2e3b3430d87998c9648ccda0b` |
| Allocation | `94e07ae6-9a49-88c8-58fe-3dab60d547a7` |
| Rendered job SHA-256 | `f0b6e2410c1548d7b2a559fac97ea09266173a602ff21a777a20f33f9c67e8a7` |
| Harness grant and artifact | Grant 1, artifact 1 |
| Exported file SHA-256 | `9437f83af86c3ef8a1b091b44cc915bc38e8fac637a345b4c7c6ac7dc552967d` |

Harness audited the brief read, assigned skill read and submission under grant 1. After credential revocation and scratch cleanup, the export contained the exact five UTF-8 city lines. Nomad returned HTTP 404 for both the job and allocation. The variable was still present in Nomad’s metadata list, with ACLs and HTTP/RPC TLS disabled. The literal provider key was absent from the submitted job, receipt, allocation snapshot and retained logs.

## Offline checks

`bash docs/phase2/SLICE15_EVIDENCE.sh` passed `make check` and `make test` with 294 tests passed and 14 live or Nomad tests deselected. The renderer test covers the task template, the separate Harness credential and rejection of the flag for Kiro.
