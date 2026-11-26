"""Add one read-only host volume when the local development login exists."""

import json
import os
import sys
from pathlib import Path

auth = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "auth.json"
configuration = ""
if auth.is_file():
    configuration = (
        'client {\n  host_volume "harness-codex-login" {\n'
        f"    path = {json.dumps(str(auth.resolve()))}\n"
        "    read_only = true\n  }\n}\n"
    )
Path(sys.argv[1]).write_text(configuration)
