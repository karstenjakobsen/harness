"""Configure the guard volume and the optional local Codex login volume."""

import json
import os
import sys
from pathlib import Path

auth = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "auth.json"
guard = Path(".harness/nomad/acl/guard").resolve(strict=True)
configuration = (
    'client {\n  host_volume "harness-guard" {\n'
    f"    path = {json.dumps(str(guard))}\n    read_only = true\n  }}\n}}\n"
)
if auth.is_file():
    configuration += (
        'client {\n  host_volume "harness-codex-login" {\n'
        f"    path = {json.dumps(str(auth.resolve()))}\n"
        "    read_only = true\n  }\n}\n"
    )
Path(sys.argv[1]).write_text(configuration)
