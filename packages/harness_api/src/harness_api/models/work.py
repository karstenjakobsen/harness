"""Immutable assignments, one-shot attempts and authenticated artifact handoff."""

import json
import os
import re
import secrets
import sqlite3
import stat
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal, NotRequired, TypedDict, cast

from ..database import (
    ADMIN_USER_ID,
    WorkspaceDatabase,
    WorkspaceStorageError,
    utc_timestamp,
)
from .activity import (
    CallReference,
    SkillReference,
)
from .goals import Goal, GoalAPI
from .skills import SkillRevision, SkillSummary, is_skill_id
from .work_delegation import WorkDelegationGrant, active_delegation_grant

MAX_ARTIFACT_BYTES = 16 * 1024 * 1024

# A delegated worker chooses from the owner's current catalog. Explicit owner
# assignments retain their pinned revisions, including historical revisions.
WORKER_SKILL_SCOPE = """
FROM skill_revisions AS snapshot
LEFT JOIN work_item_skills AS assigned
    ON assigned.snapshot_id = snapshot.id AND assigned.work_item_id = :work_item_id
WHERE snapshot.owner_user_id = :owner AND (
    assigned.work_item_id IS NOT NULL OR (
        snapshot.discoverable = 1 AND EXISTS (
            SELECT 1 FROM work_delegations WHERE work_item_id = :work_item_id
        )
    )
)
"""


class WorkspaceInput(TypedDict):
    """Requested input only; accepting it authorizes no repository access."""

    source_path: str | None
    base_sha: str | None


class WorkItem(TypedDict):
    id: int
    owner_user_id: int
    goal_id: int
    goal_revision: int
    operator_id: int
    brief: str
    skills: list[SkillReference]
    source_path: str | None
    base_sha: str | None
    created_at: str
    delegation_grant_id: NotRequired[int]
    committing_call: NotRequired[CallReference]


class WorkAttempt(TypedDict):
    id: str
    work_item_id: int
    created_at: str
    scratch_path: str | None
    scratch_cleaned_at: str | None
    container_id: str | None
    image_digest: str | None
    launched_at: str | None
    exit_code: int | None
    exited_at: str | None
    artifact_id: int | None
    grant_id: int | None


class AttemptGrant(TypedDict):
    id: int
    attempt_id: str
    granted_at: str
    revoked_at: str | None


class WorkArtifact(TypedDict):
    id: int
    attempt_id: str
    work_item_id: int
    goal_id: int
    goal_revision: int
    operator_id: int
    grant_id: int
    relative_path: str
    sha256: str
    size_bytes: int
    base_sha: str | None
    created_at: str


class WorkBrief(TypedDict):
    attempt_id: str
    work_item: WorkItem
    goal: Goal


class WorkerCall(TypedDict):
    id: int
    attempt_id: str
    grant_id: int | None
    tool: str
    outcome: Literal["returned", "denied", "failed"]
    started_at: str
    finished_at: str
    arguments: dict
    artifact_id: int | None
    error: str | None


class WorkAttemptDetails(TypedDict):
    attempt: WorkAttempt
    work_item: WorkItem
    calls: list[WorkerCall]
    artifact: WorkArtifact | None
    trace_path: None


class WorkValidationError(ValueError):
    """A work operation received invalid input."""


class WorkNotFoundError(LookupError):
    """The requested owner-scoped work record is missing."""


class WorkConflictError(RuntimeError):
    """An immutable identity or saved outcome conflicts with the request."""


class WorkAuthorizationError(RuntimeError):
    """The exact grant or credential does not authorize this operation."""


class WorkStorageError(WorkspaceStorageError):
    pass


def _positive(value: int, label: str) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise WorkValidationError(f"{label} must be a positive 64-bit integer.")
    return value


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise WorkValidationError(f"{label} must contain text.")
    return value.strip()


def _workspace_input(
    source_path: Path | str | None, base_sha: str | None
) -> WorkspaceInput:
    if source_path is None and base_sha is not None:
        raise WorkValidationError("A base SHA requires a source path.")
    if source_path is not None:
        if not isinstance(source_path, (str, Path)) or not str(source_path).strip():
            raise WorkValidationError("A source path is required.")
        if (
            not isinstance(base_sha, str)
            or re.fullmatch(r"[0-9a-f]{40}", base_sha) is None
        ):
            raise WorkValidationError(
                "A source checkout requires a full Git commit SHA."
            )
        source_path = os.path.abspath(source_path)
    return WorkspaceInput(source_path=source_path, base_sha=base_sha)


def _attempt_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value
    ):
        raise WorkValidationError("Attempt ID must be 1–128 URL-safe characters.")
    return value


def _credential_hash(credential: str) -> str:
    if not isinstance(credential, str) or not credential or len(credential) > 4096:
        raise WorkAuthorizationError("A valid attempt credential is required.")
    return sha256(credential.encode("utf-8")).hexdigest()


def _relative_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4096
        or "\x00" in value
        or "\\" in value
    ):
        raise WorkValidationError("A relative workspace file path is required.")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or path.as_posix() != value
    ):
        raise WorkValidationError("A canonical path inside the workspace is required.")
    return value


def _read_workspace_file(root: str | None, relative_path: str) -> bytes:
    """Anchor every component to an open directory; never follow worker symlinks."""
    if root is None:
        raise WorkValidationError("The attempt has no registered workspace.")
    descriptors: list[int] = []
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(directory)
        parts = PurePosixPath(relative_path).parts
        for component in parts[:-1]:
            directory = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory,
            )
            descriptors.append(directory)
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        descriptors.append(descriptor)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise WorkValidationError("The submitted path must be a regular file.")
        if info.st_size > MAX_ARTIFACT_BYTES:
            raise WorkValidationError(
                "The submitted file exceeds the artifact size limit."
            )
        chunks: list[bytes] = []
        remaining = MAX_ARTIFACT_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > MAX_ARTIFACT_BYTES:
            raise WorkValidationError(
                "The submitted file exceeds the artifact size limit."
            )
        return content
    except OSError as error:
        raise WorkValidationError(
            "The submitted file is unavailable or unsafe."
        ) from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


ATTEMPT_SELECT = """
SELECT attempt.*, (SELECT id FROM work_attempt_grants
    WHERE attempt_id = attempt.id AND revoked_at IS NULL) AS grant_id
FROM work_attempts AS attempt JOIN work_items AS item ON item.id = attempt.work_item_id
WHERE item.owner_user_id = :owner
"""

ARTIFACT_SELECT = """
SELECT artifact.id, attempt.attempt_key AS attempt_id, artifact.work_item_id, item.goal_id,
       item.goal_revision, item.operator_id, artifact.grant_id, artifact.relative_path,
       artifact.sha256, artifact.size_bytes, item.base_sha, artifact.created_at
FROM work_artifacts AS artifact JOIN work_items AS item ON item.id = artifact.work_item_id
JOIN work_attempts AS attempt ON attempt.id = artifact.attempt_id
JOIN goals AS goal ON goal.id = item.goal_id
WHERE item.owner_user_id = :owner AND goal.owner_user_id = :owner AND goal.deleted_at IS NULL
"""


@dataclass
class _WorkerOperation:
    db: sqlite3.Connection
    attempt: WorkAttempt
    grant_id: int
    artifact_id: int | None = None
    outcome: Literal["returned", "denied", "failed"] = "returned"
    error: str | None = None


class WorkAPI(WorkspaceDatabase):
    """Owner-scoped work management and credential-scoped worker operations.

    Worker methods require both the session's attempt ID and its exact credential.
    Each call checks live authority inside its transaction, including saved retries.
    Credentials are represented only by their SHA-256 digest in persistent storage.
    """

    storage_error = WorkStorageError

    @property
    def database_path(self) -> Path:
        """The selected workspace database, shared by its trusted adapters."""
        return self._path

    def _item(self, db: sqlite3.Connection, work_item_id: int) -> WorkItem:
        row = db.execute(
            """SELECT item.* FROM work_items AS item JOIN goals AS goal ON goal.id = item.goal_id
               WHERE item.id = ? AND item.owner_user_id = ? AND goal.owner_user_id = ?
                 AND (goal.deleted_at IS NULL OR EXISTS (
                     SELECT 1 FROM work_delegations WHERE work_item_id = item.id))""",
            (_positive(work_item_id, "Work item ID"), ADMIN_USER_ID, ADMIN_USER_ID),
        ).fetchone()
        if row is None:
            raise WorkNotFoundError("Work item was not found.")
        item = dict(row)
        item["skills"] = [
            SkillReference(id=skill["skill_key"], revision=skill["revision"])
            for skill in db.execute(
                """SELECT snapshot.skill_key, snapshot.revision FROM work_item_skills AS assigned
                   JOIN skill_revisions AS snapshot ON snapshot.id = assigned.snapshot_id
                   WHERE assigned.work_item_id = ? ORDER BY assigned.position""",
                (work_item_id,),
            )
        ]
        delegation = db.execute(
            """SELECT delegation.grant_id, call.run_id, call.sequence
               FROM work_delegations AS delegation JOIN run_call_work_items AS call
                 ON call.work_item_id = delegation.work_item_id AND call.kind = 'committed'
               WHERE delegation.work_item_id = ?""",
            (work_item_id,),
        ).fetchone()
        if delegation is not None:
            item["delegation_grant_id"] = delegation["grant_id"]
            item["committing_call"] = CallReference(
                run_id=delegation["run_id"], sequence=delegation["sequence"]
            )
        return cast(WorkItem, item)

    def _attempt(self, db: sqlite3.Connection, attempt_id: str) -> WorkAttempt:
        row = db.execute(
            ATTEMPT_SELECT + " AND attempt.attempt_key = :id",
            {"owner": ADMIN_USER_ID, "id": _attempt_id(attempt_id)},
        ).fetchone()
        if row is None:
            raise WorkNotFoundError("Work attempt was not found.")
        self._item(db, row["work_item_id"])
        result = dict(row)
        result["id"] = result.pop("attempt_key")
        result["container_id"] = result.pop("container_key")
        return cast(WorkAttempt, result)

    @staticmethod
    def _attempt_row_id(db: sqlite3.Connection, attempt_id: str) -> int:
        row = db.execute(
            "SELECT id FROM work_attempts WHERE attempt_key = ?", (attempt_id,)
        ).fetchone()
        if row is None:
            raise WorkNotFoundError("Work attempt was not found.")
        return row["id"]

    def _valid_binding(self, db: sqlite3.Connection, item: WorkItem) -> None:
        row = db.execute(
            """SELECT goal.owner_user_id, goal.deleted_at, goal.status,
                      (SELECT max(revision) FROM goal_revisions WHERE goal_id = goal.id) AS revision,
                      operator.deleted_at AS operator_deleted,
                      operator.owner_user_id AS operator_owner
               FROM goals AS goal JOIN operators AS operator ON operator.id = ?
               WHERE goal.id = ?""",
            (item["operator_id"], item["goal_id"]),
        ).fetchone()
        if (
            row is None
            or row["deleted_at"] is not None
            or row["operator_deleted"] is not None
            or row["owner_user_id"] != ADMIN_USER_ID
            or row["operator_owner"] != ADMIN_USER_ID
        ):
            raise WorkAuthorizationError(
                "The assigned operator or goal is no longer authorized."
            )
        if row["revision"] != item["goal_revision"]:
            raise WorkAuthorizationError(
                "The assignment is bound to a stale goal revision."
            )
        if row["status"] not in ("draft", "active", "paused"):
            raise WorkAuthorizationError(
                "The assigned goal is no longer open for work."
            )

    def create_work_item(
        self,
        goal_id: int,
        expected_revision: int,
        operator_id: int,
        brief: str,
        *,
        skills: Sequence[SkillReference] = (),
        source_path: Path | str | None = None,
        base_sha: str | None = None,
    ) -> WorkItem:
        with self._write() as db:
            return self._create_work_item(
                db,
                goal_id,
                expected_revision,
                operator_id,
                brief,
                skills=skills,
                source_path=source_path,
                base_sha=base_sha,
            )

    @staticmethod
    def _validate_work_target(
        db: sqlite3.Connection, goal_id: int, expected_revision: int, operator_id: int
    ) -> None:
        goal = db.execute(
            """SELECT goal.status, max(revision.revision) AS revision
               FROM goals AS goal JOIN goal_revisions AS revision ON revision.goal_id = goal.id
               WHERE goal.id = ? AND goal.owner_user_id = ? AND goal.deleted_at IS NULL
               GROUP BY goal.id""",
            (goal_id, ADMIN_USER_ID),
        ).fetchone()
        if goal is None:
            raise WorkNotFoundError("Goal was not found.")
        if goal["revision"] != expected_revision:
            raise WorkConflictError("The work item requires the current goal revision.")
        if goal["status"] not in ("draft", "active", "paused"):
            raise WorkConflictError("The goal must be open for work.")
        operator = db.execute(
            "SELECT 1 FROM operators WHERE id = ? AND owner_user_id = ? AND deleted_at IS NULL",
            (operator_id, ADMIN_USER_ID),
        ).fetchone()
        if operator is None:
            raise WorkValidationError(
                "A registered operator owned by this workspace is required."
            )

    def _create_work_item(
        self,
        db: sqlite3.Connection,
        goal_id: int,
        expected_revision: int,
        operator_id: int,
        brief: str,
        *,
        skills: Sequence[SkillReference] = (),
        source_path: Path | str | None = None,
        base_sha: str | None = None,
    ) -> WorkItem:
        goal_id = _positive(goal_id, "Goal ID")
        expected_revision = _positive(expected_revision, "Goal revision")
        operator_id = _positive(operator_id, "Operator ID")
        brief = _text(brief, "Work brief")
        source = _workspace_input(source_path, base_sha)
        source_path, base_sha = source["source_path"], source["base_sha"]
        if isinstance(skills, (str, bytes)) or not isinstance(skills, Sequence):
            raise WorkValidationError(
                "Assigned skills must be exact revision references."
            )
        self._validate_work_target(db, goal_id, expected_revision, operator_id)
        snapshots = []
        for reference in skills:
            if (
                not isinstance(reference, dict)
                or set(reference) != {"id", "revision"}
                or not is_skill_id(reference.get("id"))
            ):
                raise WorkValidationError(
                    "Assigned skills require an ID and exact revision."
                )
            _positive(reference["revision"], "Skill revision")
            snapshot = db.execute(
                "SELECT id FROM skill_revisions WHERE owner_user_id = ? AND skill_key = ? AND revision = ?",
                (ADMIN_USER_ID, reference["id"], reference["revision"]),
            ).fetchone()
            if snapshot is None or snapshot["id"] in snapshots:
                raise WorkValidationError(
                    "Assigned skill revisions must exist and be unique."
                )
            snapshots.append(snapshot["id"])
        row = db.execute(
            """INSERT INTO work_items
               (owner_user_id,goal_id,goal_revision,operator_id,brief,source_path,base_sha,created_at)
               VALUES (?,?,?,?,?,?,?,?) RETURNING id""",
            (
                ADMIN_USER_ID,
                goal_id,
                expected_revision,
                operator_id,
                brief,
                source_path,
                base_sha,
                utc_timestamp(),
            ),
        ).fetchone()
        db.executemany(
            "INSERT INTO work_item_skills(work_item_id,position,snapshot_id) VALUES (?,?,?)",
            [
                (row["id"], position, snapshot)
                for position, snapshot in enumerate(snapshots)
            ],
        )
        return self._item(db, row["id"])

    def get_work_item(self, work_item_id: int) -> WorkItem:
        with self._connection("ro") as db:
            db.execute("BEGIN")
            return self._item(db, work_item_id)

    def grant_delegation(self, goal_id: int, operator_id: int) -> WorkDelegationGrant:
        """Trusted owner grants delegation of work for this exact goal."""
        goal_id = _positive(goal_id, "Goal ID")
        operator_id = _positive(operator_id, "Operator ID")
        with self._write() as db:
            self._owner_goal(db, goal_id)
            if (
                db.execute(
                    "SELECT 1 FROM operators WHERE id = ? AND owner_user_id = ? AND deleted_at IS NULL",
                    (operator_id, ADMIN_USER_ID),
                ).fetchone()
                is None
            ):
                raise WorkValidationError(
                    "A registered workspace operator is required."
                )
            row = db.execute(
                """INSERT INTO work_delegation_grants(goal_id,operator_id,granted_at)
                   VALUES (?,?,?) RETURNING *""",
                (goal_id, operator_id, utc_timestamp()),
            ).fetchone()
            return cast(WorkDelegationGrant, dict(row))

    @staticmethod
    def _delegation_grant(db: sqlite3.Connection, grant_id: int) -> WorkDelegationGrant:
        grant = active_delegation_grant(
            db, _positive(grant_id, "Delegation grant ID"), ADMIN_USER_ID
        )
        if grant is None:
            raise WorkAuthorizationError(
                "The delegation grant is inactive or unavailable."
            )
        return grant

    def get_delegation_grant(self, grant_id: int) -> WorkDelegationGrant:
        """Resolve the exact active grant for a trusted session binding."""
        with self._connection("ro") as db:
            return self._delegation_grant(db, grant_id)

    def withdraw_delegation(self, grant_id: int) -> WorkDelegationGrant:
        """Trusted owner withdraws authority, retaining historical grant identity."""
        with self._write() as db:
            self._delegation_grant(db, grant_id)
            row = db.execute(
                "UPDATE work_delegation_grants SET withdrawn_at = ? WHERE id = ? RETURNING *",
                (utc_timestamp(), grant_id),
            ).fetchone()
            return cast(WorkDelegationGrant, dict(row))

    def delegate_work(
        self,
        goal_id: int,
        expected_revision: int,
        brief: str,
        workspace_input: WorkspaceInput,
        retry_key: str,
        *,
        call: CallReference,
    ) -> WorkItem:
        """Save one assignment under the recorded call's exact live authority.

        Repository input is a request, never an authorization to access that path.
        Every replay rechecks the current revision and requires a new call.
        """
        goal_id = _positive(goal_id, "Goal ID")
        expected_revision = _positive(expected_revision, "Goal revision")
        brief = _text(brief, "Work brief")
        retry_key = _text(retry_key, "Retry key")
        if not isinstance(workspace_input, dict) or set(workspace_input) != {
            "source_path",
            "base_sha",
        }:
            raise WorkValidationError(
                "Workspace input requires source_path and base_sha."
            )
        source_path, base_sha = (
            workspace_input["source_path"],
            workspace_input["base_sha"],
        )
        if source_path is not None and (
            not isinstance(source_path, str)
            or "\x00" in source_path
            or not os.path.isabs(source_path)
        ):
            raise WorkValidationError("Requested source path must be absolute.")
        # Lexical normalization only; accepting an input grants no repository access.
        source = _workspace_input(source_path, base_sha)
        source_path, base_sha = source["source_path"], source["base_sha"]
        if not isinstance(call, dict) or set(call) != {"run_id", "sequence"}:
            raise WorkAuthorizationError("A recorded delegation call is required.")
        _positive(call["run_id"], "Run ID")
        _positive(call["sequence"], "Call sequence")
        fingerprint = sha256(
            json.dumps(
                [goal_id, expected_revision, brief, source_path, base_sha],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        with self._write() as db:
            attempt = db.execute(
                """SELECT call.*, run.delegation_grant_id, run.outcome AS run_outcome
                   FROM run_calls AS call JOIN operator_runs AS run ON run.id = call.run_id
                   WHERE call.run_id = ? AND call.sequence = ? AND run.owner_user_id = ?""",
                (call["run_id"], call["sequence"], ADMIN_USER_ID),
            ).fetchone()
            if (
                attempt is None
                or attempt["outcome"] != "unfinished"
                or attempt["run_outcome"] != "unfinished"
                or attempt["tool"] != "delegate_work"
                or attempt["target_goal_id"] != goal_id
                or attempt["target_revision"] != expected_revision
                or attempt["target_run_id"] is not None
                or attempt["delegation_grant_id"] is None
            ):
                raise WorkAuthorizationError(
                    "The recorded call does not authorize this delegation."
                )
            grant = self._delegation_grant(db, attempt["delegation_grant_id"])
            if grant["goal_id"] != goal_id:
                raise WorkAuthorizationError(
                    "The delegation grant does not cover this goal."
                )
            if (
                db.execute(
                    "SELECT 1 FROM run_call_work_items WHERE run_id = ? AND sequence = ?",
                    (call["run_id"], call["sequence"]),
                ).fetchone()
                is not None
            ):
                raise WorkConflictError(
                    "This call already saved a work result. Use a new call to retry."
                )
            prior = db.execute(
                "SELECT work_item_id, fingerprint FROM work_delegations WHERE grant_id = ? AND retry_key = ?",
                (grant["id"], retry_key),
            ).fetchone()
            if prior is not None:
                self._validate_work_target(
                    db, goal_id, expected_revision, grant["operator_id"]
                )
                if prior["fingerprint"] != fingerprint:
                    raise WorkConflictError(
                        "This retry key identifies different work inputs."
                    )
                item_id, kind = prior["work_item_id"], "retrieved"
            else:
                item = self._create_work_item(
                    db,
                    goal_id,
                    expected_revision,
                    grant["operator_id"],
                    brief,
                    source_path=source_path,
                    base_sha=base_sha,
                )
                item_id, kind = item["id"], "committed"
                db.execute(
                    "INSERT INTO work_delegations(work_item_id,grant_id,retry_key,fingerprint) VALUES (?,?,?,?)",
                    (item_id, grant["id"], retry_key, fingerprint),
                )
            db.execute(
                "INSERT INTO run_call_work_items(run_id,sequence,work_item_id,kind) VALUES (?,?,?,?)",
                (call["run_id"], call["sequence"], item_id, kind),
            )
            return self._item(db, item_id)

    def list_work_items(self, goal_id: int) -> list[WorkItem]:
        with self._connection("ro") as db:
            db.execute("BEGIN")
            self._owner_goal(db, goal_id)
            return [
                self._item(db, row["id"])
                for row in db.execute(
                    "SELECT id FROM work_items WHERE goal_id = ? AND owner_user_id = ? ORDER BY id",
                    (goal_id, ADMIN_USER_ID),
                )
            ]

    def create_attempt(self, attempt_id: str, work_item_id: int) -> WorkAttempt:
        attempt_id = _attempt_id(attempt_id)
        with self._write() as db:
            item = self._item(db, work_item_id)
            row = db.execute(
                "SELECT work_item_id FROM work_attempts WHERE attempt_key = ?",
                (attempt_id,),
            ).fetchone()
            if row is not None:
                if row["work_item_id"] != work_item_id:
                    raise WorkConflictError(
                        "Attempt ID is already bound to a different work item."
                    )
                return self._attempt(db, attempt_id)
            self._valid_binding(db, item)
            db.execute(
                "INSERT INTO work_attempts(attempt_key,work_item_id,created_at) VALUES (?,?,?)",
                (attempt_id, work_item_id, utc_timestamp()),
            )
            return self._attempt(db, attempt_id)

    def get_attempt(self, attempt_id: str) -> WorkAttempt:
        with self._connection("ro") as db:
            db.execute("BEGIN")
            return self._attempt(db, attempt_id)

    def list_attempts(self, work_item_id: int) -> list[WorkAttempt]:
        with self._connection("ro") as db:
            db.execute("BEGIN")
            self._item(db, work_item_id)
            return [
                self._attempt(db, row["attempt_key"])
                for row in db.execute(
                    "SELECT attempt_key FROM work_attempts WHERE work_item_id = ? ORDER BY created_at,id",
                    (work_item_id,),
                )
            ]

    def grant_attempt(self, attempt_id: str, credential: str) -> AttemptGrant:
        digest = _credential_hash(credential)
        with self._write() as db:
            attempt = self._attempt(db, attempt_id)
            self._valid_binding(db, self._item(db, attempt["work_item_id"]))
            row_id = self._attempt_row_id(db, attempt_id)
            prior = db.execute(
                "SELECT * FROM work_attempt_grants WHERE credential_hash = ?", (digest,)
            ).fetchone()
            if prior is not None:
                if prior["attempt_id"] == row_id and prior["revoked_at"] is None:
                    return self._grant(prior, attempt_id)
                raise WorkConflictError(
                    "The credential was already used; use a fresh credential."
                )
            now = utc_timestamp()
            db.execute(
                "UPDATE work_attempt_grants SET revoked_at = ? WHERE attempt_id = ? AND revoked_at IS NULL",
                (now, row_id),
            )
            row = db.execute(
                "INSERT INTO work_attempt_grants(attempt_id,credential_hash,granted_at) VALUES (?,?,?) RETURNING *",
                (row_id, digest, now),
            ).fetchone()
            return self._grant(row, attempt_id)

    def issue_attempt_credential(
        self, attempt_id: str, output: Path | str
    ) -> AttemptGrant:
        """Save a fresh credential privately before activating its grant.

        Existing files are preserved. A failed grant removes the newly created
        file and leaves the previous grant intact. After a lost response, the
        owner can use the file or issue a replacement into another new file.
        """
        path = Path(output)
        credential = secrets.token_urlsafe(32)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(credential)
                stream.flush()
                os.fsync(stream.fileno())
            return self.grant_attempt(attempt_id, credential)
        except BaseException:
            path.unlink()
            raise

    @staticmethod
    def _grant(row: sqlite3.Row, attempt_id: str) -> AttemptGrant:
        return AttemptGrant(
            id=row["id"],
            attempt_id=attempt_id,
            granted_at=row["granted_at"],
            revoked_at=row["revoked_at"],
        )

    def revoke_attempt_grant(self, attempt_id: str) -> AttemptGrant:
        with self._write() as db:
            self._attempt(db, attempt_id)
            row = db.execute(
                "UPDATE work_attempt_grants SET revoked_at = ? WHERE attempt_id = ? AND revoked_at IS NULL RETURNING *",
                (utc_timestamp(), self._attempt_row_id(db, attempt_id)),
            ).fetchone()
            if row is None:
                raise WorkConflictError("The attempt has no active grant.")
            return self._grant(row, attempt_id)

    def _authorize(
        self, db: sqlite3.Connection, attempt_id: str, credential: str
    ) -> tuple[WorkAttempt, int]:
        try:
            attempt = self._attempt(db, attempt_id)
        except (WorkNotFoundError, WorkValidationError) as error:
            raise WorkAuthorizationError("The attempt is not authorized.") from error
        grant = db.execute(
            "SELECT id FROM work_attempt_grants WHERE attempt_id = ? AND credential_hash = ? AND revoked_at IS NULL",
            (self._attempt_row_id(db, attempt_id), _credential_hash(credential)),
        ).fetchone()
        if grant is None:
            raise WorkAuthorizationError(
                "The attempt credential grant is invalid or withdrawn."
            )
        self._valid_binding(db, self._item(db, attempt["work_item_id"]))
        return attempt, grant["id"]

    def _audit(
        self,
        db: sqlite3.Connection,
        attempt_id: str,
        credential: str,
        tool: str,
        arguments: dict,
        started_at: str,
        outcome: str,
        error: str | None,
        artifact_id: int | None = None,
    ) -> None:
        if not isinstance(attempt_id, str):
            return
        known = db.execute(
            "SELECT id FROM work_attempts WHERE attempt_key = ?", (attempt_id,)
        ).fetchone()
        if known is None:
            return
        try:
            digest = _credential_hash(credential)
        except WorkAuthorizationError:
            digest = ""
        grant = db.execute(
            "SELECT id FROM work_attempt_grants WHERE attempt_id = ? AND credential_hash = ?",
            (known["id"], digest),
        ).fetchone()
        db.execute(
            """INSERT INTO worker_calls
               (attempt_id,grant_id,tool,started_at,finished_at,outcome,arguments,artifact_id,error)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                known["id"],
                None if grant is None else grant["id"],
                tool,
                started_at,
                utc_timestamp(),
                outcome,
                json.dumps(
                    {
                        key: value
                        if type(value) in (str, int, bool, type(None))
                        else None
                        for key, value in arguments.items()
                    },
                    sort_keys=True,
                ),
                artifact_id,
                error,
            ),
        )

    @contextmanager
    def _worker_call(
        self,
        attempt_id: str,
        credential: str,
        tool: str,
        arguments: dict | None = None,
    ) -> Generator[_WorkerOperation]:
        """Commit a safe audit even when the operation itself must roll back."""
        started = utc_timestamp()
        caught: Exception | None = None
        with self._write() as db:
            db.execute("SAVEPOINT worker_operation")
            try:
                attempt, grant_id = self._authorize(db, attempt_id, credential)
                operation = _WorkerOperation(db, attempt, grant_id)
                yield operation
            except (
                WorkAuthorizationError,
                WorkValidationError,
                WorkNotFoundError,
                WorkConflictError,
                WorkStorageError,
                sqlite3.Error,
                OSError,
            ) as error:
                db.execute("ROLLBACK TO worker_operation")
                db.execute("RELEASE worker_operation")
                denied = isinstance(
                    error,
                    (
                        WorkAuthorizationError,
                        WorkValidationError,
                        WorkNotFoundError,
                        WorkConflictError,
                    ),
                )
                self._audit(
                    db,
                    attempt_id,
                    credential,
                    tool,
                    arguments or {},
                    started,
                    "denied" if denied else "failed",
                    type(error).__name__,
                )
                caught = (
                    WorkStorageError() if isinstance(error, sqlite3.Error) else error
                )
            else:
                db.execute("RELEASE worker_operation")
                self._audit(
                    db,
                    attempt_id,
                    credential,
                    tool,
                    arguments or {},
                    started,
                    operation.outcome,
                    operation.error,
                    operation.artifact_id,
                )
        if caught is not None:
            raise caught

    def authorize_attempt(
        self, attempt_id: str, credential: str, *, tool: str = "authorize_attempt"
    ) -> WorkAttempt:
        with self._worker_call(attempt_id, credential, tool) as call:
            return call.attempt

    def resolve_attempt(self, credential: str) -> WorkAttempt:
        digest = _credential_hash(credential)
        with self._connection("ro") as db:
            row = db.execute(
                """SELECT attempt.attempt_key AS attempt_id FROM work_attempt_grants AS grant
                   JOIN work_attempts AS attempt ON attempt.id = grant.attempt_id
                   WHERE grant.credential_hash = ?""",
                (digest,),
            ).fetchone()
        if row is None:
            raise WorkAuthorizationError("The worker credential is unknown.")
        # Successful authentication is not a tool call; each dispatched operation
        # performs its own transactional authorization and audit.
        error: WorkAuthorizationError | None = None
        with self._write() as db:
            try:
                attempt, _ = self._authorize(db, row["attempt_id"], credential)
            except WorkAuthorizationError as denied:
                self._audit(
                    db,
                    row["attempt_id"],
                    credential,
                    "authenticate_worker",
                    {},
                    utc_timestamp(),
                    "denied",
                    "WorkAuthorizationError",
                )
                error = denied
        if error is not None:
            raise error
        return attempt

    def record_worker_failure(
        self, attempt_id: str, credential: str, tool: str
    ) -> None:
        with self._worker_call(attempt_id, credential, tool) as call:
            call.outcome = "denied"
            # Adapter errors are deliberately fixed: never store supplied payloads.
            call.error = "Invalid worker tool request."

    def get_work_brief(self, attempt_id: str, credential: str) -> WorkBrief:
        with self._worker_call(attempt_id, credential, "get_work_brief") as call:
            item = self._item(call.db, call.attempt["work_item_id"])
            return WorkBrief(
                attempt_id=attempt_id,
                work_item=item,
                goal=GoalAPI(self._path).get_goal(item["goal_id"]),
            )

    def list_skills(self, attempt_id: str, credential: str) -> list[SkillSummary]:
        with self._worker_call(attempt_id, credential, "list_skills") as call:
            return [
                SkillSummary(**row)
                for row in call.db.execute(
                    "SELECT snapshot.skill_key AS id,snapshot.revision,snapshot.name,snapshot.description "
                    + WORKER_SKILL_SCOPE
                    + " ORDER BY assigned.position,snapshot.skill_key,snapshot.revision",
                    {
                        "work_item_id": call.attempt["work_item_id"],
                        "owner": ADMIN_USER_ID,
                    },
                )
            ]

    def read_skill(
        self, attempt_id: str, credential: str, skill_id: str, revision: int
    ) -> SkillRevision:
        arguments = {"id": skill_id, "revision": revision}
        with self._worker_call(attempt_id, credential, "read_skill", arguments) as call:
            if not is_skill_id(skill_id):
                raise WorkValidationError("A valid skill ID is required.")
            _positive(revision, "Skill revision")
            row = call.db.execute(
                """SELECT snapshot.skill_key AS id,snapshot.revision,snapshot.name,snapshot.description,
                          snapshot.manifest,snapshot.instructions,snapshot.source_path,snapshot.commit_sha,snapshot.content_hash """
                + WORKER_SKILL_SCOPE
                + " AND snapshot.skill_key = :skill_id AND snapshot.revision = :revision",
                {
                    "work_item_id": call.attempt["work_item_id"],
                    "owner": ADMIN_USER_ID,
                    "skill_id": skill_id,
                    "revision": revision,
                },
            ).fetchone()
            if row is None:
                raise WorkAuthorizationError(
                    "Only assigned or permitted catalog skill revisions may be read."
                )
            return cast(SkillRevision, dict(row))

    def submit_work_result(
        self, attempt_id: str, credential: str, relative_path: str
    ) -> WorkArtifact:
        with self._worker_call(
            attempt_id,
            credential,
            "submit_work_result",
            {"relative_path": relative_path},
        ) as call:
            relative_path = _relative_path(relative_path)
            if call.attempt["artifact_id"] is not None:
                saved = self._artifact(call.db, call.attempt["artifact_id"])
                if saved["relative_path"] != relative_path:
                    raise WorkConflictError(
                        "The attempt already submitted a different path."
                    )
                call.artifact_id = saved["id"]
                return saved
            if call.attempt["scratch_cleaned_at"] is not None:
                raise WorkValidationError("The attempt workspace was already cleaned.")
            content = _read_workspace_file(call.attempt["scratch_path"], relative_path)
            row = call.db.execute(
                """INSERT INTO work_artifacts
                   (attempt_id,work_item_id,grant_id,relative_path,sha256,size_bytes,content,created_at)
                   VALUES (?,?,?,?,?,?,?,?) RETURNING id""",
                (
                    self._attempt_row_id(call.db, attempt_id),
                    call.attempt["work_item_id"],
                    call.grant_id,
                    relative_path,
                    sha256(content).hexdigest(),
                    len(content),
                    content,
                    utc_timestamp(),
                ),
            ).fetchone()
            call.db.execute(
                "UPDATE work_attempts SET artifact_id = ? WHERE attempt_key = ?",
                (row["id"], attempt_id),
            )
            call.artifact_id = row["id"]
            return self._artifact(call.db, row["id"])

    def _artifact(self, db: sqlite3.Connection, artifact_id: int) -> WorkArtifact:
        row = db.execute(
            ARTIFACT_SELECT + " AND artifact.id = :id",
            {"owner": ADMIN_USER_ID, "id": _positive(artifact_id, "Artifact ID")},
        ).fetchone()
        if row is None:
            raise WorkNotFoundError("Saved work artifact was not found.")
        return cast(WorkArtifact, dict(row))

    def get_artifact(self, artifact_id: int) -> WorkArtifact:
        with self._connection("ro") as db:
            return self._artifact(db, artifact_id)

    def read_artifact_bytes(self, artifact_id: int) -> bytes:
        with self._connection("ro") as db:
            db.execute("BEGIN")
            self._artifact(db, artifact_id)
            return bytes(
                db.execute(
                    "SELECT content FROM work_artifacts WHERE id = ?", (artifact_id,)
                ).fetchone()["content"]
            )

    @staticmethod
    def _owner_goal(db: sqlite3.Connection, goal_id: int) -> None:
        if (
            db.execute(
                "SELECT 1 FROM goals WHERE id = ? AND owner_user_id = ? AND deleted_at IS NULL",
                (_positive(goal_id, "Goal ID"), ADMIN_USER_ID),
            ).fetchone()
            is None
        ):
            raise WorkNotFoundError("Goal was not found.")

    def list_artifacts(self, goal_id: int) -> list[WorkArtifact]:
        with self._connection("ro") as db:
            db.execute("BEGIN")
            self._owner_goal(db, goal_id)
            return [
                cast(WorkArtifact, dict(row))
                for row in db.execute(
                    ARTIFACT_SELECT + " AND item.goal_id = :goal ORDER BY artifact.id",
                    {"owner": ADMIN_USER_ID, "goal": goal_id},
                )
            ]

    def get_attempt_details(self, attempt_id: str) -> WorkAttemptDetails:
        """Read an attempt and its handoff audit from one database snapshot."""
        with self._connection("ro") as db:
            db.execute("BEGIN")
            attempt = self._attempt(db, attempt_id)
            return WorkAttemptDetails(
                attempt=attempt,
                work_item=self._item(db, attempt["work_item_id"]),
                calls=self._worker_calls(db, attempt_id),
                artifact=(
                    self._artifact(db, attempt["artifact_id"])
                    if attempt["artifact_id"] is not None
                    else None
                ),
                trace_path=None,
            )

    def list_worker_calls(self, attempt_id: str) -> list[WorkerCall]:
        with self._connection("ro") as db:
            db.execute("BEGIN")
            self._attempt(db, attempt_id)
            return self._worker_calls(db, attempt_id)

    def _worker_calls(
        self, db: sqlite3.Connection, attempt_id: str
    ) -> list[WorkerCall]:
        calls = []
        for row in db.execute(
            "SELECT * FROM worker_calls WHERE attempt_id = ? ORDER BY id",
            (self._attempt_row_id(db, attempt_id),),
        ):
            call = dict(row)
            call["attempt_id"] = attempt_id
            call["arguments"] = json.loads(call["arguments"])
            calls.append(cast(WorkerCall, call))
        return calls

    def set_scratch(self, attempt_id: str, path: Path | str) -> WorkAttempt:
        if not isinstance(path, (str, Path)) or not str(path).strip():
            raise WorkValidationError("A scratch directory path is required.")
        absolute = Path(path).resolve()
        with self._write() as db:
            attempt = self._attempt(db, attempt_id)
            if (
                attempt["scratch_path"] is not None
                and Path(attempt["scratch_path"]).resolve() != absolute
            ):
                raise WorkConflictError(
                    "Attempt already has a different scratch directory."
                )
            for row in db.execute(
                "SELECT scratch_path FROM work_attempts WHERE scratch_path IS NOT NULL AND attempt_key != ?",
                (attempt_id,),
            ):
                registered = Path(row["scratch_path"]).resolve()
                if absolute.is_relative_to(registered) or registered.is_relative_to(
                    absolute
                ):
                    raise WorkConflictError(
                        "Scratch directories cannot be shared or overlap across attempts."
                    )
            if attempt["scratch_path"] is not None:
                return attempt
            db.execute(
                "UPDATE work_attempts SET scratch_path = ? WHERE attempt_key = ?",
                (str(absolute), attempt_id),
            )
            return self._attempt(db, attempt_id)

    def record_launch(
        self, attempt_id: str, container_id: str, image_digest: str
    ) -> WorkAttempt:
        container_id = _text(container_id, "Container ID")
        if (
            not isinstance(image_digest, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest) is None
        ):
            raise WorkValidationError("A pinned Docker image digest is required.")
        with self._write() as db:
            attempt = self._attempt(db, attempt_id)
            if attempt["container_id"] is not None:
                if (attempt["container_id"], attempt["image_digest"]) != (
                    container_id,
                    image_digest,
                ):
                    raise WorkConflictError(
                        "Attempt already has a different container or image."
                    )
                return attempt
            self._valid_binding(db, self._item(db, attempt["work_item_id"]))
            if attempt["scratch_cleaned_at"] is not None:
                raise WorkConflictError(
                    "A cleaned attempt cannot launch a new container."
                )
            existing = db.execute(
                "SELECT 1 FROM work_attempts WHERE container_key = ?", (container_id,)
            ).fetchone()
            if existing is not None:
                raise WorkConflictError(
                    "The container already belongs to another attempt."
                )
            db.execute(
                "UPDATE work_attempts SET container_key = ?,image_digest = ?,launched_at = ? WHERE attempt_key = ?",
                (container_id, image_digest, utc_timestamp(), attempt_id),
            )
            return self._attempt(db, attempt_id)

    def record_exit(self, attempt_id: str, exit_code: int) -> WorkAttempt:
        if type(exit_code) is not int or not 0 <= exit_code <= 255:
            raise WorkValidationError(
                "Container exit code must be an integer from 0 to 255."
            )
        with self._write() as db:
            attempt = self._attempt(db, attempt_id)
            if attempt["container_id"] is None:
                raise WorkConflictError("The attempt has not launched a container.")
            if attempt["exit_code"] is not None:
                if attempt["exit_code"] != exit_code:
                    raise WorkConflictError(
                        "The attempt already has a different exit code."
                    )
                return attempt
            db.execute(
                "UPDATE work_attempts SET exit_code = ?,exited_at = ? WHERE attempt_key = ?",
                (exit_code, utc_timestamp(), attempt_id),
            )
            return self._attempt(db, attempt_id)

    def mark_scratch_cleaned(self, attempt_id: str) -> WorkAttempt:
        with self._write() as db:
            attempt = self._attempt(db, attempt_id)
            if attempt["scratch_path"] is None:
                raise WorkConflictError("The attempt has no scratch directory.")
            if attempt["scratch_cleaned_at"] is None:
                db.execute(
                    "UPDATE work_attempts SET scratch_cleaned_at = ? WHERE attempt_key = ?",
                    (utc_timestamp(), attempt_id),
                )
            return self._attempt(db, attempt_id)
