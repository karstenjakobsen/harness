#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."

make check
make test

# Check the archive paths without rerunning historical workloads.
.venv/bin/python - <<'PY'
import re
import subprocess
from pathlib import Path

paths = [Path(name) for name in ("AGENTS.md", "README.md", "CATALOG.md", "TERMINOLOGY.md")]
paths.extend(Path("docs").rglob("*.md"))
for path in paths:
    for link in re.findall(r"\]\(([^)]+)\)", path.read_text()):
        if "://" in link or link.startswith("#"):
            continue
        assert (path.parent / link.split("#")[0]).exists(), (path, link)
for path in Path("docs").rglob("*EVIDENCE.sh"):
    subprocess.run(["bash", "-n", str(path)], check=True)
print("Local documentation links and evidence shell syntax passed.")

# Execute the documented command sequence through the installed CLI and MCP.
readme = Path("README.md").read_text()
section = readme.split("## Prepare an attempt and hand off a file\n")[1].split("## Sign in to Codex\n")[0]
blocks = re.findall(r"```sh\n(.*?)```", section, re.S)
assert len(blocks) == 2
subprocess.run(["bash"], input="set -euo pipefail\n" + "\n".join(blocks), text=True, check=True)
print("README manual handoff, recovery, revocation and server shutdown passed.")
PY

git diff --check
