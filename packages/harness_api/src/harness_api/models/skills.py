"""Versioned instructions and the catalog visible to this workspace owner."""

import re
import sqlite3
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
from typing import TypeGuard, cast

import yaml

from ..database import ADMIN_USER_ID, WorkspaceDatabase
from .activity import CallReference, SkillReference


class SkillSummary(SkillReference):
    name: str
    description: str


class SkillRevision(SkillSummary):
    manifest: str
    instructions: str
    source_path: str
    commit_sha: str
    content_hash: str


@dataclass(frozen=True)
class SkillSource:
    path: str
    manifest: str
    instructions: str


@dataclass(frozen=True)
class SkillCatalog:
    commit_sha: str
    sources: tuple[SkillSource, ...]


class SkillCatalogError(ValueError):
    pass


class SkillValidationError(ValueError):
    """Invalid skill ID or revision supplied to a catalog query."""


class SkillNotFoundError(LookupError):
    def __init__(self, skill_id: str, revision: int) -> None:
        super().__init__(f"Skill {skill_id!r} revision {revision} was not found.")


class _ManifestLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        fields = set()
        for key, _ in node.value:
            if isinstance(key, yaml.ScalarNode):
                if key.value in fields:
                    raise ValueError(f"duplicate manifest field {key.value!r}")
                fields.add(key.value)
        return super().construct_mapping(node, deep=deep)


def is_skill_id(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) is not None
    )


def _import_revision(
    db: sqlite3.Connection, source: SkillSource, commit_sha: str
) -> tuple[str, int]:
    path = PurePosixPath(source.path)
    if len(path.parts) != 2 or path.parts[0] != "skills" or ".." in path.parts:
        raise SkillCatalogError(f"Invalid skill source path: {source.path!r}.")
    try:
        manifest = yaml.load(source.manifest, Loader=_ManifestLoader)
    except (yaml.YAMLError, ValueError, OverflowError) as error:
        raise SkillCatalogError(f"{path}/operator.yaml: {error}") from error
    if not isinstance(manifest, dict):
        raise SkillCatalogError(f"{path}/operator.yaml requires a manifest mapping.")
    key, revision = manifest.get("id"), manifest.get("revision")
    if not is_skill_id(key):
        raise SkillCatalogError(f"{path}/operator.yaml requires a URL-safe skill ID.")
    if type(revision) is not int or not 0 < revision < 2**63:
        raise SkillCatalogError(
            f"{path}/operator.yaml requires a positive integer revision."
        )
    old = db.execute(
        """SELECT manifest, instructions FROM skill_revisions
           WHERE owner_user_id = ? AND skill_key = ? AND revision = ?""",
        (ADMIN_USER_ID, key, revision),
    ).fetchone()
    if old is not None:
        if (
            old["manifest"] != source.manifest
            or old["instructions"] != source.instructions
        ):
            raise SkillCatalogError(
                f"Skill {key!r} revision {revision} changed. Bump its revision."
            )
        return key, revision

    if manifest.get("kind") != "skill":
        raise SkillCatalogError(f"{path}/operator.yaml must declare kind: skill.")
    for field in ("name", "description", "author"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise SkillCatalogError(
                f"{path}/operator.yaml requires a nonblank {field}."
            )
    if not source.instructions.strip():
        raise SkillCatalogError(f"{path}/SKILL.md requires instructions.")
    manifest_bytes = source.manifest.encode("utf-8")
    digest = sha256(len(manifest_bytes).to_bytes(8, "big"))
    digest.update(manifest_bytes)
    digest.update(source.instructions.encode("utf-8"))
    db.execute(
        """INSERT INTO skill_revisions
           (owner_user_id, skill_key, revision, name, description, manifest,
            instructions, source_path, commit_sha, content_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ADMIN_USER_ID,
            key,
            revision,
            manifest["name"],
            manifest["description"],
            source.manifest,
            source.instructions,
            source.path,
            commit_sha,
            digest.hexdigest(),
        ),
    )
    return key, revision


def _revision_key(skill_id: str, revision: int) -> tuple[int, str, int]:
    if not is_skill_id(skill_id):
        raise SkillValidationError("A URL-safe skill ID is required.")
    if type(revision) is not int or not 0 < revision < 2**63:
        raise SkillValidationError("Skill revision must be a positive 64-bit integer.")
    return ADMIN_USER_ID, skill_id, revision


class SkillAPI(WorkspaceDatabase):
    def import_catalog(self, catalog: SkillCatalog) -> None:
        """Activate exactly this committed catalog, retaining every earlier revision."""
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", catalog.commit_sha):
            raise SkillCatalogError("A catalog requires a full Git commit SHA.")
        with self._write() as db:
            current = {
                row["skill_key"]: row["revision"]
                for row in db.execute(
                    "SELECT skill_key, revision FROM skill_revisions WHERE owner_user_id = ? AND discoverable = 1",
                    (ADMIN_USER_ID,),
                )
            }
            incoming = {}
            for source in catalog.sources:
                key, revision = _import_revision(db, source, catalog.commit_sha)
                if key in incoming:
                    raise SkillCatalogError(
                        f"Duplicate skill ID {key!r} in the catalog."
                    )
                incoming[key] = revision
            for key, revision in current.items() - incoming.items():
                db.execute(
                    "UPDATE skill_revisions SET discoverable = 0 WHERE owner_user_id = ? AND skill_key = ? AND revision = ?",
                    (ADMIN_USER_ID, key, revision),
                )
            for key, revision in incoming.items() - current.items():
                db.execute(
                    "UPDATE skill_revisions SET discoverable = 1 WHERE owner_user_id = ? AND skill_key = ? AND revision = ?",
                    (ADMIN_USER_ID, key, revision),
                )

    def list_skills(self) -> list[SkillSummary]:
        with self._connection("ro") as db:
            return [
                SkillSummary(**row)
                for row in db.execute(
                    """SELECT skill_key AS id, revision, name, description FROM skill_revisions
                   WHERE owner_user_id = ? AND discoverable = 1 ORDER BY skill_key""",
                    (ADMIN_USER_ID,),
                )
            ]

    def read_skill(self, skill_id: str, revision: int) -> SkillRevision:
        with self._connection("ro") as db:
            row = db.execute(
                """SELECT skill_key AS id, revision, name, description, manifest, instructions,
                          source_path, commit_sha, content_hash FROM skill_revisions
                   WHERE owner_user_id = ? AND skill_key = ? AND revision = ?""",
                _revision_key(skill_id, revision),
            ).fetchone()
            if row is None:
                raise SkillNotFoundError(skill_id, revision)
            return cast(SkillRevision, dict(row))

    def reading_calls(self, skill_id: str, revision: int) -> list[CallReference]:
        with self._connection("ro") as db:
            db.execute("BEGIN")
            snapshot = db.execute(
                """SELECT id FROM skill_revisions WHERE owner_user_id = ? AND skill_key = ? AND revision = ?""",
                _revision_key(skill_id, revision),
            ).fetchone()
            if snapshot is None:
                raise SkillNotFoundError(skill_id, revision)
            return [
                CallReference(**row)
                for row in db.execute(
                    """SELECT ref.run_id, ref.sequence FROM run_call_skills AS ref
                       JOIN run_calls AS call USING (run_id, sequence)
                       JOIN operator_runs AS run ON run.id = ref.run_id
                       WHERE ref.snapshot_id = ? AND run.owner_user_id = ?
                           AND call.tool = 'read_skill' AND call.outcome = 'returned'
                       ORDER BY ref.run_id, ref.sequence""",
                    (snapshot["id"], ADMIN_USER_ID),
                )
            ]
