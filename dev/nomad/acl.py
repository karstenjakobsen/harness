"""Bootstrap this checkout's development cluster and keep ACL tokens on the host."""

import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

ADDRESS = "http://127.0.0.1:14646/v1/"
directory = Path(".harness/nomad/acl")
os.umask(0o077)
directory.mkdir(exist_ok=True)


def request(path, *, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Nomad-Token"] = token
    data = json.dumps(body).encode() if body is not None else None
    with urlopen(
        Request(ADDRESS + path, data=data, headers=headers), timeout=5
    ) as response:
        payload = response.read()
        return json.loads(payload) if payload else None


def save(name, secret):
    temporary = directory / (name + ".tmp")
    temporary.write_text(secret)
    temporary.replace(directory / name)


def active(token):
    try:
        return request("acl/token/self", token=token)["SecretID"] == token
    except HTTPError as error:
        if error.code not in (403, 404):
            raise
        return False


root_file = directory / "bootstrap"
if not root_file.exists():
    save("bootstrap", str(uuid4()))
root = root_file.read_text()
if not active(root):
    request("acl/bootstrap", body={"BootstrapSecret": root})
    if not active(root):
        raise SystemExit("Could not verify this checkout's Nomad bootstrap credential.")

policies = {
    "guard": 'namespace "default" { capabilities = ["read-job"] }',
    "launcher": """
        namespace "default" { policy = "write" }
        node { policy = "read" }
        host_volume "harness-guard" { policy = "read" }
        host_volume "harness-codex-login" { policy = "read" }
    """,
}
for name, rules in policies.items():
    policy = "harness-" + name
    request("acl/policy/" + policy, token=root, body={"Name": policy, "Rules": rules})
    path = directory / name
    if not path.exists() or not active(path.read_text()):
        record = request(
            "acl/token",
            token=root,
            body={"Name": policy, "Type": "client", "Policies": [policy]},
        )
        save(name, record["SecretID"])
