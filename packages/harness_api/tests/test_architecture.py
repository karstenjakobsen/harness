import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

import harness_api

PACKAGES = Path(__file__).resolve().parents[2]
ADAPTER_MODULES = (
    "click",
    "fastapi",
    "mcp",
    "codex",
    "harness_mcp",
    "harness_operator",
    "harness_api.app",
    "harness_api.controllers",
    "harness_api.views",
)


def imported_names(path, package):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.lineno, alias.name, None
        elif isinstance(node, ast.ImportFrom):
            module = resolve_name("." * node.level + (node.module or ""), package)
            for alias in node.names:
                yield alias.lineno, module, alias.name


def import_violations(path, src):
    relative = path.relative_to(src)
    package = ".".join(relative.parent.parts)
    for line, module, member in imported_names(path, package):
        name = f"{module}.{member}" if member is not None else module
        if relative.parts[0] == "harness_api":
            forbidden = any(
                name == adapter or name.startswith(adapter + ".")
                for adapter in ADAPTER_MODULES
            )
        else:
            root = module.partition(".")[0]
            forbidden = root in ("sqlite3", "_sqlite3") or (
                root == "harness_api"
                and (module != "harness_api" or member not in harness_api.__all__)
            )
        if forbidden:
            yield f"{path}:{line}: forbidden import {name}"


def test_production_import_boundaries():
    violations = []
    for package in ("harness_api", "harness_operator", "harness_mcp"):
        src = PACKAGES / package / "src"
        root = src / package
        if package == "harness_api":
            paths = [root / "database.py", *(root / "models").rglob("*.py")]
        else:
            paths = root.rglob("*.py")
        for path in sorted(paths):
            violations.extend(import_violations(path, src))
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize(
    "module,statement,forbidden",
    [
        (
            "harness_api/models/goals.py",
            "from fastapi import Depends",
            "fastapi.Depends",
        ),
        (
            "harness_operator/commands/get.py",
            "import harness_api.models.accounts as accounts",
            "harness_api.models.accounts",
        ),
        (
            "harness_operator/commands/get.py",
            "import harness_api as api\napi.database.WorkspaceDatabase",
            "harness_api",
        ),
        ("harness_mcp/server.py", "from harness_api import *", "harness_api.*"),
        (
            "harness_mcp/server.py",
            "import harness_api.OperatorAPI",
            "harness_api.OperatorAPI",
        ),
        ("harness_mcp/server.py", "import sqlite3 as db", "sqlite3"),
        (
            "harness_operator/commands/get.py",
            "from harness_api import OperatorAPI",
            None,
        ),
    ],
)
def test_import_examples(tmp_path, module, statement, forbidden):
    path = tmp_path / module
    path.parent.mkdir(parents=True)
    path.write_text(f"# Example module\n{statement}\n", encoding="utf-8")
    expected = [] if forbidden is None else [f"{path}:2: forbidden import {forbidden}"]
    assert list(import_violations(path, tmp_path)) == expected
