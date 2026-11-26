"""Goal-scoped work, execution attempts and observations from their workers."""

import json
import sqlite3
from typing import TypedDict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..database import ADMIN_USER_ID, WorkspaceDatabase, utc_timestamp
from ..execution import ExecutionBackend, WorkloadSpec
from . import GoalConflictError, GoalValidationError
from .activity import CallReference, SkillReference
from .evidence import add_evidence

WORKER_EXECUTABLE = "/usr/local/bin/harness-worker"


class WorkGrant(TypedDict):
    id: int
    operator_id: int
    goal_id: int


class DelegatedWorkResult(TypedDict):
    goal_id: int
    revision: int
    work_item_id: int
    attempt_id: int
    run_id: int
    sequence: int


class ChessCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    fen: str = Field(min_length=1, max_length=160)
    move: str = Field(min_length=1, max_length=16)
    expected_legal: bool
    reason: str = Field(min_length=1, max_length=600)


class WorkFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cases: list[ChessCase] = Field(min_length=1, max_length=16)
    executed: bool


def active_grant(connection: sqlite3.Connection, grant_id: int) -> WorkGrant:
    row = connection.execute(
        """SELECT w.id,w.operator_id,w.goal_id FROM work_grants w
           JOIN operators o ON o.id=w.operator_id JOIN goals g ON g.id=w.goal_id
           WHERE w.id=? AND w.withdrawn_at IS NULL AND o.deleted_at IS NULL
           AND g.deleted_at IS NULL AND o.owner_user_id=g.owner_user_id AND g.owner_user_id=?""",
        (grant_id, ADMIN_USER_ID),
    ).fetchone()
    if row is None:
        raise GoalValidationError("Work grant is inactive or unavailable.")
    return WorkGrant(
        id=row["id"], operator_id=row["operator_id"], goal_id=row["goal_id"]
    )


def _revision_reason(connection, goal, revision):
    current = connection.execute(
        "SELECT max(revision) FROM goal_revisions WHERE goal_id=?", (goal,)
    ).fetchone()[0]
    if current != revision:
        return (
            f"Work targets revision {revision}. The current goal is revision {current}."
        )
    return None


def _work_call(connection, call, tool, goal_id=None, revision=None, work_item_id=None):
    row = connection.execute(
        """SELECT c.*,r.work_grant_id FROM run_calls c JOIN operator_runs r ON r.id=c.run_id
           WHERE c.run_id=:run_id AND c.sequence=:sequence AND r.owner_user_id=:owner
             AND r.outcome='unfinished' AND c.outcome='unfinished'""",
        dict(call, owner=ADMIN_USER_ID),
    ).fetchone()
    if row is None or (
        row["tool"],
        row["target_revision"],
        row["target_work_item_id"],
    ) != (tool, revision, work_item_id):
        raise GoalValidationError(
            "The open call must match the requested work operation."
        )
    grant = active_grant(connection, row["work_grant_id"])
    if goal_id is not None and (
        row["target_goal_id"] != goal_id or grant["goal_id"] != goal_id
    ):
        raise GoalValidationError("The grant does not cover this goal.")
    if connection.execute(
        "SELECT 1 FROM work_call_results WHERE run_id=:run_id AND sequence=:sequence",
        call,
    ).fetchone():
        raise GoalConflictError("This call already has a work result.")
    return grant


def _positive_id(value: int, label: str) -> None:
    if type(value) is not int or not 0 < value < 2**63:
        raise GoalValidationError(f"{label} must be a positive integer.")


def _request(values):
    return json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _previous(connection, grant_id, key, request):
    if not isinstance(key, str) or not key.strip() or len(key) > 256:
        raise GoalValidationError(
            "Supply a nonblank retry key of at most 256 characters."
        )
    row = connection.execute(
        "SELECT * FROM work_decisions WHERE grant_id=? AND retry_key=?", (grant_id, key)
    ).fetchone()
    if row and row["request"] != request:
        raise GoalConflictError("This retry key already identifies different work.")
    return row["attempt_id"] if row else None


def _new_attempt(connection, item, image, grant_id, key, request):
    attempt = connection.execute(
        """INSERT INTO work_attempts(work_item_id,execution_id,image,created_at)
        VALUES (?,?,?,?) RETURNING id""",
        (item, uuid4().hex, image, utc_timestamp()),
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO work_decisions VALUES (?,?,?,?)", (grant_id, key, request, attempt)
    )
    return attempt


def _link(connection, call, attempt, kind):
    connection.execute(
        """INSERT INTO work_call_results VALUES (:run_id,:sequence,:attempt,:kind)""",
        dict(call, attempt=attempt, kind=kind),
    )
    return dict(
        connection.execute(
            """SELECT i.goal_id,i.revision,i.id AS work_item_id,a.id AS attempt_id,
            c.run_id,c.sequence FROM work_attempts a JOIN work_items i ON i.id=a.work_item_id
            JOIN work_call_results c ON c.attempt_id=a.id AND c.kind='committed' WHERE a.id=?""",
            (attempt,),
        ).fetchone()
    )


def _skills(connection, item):
    return connection.execute(
        """SELECT s.skill_key AS id,s.revision,s.name,s.description,s.instructions,
            s.content_hash,s.commit_sha,s.source_path,s.manifest FROM work_skills w
            JOIN skill_revisions s ON s.id=w.snapshot_id WHERE w.work_item_id=? ORDER BY s.skill_key,s.revision""",
        (item,),
    ).fetchall()


def work_history(connection, goal_id):
    items = []
    for row in connection.execute(
        """SELECT i.*,g.operator_id FROM work_items i JOIN work_grants g ON g.id=i.grant_id
                            WHERE i.goal_id=? ORDER BY i.id""",
        (goal_id,),
    ):
        item = dict(row)
        item["skill_revisions"] = [
            {"id": skill["id"], "revision": skill["revision"]}
            for skill in _skills(connection, item["id"])
        ]
        item["attempts"] = []
        for attempt_row in connection.execute(
            """SELECT a.*,c.run_id,c.sequence FROM work_attempts a JOIN work_call_results c
                ON c.attempt_id=a.id AND c.kind='committed' WHERE work_item_id=? ORDER BY a.id""",
            (item["id"],),
        ):
            attempt = dict(attempt_row)
            attempt["committing_call"] = {
                "run_id": attempt.pop("run_id"),
                "sequence": attempt.pop("sequence"),
            }
            attempt["replacement_allocation_ids"] = json.loads(
                attempt.pop("replacements")
            )
            attempt["worker_calls"] = []
            for call_row in connection.execute(
                "SELECT * FROM worker_calls WHERE attempt_id=? ORDER BY id",
                (attempt_row["id"],),
            ):
                entry = dict(call_row)
                if entry["returned_skills"] is not None:
                    entry["returned_skills"] = json.loads(entry["returned_skills"])
                attempt["worker_calls"].append(entry)
            result = connection.execute(
                """SELECT r.call_id,r.evidence_id,e.recorded_at,e.payload FROM work_results r
                         JOIN goal_events e ON e.id=r.evidence_id WHERE r.attempt_id=?""",
                (attempt_row["id"],),
            ).fetchone()
            attempt["result"] = (
                None
                if result is None
                else {
                    "worker_call_id": result["call_id"],
                    "evidence_id": result["evidence_id"],
                    "recorded_at": result["recorded_at"],
                    "fixture": json.loads(json.loads(result["payload"])["evidence"]),
                }
            )
            item["attempts"].append(attempt)
        item["latest_attempt_id"] = item["attempts"][-1]["id"]
        item["declined_retries"] = [
            dict(call_row)
            for call_row in connection.execute(
                """SELECT run_id,sequence,work_reason AS reason
              FROM run_calls WHERE target_work_item_id=? AND work_reason IS NOT NULL ORDER BY started_at""",
                (item["id"],),
            )
        ]
        items.append(item)
    return items


class WorkAPI(WorkspaceDatabase):
    def configure_launcher(self, image: str, nomad_address: str, endpoint: str) -> None:
        WorkloadSpec(image, (WORKER_EXECUTABLE,))
        with self._write() as connection:
            existing = connection.execute(
                "SELECT image,nomad_address,endpoint FROM worker_configuration"
            ).fetchone()
            if existing and tuple(existing) != (image, nomad_address, endpoint):
                raise GoalConflictError(
                    "This workspace already has a different worker launcher."
                )
            connection.execute(
                "INSERT OR IGNORE INTO worker_configuration VALUES (1,?,?,?)",
                (image, nomad_address, endpoint),
            )

    def delegate_work(
        self,
        goal_id: int,
        expected_revision: int,
        brief: str,
        skill_revisions: list[SkillReference],
        retry_key: str,
        *,
        call: CallReference,
    ) -> DelegatedWorkResult:
        _positive_id(goal_id, "Goal ID")
        _positive_id(expected_revision, "Goal revision")
        if not isinstance(brief, str) or not brief.strip() or len(brief) > 8192:
            raise GoalValidationError("Supply a brief of up to 8192 characters.")
        if not isinstance(skill_revisions, list) or len(skill_revisions) > 32:
            raise GoalValidationError("Assign at most 32 skill revisions.")
        with self._write() as connection:
            grant = _work_call(
                connection, call, "delegate_work", goal_id, expected_revision
            )
            config = connection.execute(
                "SELECT image FROM worker_configuration WHERE id=1"
            ).fetchone()
            if config is None:
                raise GoalValidationError(
                    "Start the workspace worker service before delegating work."
                )
            image = config["image"]
            if reason := _revision_reason(connection, goal_id, expected_revision):
                raise GoalConflictError(reason)
            snapshots = []
            for reference in skill_revisions:
                if (
                    not isinstance(reference, dict)
                    or set(reference) != {"id", "revision"}
                    or not isinstance(reference["id"], str)
                    or type(reference["revision"]) is not int
                ):
                    raise GoalValidationError(
                        "Expected an exact skill ID and revision."
                    )
                row = connection.execute(
                    """SELECT id FROM skill_revisions WHERE owner_user_id=? AND skill_key=? AND revision=?""",
                    (ADMIN_USER_ID, reference["id"], reference["revision"]),
                ).fetchone()
                if row is None or row[0] in snapshots:
                    raise GoalValidationError("Choose distinct saved skill revisions.")
                snapshots.append(row[0])
            request = _request(
                ["delegate_work", goal_id, expected_revision, brief, sorted(snapshots)]
            )
            previous = _previous(connection, grant["id"], retry_key, request)
            if previous:
                return _link(connection, call, previous, "retrieved")
            item = connection.execute(
                "INSERT INTO work_items(grant_id,goal_id,revision,brief) VALUES (?,?,?,?) RETURNING id",
                (grant["id"], goal_id, expected_revision, brief),
            ).fetchone()[0]
            connection.executemany(
                "INSERT INTO work_skills VALUES (?,?)",
                [(item, skill) for skill in snapshots],
            )
            attempt = _new_attempt(
                connection, item, image, grant["id"], retry_key, request
            )
            return _link(connection, call, attempt, "committed")

    def retry_work(
        self,
        work_item_id: int,
        expected_latest_attempt_id: int,
        retry_key: str,
        *,
        call: CallReference,
    ) -> DelegatedWorkResult:
        _positive_id(work_item_id, "Work item ID")
        _positive_id(expected_latest_attempt_id, "Expected attempt ID")
        with self._write() as connection:
            grant = _work_call(
                connection, call, "retry_work", work_item_id=work_item_id
            )
            item = connection.execute(
                "SELECT * FROM work_items WHERE id=? AND grant_id=?",
                (work_item_id, grant["id"]),
            ).fetchone()
            if item is None:
                raise GoalValidationError("Work item is outside this grant.")
            request = _request(["retry_work", work_item_id, expected_latest_attempt_id])
            previous = _previous(connection, grant["id"], retry_key, request)
            if previous:
                return _link(connection, call, previous, "retrieved")
            reason = _revision_reason(connection, item["goal_id"], item["revision"])
            latest = connection.execute(
                "SELECT id,image FROM work_attempts WHERE work_item_id=? ORDER BY id DESC LIMIT 1",
                (work_item_id,),
            ).fetchone()
            if latest["id"] != expected_latest_attempt_id:
                reason = (
                    reason
                    or f"The latest attempt is {latest['id']}. Reread the work history."
                )
            if not reason:
                attempt = _new_attempt(
                    connection,
                    work_item_id,
                    latest["image"],
                    grant["id"],
                    retry_key,
                    request,
                )
                return _link(connection, call, attempt, "committed")
            connection.execute(
                "UPDATE run_calls SET work_reason=:reason WHERE run_id=:run_id AND sequence=:sequence",
                dict(call, reason=reason),
            )
        raise GoalConflictError(reason)

    def list_outstanding_attempt_ids(self) -> list[int]:
        with self._connection("ro") as connection:
            return [
                r[0]
                for r in connection.execute(
                    "SELECT id FROM work_attempts WHERE state IN ('pending','running','unknown') ORDER BY id"
                )
            ]

    def dispatch(self, attempt_id: int, backend: ExecutionBackend) -> None:
        """Claim once. Recovery after the claim only inspects the existing job."""
        with self._write() as connection:
            attempt_row = connection.execute(
                """SELECT a.*,i.grant_id,i.goal_id,i.revision FROM work_attempts a
                JOIN work_items i ON i.id=a.work_item_id WHERE a.id=?""",
                (attempt_id,),
            ).fetchone()
            if attempt_row is None:
                raise GoalValidationError("Unknown work attempt.")
            if attempt_row["state"] not in ("pending", "running", "unknown"):
                return
            first = attempt_row["claimed_at"] is None
            spec = WorkloadSpec(attempt_row["image"], (WORKER_EXECUTABLE,))
            if first:
                try:
                    active_grant(connection, attempt_row["grant_id"])
                    reason = _revision_reason(
                        connection, attempt_row["goal_id"], attempt_row["revision"]
                    )
                except GoalValidationError as error:
                    reason = str(error)
                if reason:
                    connection.execute(
                        "UPDATE work_attempts SET state='declined',reason=? WHERE id=?",
                        (reason, attempt_id),
                    )
                    return
                connection.execute(
                    "UPDATE work_attempts SET claimed_at=?,job_id=? WHERE id=?",
                    (
                        utc_timestamp(),
                        backend.handle(attempt_row["execution_id"]),
                        attempt_id,
                    ),
                )
        try:
            if first:
                backend.start(attempt_row["execution_id"], spec)
            status = backend.lookup(attempt_row["execution_id"], spec)
        except (OSError, RuntimeError, ValueError) as error:
            with self._write() as connection:
                connection.execute(
                    """UPDATE work_attempts SET state='unknown',reason=?
                        WHERE id=? AND state IN ('running','pending','unknown')""",
                    (str(error), attempt_id),
                )
            return
        with self._write() as connection:
            current = connection.execute(
                "SELECT allocation_id, state FROM work_attempts WHERE id=?",
                (attempt_id,),
            ).fetchone()
            if current["state"] not in ("pending", "running", "unknown"):
                return
            original = current["allocation_id"]
            if original and status.allocation_id and original != status.allocation_id:
                replacements = list(
                    dict.fromkeys(
                        [*status.replacement_allocation_ids, status.allocation_id]
                    )
                )
                connection.execute(
                    "UPDATE work_attempts SET state='unknown',reason='Conflicting allocation observed.',replacements=?,exit_code=NULL WHERE id=?",
                    (json.dumps(replacements), attempt_id),
                )
                return
            connection.execute(
                """UPDATE work_attempts SET state=?,reason=NULL,allocation_id=coalesce(allocation_id,?),
                  replacements=?,exit_code=? WHERE id=? AND state IN ('running','pending','unknown')
                  AND (allocation_id IS NULL OR ? IS NULL OR allocation_id=?)""",
                (
                    status.state,
                    status.allocation_id,
                    json.dumps(status.replacement_allocation_ids),
                    status.exit_code,
                    attempt_id,
                    status.allocation_id,
                    status.allocation_id,
                ),
            )

    def refresh_worker(self, job_id: str, backend: ExecutionBackend) -> None:
        with self._connection("ro") as connection:
            row = connection.execute(
                "SELECT id FROM work_attempts WHERE job_id=?", (job_id,)
            ).fetchone()
        if row is not None:
            self.dispatch(row["id"], backend)

    def can_read(self, job_id: str, allocation_id: str) -> bool:
        with self._connection("ro") as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                """SELECT i.grant_id FROM work_attempts a JOIN work_items i ON i.id=a.work_item_id
                WHERE a.job_id=? AND a.allocation_id=?""",
                (job_id, allocation_id),
            ).fetchone()
            if row is None:
                return False
            try:
                active_grant(connection, row[0])
            except GoalValidationError:
                return False
            return True

    def worker_call(
        self, job_id: str, allocation_id: str, tool: str, arguments: dict
    ) -> dict:
        """The transport supplies verified job and allocation claims, never tool arguments."""
        with self._write() as connection:
            row = connection.execute(
                """SELECT a.id AS attempt_id,a.allocation_id,a.replacements,i.* FROM work_attempts a
                JOIN work_items i ON i.id=a.work_item_id WHERE a.job_id=?""",
                (job_id,),
            ).fetchone()
            if row is None:
                raise GoalValidationError("Unknown worker job.")
            call_id = connection.execute(
                """INSERT INTO worker_calls(attempt_id,allocation_id,tool,recorded_at,outcome)
                            VALUES (?,?,?,?,'unfinished') RETURNING id""",
                (row["attempt_id"], allocation_id, tool, utc_timestamp()),
            ).fetchone()[0]
            try:
                active_grant(connection, row["grant_id"])
                if (
                    not allocation_id
                    or row["allocation_id"] != allocation_id
                    or allocation_id in json.loads(row["replacements"])
                ):
                    raise GoalValidationError(
                        "This is not the original allocation for this attempt."
                    )
                result = self._perform(connection, row, tool, arguments, call_id)
            except (GoalValidationError, GoalConflictError, ValidationError) as error:
                denied_error = (
                    GoalValidationError("Invalid worker result fixture.")
                    if isinstance(error, ValidationError)
                    else error
                )
                connection.execute(
                    "UPDATE worker_calls SET outcome='denied',reason=? WHERE id=?",
                    (str(denied_error), call_id),
                )
            else:
                connection.execute(
                    "UPDATE worker_calls SET outcome='returned' WHERE id=?", (call_id,)
                )
                return result
        raise denied_error

    @staticmethod
    def _perform(connection, row, tool, arguments, call_id):
        fields = {
            "get_work_brief": set(),
            "list_skills": set(),
            "read_skill": {"id", "revision"},
            "submit_work_result": {"fixture"},
        }
        if (
            tool not in fields
            or not isinstance(arguments, dict)
            or set(arguments) != fields[tool]
        ):
            raise GoalValidationError(
                "Unavailable worker tool or unexpected arguments."
            )
        if tool == "get_work_brief":
            goal = dict(
                connection.execute(
                    "SELECT * FROM goal_revisions WHERE goal_id=? AND revision=?",
                    (row["goal_id"], row["revision"]),
                ).fetchone()
            )
            return {
                "brief": row["brief"],
                "work_item_id": row["id"],
                "attempt_id": row["attempt_id"],
                "goal": goal,
            }
        if tool in ("list_skills", "read_skill"):
            assigned = _skills(connection, row["id"])
            if tool == "list_skills":
                result = {
                    "skills": [
                        {k: skill[k] for k in ("id", "revision", "name", "description")}
                        for skill in assigned
                    ]
                }
                refs = result["skills"]
            else:
                match = next(
                    (
                        skill
                        for skill in assigned
                        if skill["id"] == arguments["id"]
                        and type(arguments["revision"]) is int
                        and skill["revision"] == arguments["revision"]
                    ),
                    None,
                )
                if match is None:
                    raise GoalValidationError("This skill revision was not assigned.")
                result = dict(match)
                refs = [result]
            connection.execute(
                "UPDATE worker_calls SET returned_skills=? WHERE id=?",
                (
                    _request(
                        [{k: skill[k] for k in ("id", "revision")} for skill in refs]
                    ),
                    call_id,
                ),
            )
            return result
        fixture = WorkFixture.model_validate(arguments["fixture"]).model_dump()
        contents = _request(fixture)
        if len(contents.encode()) > 16384:
            raise GoalValidationError("Fixture exceeds 16384 bytes.")
        saved = connection.execute(
            """SELECT r.evidence_id,e.payload FROM work_results r JOIN goal_events e
              ON e.id=r.evidence_id WHERE r.attempt_id=?""",
            (row["attempt_id"],),
        ).fetchone()
        if saved:
            if json.loads(saved["payload"])["evidence"] != contents:
                raise GoalConflictError(
                    "This attempt already submitted a different result."
                )
            evidence_id = saved["evidence_id"]
        else:
            evidence = add_evidence(
                connection,
                row["goal_id"],
                row["revision"],
                None,
                {
                    "evidence_kind": "worker_result",
                    "evidence": contents,
                    "worker_attempt_id": row["attempt_id"],
                    "worker_allocation_id": row["allocation_id"],
                    "requesting_operator_id": active_grant(connection, row["grant_id"])[
                        "operator_id"
                    ],
                },
            )
            evidence_id = evidence["evidence_id"]
            connection.execute(
                "INSERT INTO work_results VALUES (?,?,?)",
                (row["attempt_id"], call_id, evidence_id),
            )
        connection.execute(
            "UPDATE worker_calls SET evidence_id=? WHERE id=?", (evidence_id, call_id)
        )
        return {
            "evidence_id": evidence_id,
            "attempt_id": row["attempt_id"],
            "revision": row["revision"],
        }
