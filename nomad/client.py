"""Start the Linux host client in the foreground with optional read-only Codex credentials."""

import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

root = Path(__file__).resolve().parent.parent
local = root / ".nomad"
local.mkdir(mode=0o700, exist_ok=True)
binary = local / "nomad"
with TemporaryDirectory(dir=local) as stage:
    candidate = Path(stage) / "nomad"
    subprocess.run(["docker", "compose", "cp", "nomad:/bin/nomad", str(candidate)], check=True)
    candidate.replace(binary)
configs = [root / "nomad/client.hcl"]
if auth := os.getenv("CODEX_AUTH_FILE"):
    path = Path(auth).resolve(strict=True)
    if not path.is_file():
        raise SystemExit("CODEX_AUTH_FILE must point to a file")
    config = local / "auth.hcl"
    config.write_text(
        'client {\n  host_volume "harness-codex-auth" {\n'
        f"    path = {json.dumps(str(path))}\n    read_only = true\n  }}\n}}\n"
    )
    configs.append(config)
subprocess.run([binary, "config", "validate", *configs], check=True)
os.execvp("sudo", ["sudo", str(binary), "agent", *(f"-config={cfg}" for cfg in configs)])
