"""Resolve supported operator outcomes to the harness's prompt, workspace scope, and verifier."""

from harness.evidence import ACTIVE
from harness.hello_file import ORIGINAL_PROMPT, OUTCOME, FileOutcome, legacy_verdict

type TaskInput = FileOutcome | str | None


def resolve_task(task: TaskInput | dict) -> FileOutcome:
    if isinstance(task, str):
        if task not in (OUTCOME, ORIGINAL_PROMPT):
            raise ValueError("Submit a hello-file outcome with path and content")
        return FileOutcome()
    return FileOutcome.model_validate(task) if task is not None else FileOutcome()


def recorded_task(record: dict) -> FileOutcome:
    # All legacy runs used the same verifier, including earlier revisions of the prompt.
    return resolve_task(record.get("outcome"))


def legacy_statuses(record: dict) -> dict:
    """Interpret the single-fixture trace format used before the two status fields."""
    status = record["status"]
    if record.get("timed_out"):
        execution = "timed out"
    elif record.get("exit_code") is not None:
        execution = "succeeded" if record["exit_code"] == 0 else "failed"
    else:
        execution = status if status in ACTIVE else "unknown"
    details = record.get("verification")
    verification = "pending" if status in ACTIVE else "not run"
    if details:
        verification = legacy_verdict(details)
    return {"execution_status": execution, "verification_status": verification}
