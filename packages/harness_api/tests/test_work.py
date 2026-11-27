import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from hashlib import sha256

import pytest

from harness_api import (
    MAX_ARTIFACT_BYTES,
    GoalAPI,
    OperatorAPI,
    SkillAPI,
    SkillCatalog,
    SkillReference,
    SkillSource,
    UserAPI,
    WorkAPI,
    WorkAuthorizationError,
    WorkConflictError,
    WorkNotFoundError,
    WorkStorageError,
    WorkValidationError,
)


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / "workspace.db"
    goals = GoalAPI(path)
    goal = goals.create_goal("Create a deliverable", status="active")
    operator = OperatorAPI(path).register_operator("Builder")
    work = WorkAPI(path)
    item = work.create_work_item(goal["id"], 1, operator["id"], "Write a file.")
    attempt = work.create_attempt("first-attempt", item["id"])
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    work.set_scratch(attempt["id"], scratch)
    work.grant_attempt(attempt["id"], "first-credential")
    return path, goals, work, item, attempt, scratch


def test_first_successful_submission_survives_mutation_cleanup_and_reopen(workspace):
    path, goals, work, item, attempt, scratch = workspace
    content = b"Aalborg\nAarhus\nCopenhagen\nOdense\nRoskilde\n"
    (scratch / "cities.txt").write_bytes(content)
    saved = work.submit_work_result(attempt["id"], "first-credential", "cities.txt")
    assert saved["sha256"] == sha256(content).hexdigest()
    assert saved["size_bytes"] == len(content)
    assert saved["operator_id"] == item["operator_id"]
    assert saved["goal_revision"] == 1
    (scratch / "cities.txt").write_text("Changed after submission")
    assert (
        work.submit_work_result(attempt["id"], "first-credential", "cities.txt")
        == saved
    )
    shutil.rmtree(scratch)
    work.mark_scratch_cleaned(attempt["id"])
    reopened = WorkAPI(path)
    assert (
        reopened.submit_work_result(attempt["id"], "first-credential", "cities.txt")
        == saved
    )
    assert reopened.read_artifact_bytes(saved["id"]) == content
    assert reopened.list_artifacts(item["goal_id"]) == [saved]
    assert reopened.get_attempt(attempt["id"])["artifact_id"] == saved["id"]
    with pytest.raises(WorkConflictError, match="different path"):
        reopened.submit_work_result(attempt["id"], "first-credential", "other.txt")
    assert goals.get_goal(item["goal_id"])["status"] == "active"
    assert goals.get_goal(item["goal_id"])["revision"] == 1


def test_issue_credential_uses_private_file_and_preserves_existing_file(
    workspace, tmp_path
):
    path, _, work, _, attempt, _ = workspace
    output = tmp_path / "credential"
    grant = work.issue_attempt_credential(attempt["id"], output)
    credential = output.read_text()
    assert output.stat().st_mode & 0o777 == 0o600
    assert credential and credential not in str(grant)
    assert WorkAPI(path).resolve_attempt(credential)["id"] == attempt["id"]
    with pytest.raises(FileExistsError):
        work.issue_attempt_credential(attempt["id"], output)
    assert output.read_text() == credential
    assert work.authorize_attempt(attempt["id"], credential)["id"] == attempt["id"]


def test_failed_credential_grant_removes_file_and_preserves_prior_authority(
    workspace, tmp_path
):
    path, _, work, _, attempt, _ = workspace
    output = tmp_path / "credential"
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.execute(
            "CREATE TRIGGER fail_grant BEFORE INSERT ON work_attempt_grants BEGIN SELECT RAISE(ABORT, 'failed grant'); END"
        )
        with pytest.raises(WorkStorageError):
            work.issue_attempt_credential(attempt["id"], output)
    assert not output.exists()
    assert work.resolve_attempt("first-credential")["id"] == attempt["id"]
    assert work.list_worker_calls(attempt["id"]) == []


def test_every_worker_call_rechecks_grant_and_revision_even_saved_retries(workspace):
    _, goals, work, item, attempt, scratch = workspace
    (scratch / "result").write_text("original")
    artifact = work.submit_work_result(attempt["id"], "first-credential", "result")
    work.revoke_attempt_grant(attempt["id"])
    work.grant_attempt(attempt["id"], "replacement-credential")
    operations = [
        lambda token: work.authorize_attempt(attempt["id"], token),
        lambda token: work.get_work_brief(attempt["id"], token),
        lambda token: work.list_skills(attempt["id"], token),
        lambda token: work.read_skill(attempt["id"], token, "unassigned", 1),
        lambda token: work.submit_work_result(attempt["id"], token, "result"),
    ]
    for operation in operations:
        with pytest.raises(WorkAuthorizationError):
            operation("first-credential")
    assert (
        work.submit_work_result(attempt["id"], "replacement-credential", "result")
        == artifact
    )
    with pytest.raises(WorkConflictError, match="credential"):
        work.grant_attempt(attempt["id"], "first-credential")
    goals.update_goal(item["goal_id"], title="Revised goal")
    for operation in operations:
        with pytest.raises(WorkAuthorizationError, match="revision"):
            operation("replacement-credential")
    assert work.read_artifact_bytes(artifact["id"]) == b"original"
    assert any(c["outcome"] == "denied" for c in work.list_worker_calls(attempt["id"]))


def test_assignment_cross_attempt_and_unregistered_operator_do_not_authorize(workspace):
    path, _, work, item, attempt, _ = workspace
    second = work.create_attempt("second", item["id"])
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.execute(
            "INSERT INTO goal_assignments(goal_id,operator_id) VALUES (?,?)",
            (item["goal_id"], item["operator_id"]),
        )
    with pytest.raises(WorkAuthorizationError):
        work.get_work_brief(second["id"], "first-credential")
    with pytest.raises(WorkAuthorizationError):
        work.get_work_brief(attempt["id"], "")
    assert work.resolve_attempt("first-credential")["id"] == attempt["id"]
    OperatorAPI(path).unregister_operator(item["operator_id"])
    with pytest.raises(WorkAuthorizationError):
        work.get_work_brief(attempt["id"], "first-credential")


def test_exact_assigned_skill_revisions_and_brief_are_immutable(workspace):
    path, _, work, item, _, _ = workspace
    manifest = "kind: skill\nid: example\nrevision: 1\nname: Example\ndescription: Test\nauthor: Owner\n"
    skills = SkillAPI(path)
    skills.import_catalog(
        SkillCatalog("a" * 40, (SkillSource("skills/example", manifest, "first"),))
    )
    assigned = work.create_work_item(
        item["goal_id"],
        1,
        item["operator_id"],
        "Use exact instructions.",
        skills=[SkillReference(id="example", revision=1)],
    )
    skills.import_catalog(
        SkillCatalog(
            "b" * 40,
            (
                SkillSource(
                    "skills/example",
                    manifest.replace("revision: 1", "revision: 2"),
                    "second",
                ),
            ),
        )
    )
    work.create_attempt("skilled", assigned["id"])
    work.grant_attempt("skilled", "skill-token")
    assert work.list_skills("skilled", "skill-token") == [
        {"id": "example", "revision": 1, "name": "Example", "description": "Test"}
    ]
    assert (
        work.read_skill("skilled", "skill-token", "example", 1)["instructions"]
        == "first"
    )
    with pytest.raises(WorkAuthorizationError, match="assigned"):
        work.read_skill("skilled", "skill-token", "example", 2)
    brief = work.get_work_brief("skilled", "skill-token")
    assert brief["work_item"] == assigned
    assert brief["goal"]["revision"] == 1
    assert work.get_work_item(assigned["id"])["brief"] == "Use exact instructions."


def test_launch_identity_retry_and_changed_brief_preserve_prior_attempt(workspace):
    _, _, work, item, attempt, scratch = workspace
    assert work.create_attempt(attempt["id"], item["id"])["id"] == attempt["id"]
    assert work.list_attempts(item["id"]) == [work.get_attempt(attempt["id"])]
    changed = work.create_work_item(
        item["goal_id"], 1, item["operator_id"], "Changed brief"
    )
    with pytest.raises(WorkConflictError):
        work.create_attempt(attempt["id"], changed["id"])
    second = work.create_attempt("intentional-retry", item["id"])
    assert second["work_item_id"] == attempt["work_item_id"]
    launched = work.record_launch(attempt["id"], "container-123", "sha256:" + "c" * 64)
    assert (
        work.record_launch(attempt["id"], "container-123", "sha256:" + "c" * 64)
        == launched
    )
    with pytest.raises(WorkConflictError):
        work.record_launch(attempt["id"], "container-456", "sha256:" + "c" * 64)
    with pytest.raises(WorkConflictError):
        work.record_launch(attempt["id"], "container-123", "sha256:" + "d" * 64)
    exited = work.record_exit(attempt["id"], 0)
    assert exited["exit_code"] == 0 and exited["artifact_id"] is None
    assert work.record_exit(attempt["id"], 0) == exited
    with pytest.raises(WorkConflictError):
        work.record_exit(attempt["id"], 1)
    work.mark_scratch_cleaned(attempt["id"])
    assert work.set_scratch(attempt["id"], scratch)["scratch_cleaned_at"] is not None
    with pytest.raises(WorkConflictError):
        work.set_scratch(attempt["id"], scratch / "different")


@pytest.mark.parametrize(
    "operation", ["create_attempt", "grant_attempt", "record_launch"]
)
@pytest.mark.parametrize("invalid_binding", ["revision", "operator"])
def test_owner_work_operations_preserve_authorization_errors_without_writes(
    workspace, operation, invalid_binding
):
    path, goals, work, item, attempt, _ = workspace
    before = work.list_attempts(item["id"])
    if invalid_binding == "revision":
        goals.update_goal(item["goal_id"], title="Revised goal")
    else:
        OperatorAPI(path).unregister_operator(item["operator_id"])
    operations = {
        "create_attempt": lambda: work.create_attempt("fresh-attempt", item["id"]),
        "grant_attempt": lambda: work.grant_attempt(attempt["id"], "new-credential"),
        "record_launch": lambda: work.record_launch(
            attempt["id"], "container-123", "sha256:" + "a" * 64
        ),
    }
    with pytest.raises(WorkAuthorizationError, match=invalid_binding):
        operations[operation]()
    assert work.list_attempts(item["id"]) == before


@pytest.mark.parametrize(
    "relative",
    ["../outside", "/etc/passwd", "a/../../outside", "", ".", "dir/../result"],
)
def test_escaping_or_ambiguous_paths_are_denied_without_a_result(workspace, relative):
    _, _, work, _, attempt, _ = workspace
    with pytest.raises(WorkValidationError):
        work.submit_work_result(attempt["id"], "first-credential", relative)
    assert work.get_attempt(attempt["id"])["artifact_id"] is None


def test_symlink_components_directories_and_missing_files_are_rejected(
    workspace, tmp_path
):
    _, _, work, _, attempt, scratch = workspace
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("private")
    (scratch / "link").symlink_to(outside, target_is_directory=True)
    (scratch / "file-link").symlink_to(outside / "secret")
    (scratch / "directory").mkdir()
    for relative in ("link/secret", "file-link", "directory", "missing"):
        with pytest.raises(WorkValidationError):
            work.submit_work_result(attempt["id"], "first-credential", relative)
    assert work.get_attempt(attempt["id"])["artifact_id"] is None


def test_submission_atomicity_rolls_back_artifact_and_keeps_failure_audit(workspace):
    path, _, work, item, attempt, scratch = workspace
    (scratch / "result").write_text("result")
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.executescript("""
            CREATE TRIGGER fail_artifact_link BEFORE UPDATE OF artifact_id ON work_attempts
            BEGIN SELECT RAISE(ABORT, 'failed link'); END;
        """)
        with pytest.raises(WorkStorageError):
            work.submit_work_result(attempt["id"], "first-credential", "result")
        assert db.execute("SELECT count(*) FROM work_artifacts").fetchone() == (0,)
        db.execute("DROP TRIGGER fail_artifact_link")
    assert work.get_attempt(attempt["id"])["artifact_id"] is None
    assert work.list_worker_calls(attempt["id"])[-1]["outcome"] == "failed"
    saved = work.submit_work_result(attempt["id"], "first-credential", "result")
    assert work.list_artifacts(item["goal_id"]) == [saved]


def test_owner_scope_current_revision_and_workspace_input_are_validated(workspace):
    path, goals, work, item, _, _ = workspace
    other = UserAPI(path).create_user("other")
    foreign = OperatorAPI(path).register_operator("Foreign", other["id"])
    with pytest.raises(WorkValidationError, match="operator"):
        work.create_work_item(item["goal_id"], 1, foreign["id"], "Brief")
    with pytest.raises(WorkConflictError, match="revision"):
        work.create_work_item(item["goal_id"], 2, item["operator_id"], "Brief")
    with pytest.raises(WorkValidationError, match="SHA"):
        work.create_work_item(
            item["goal_id"], 1, item["operator_id"], "Brief", source_path="."
        )
    with pytest.raises(WorkValidationError, match="source"):
        work.create_work_item(
            item["goal_id"], 1, item["operator_id"], "Brief", base_sha="a" * 40
        )
    with pytest.raises(WorkNotFoundError):
        work.list_artifacts(999)
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.execute(
            "UPDATE goals SET owner_user_id = ? WHERE id = ?",
            (other["id"], item["goal_id"]),
        )
    with pytest.raises(WorkAuthorizationError):
        work.get_work_brief("first-attempt", "first-credential")
    with pytest.raises(WorkNotFoundError):
        work.list_artifacts(item["goal_id"])
    assert goals.list_goals() == []


def test_known_denials_are_audited_without_credential_values(workspace):
    path, _, work, _, attempt, _ = workspace
    with pytest.raises(WorkAuthorizationError):
        work.get_work_brief(attempt["id"], "incorrect-secret")
    work.revoke_attempt_grant(attempt["id"])
    with pytest.raises(WorkAuthorizationError):
        work.resolve_attempt("first-credential")
    calls = work.list_worker_calls(attempt["id"])
    assert [c["outcome"] for c in calls] == ["denied", "denied"]
    with closing(sqlite3.connect(path)) as db:
        dump = "\n".join(db.iterdump())
    for credential in ("first-credential", "incorrect-secret"):
        assert credential not in dump


def test_large_files_and_cleaned_workspaces_cannot_create_new_results(workspace):
    _, _, work, _, attempt, scratch = workspace
    with (scratch / "oversized").open("wb") as file:
        file.truncate(MAX_ARTIFACT_BYTES + 1)
    with pytest.raises(WorkValidationError, match="size limit"):
        work.submit_work_result(attempt["id"], "first-credential", "oversized")
    work.mark_scratch_cleaned(attempt["id"])
    (scratch / "result").write_text("Cannot resurrect a cleaned attempt")
    with pytest.raises(WorkValidationError, match="cleaned"):
        work.submit_work_result(attempt["id"], "first-credential", "result")
    assert work.get_attempt(attempt["id"])["artifact_id"] is None


def test_concurrent_submission_returns_one_immutable_artifact(workspace):
    _, _, work, item, attempt, scratch = workspace
    (scratch / "result").write_bytes(b"one result")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                work.submit_work_result, attempt["id"], "first-credential", "result"
            )
            for _ in range(2)
        ]
        first, second = [future.result() for future in futures]
    assert first == second
    assert work.list_artifacts(item["goal_id"]) == [first]
    assert [call["artifact_id"] for call in work.list_worker_calls(attempt["id"])] == [
        first["id"],
        first["id"],
    ]


def test_attempts_cannot_share_registered_scratch_directories(workspace):
    _, _, work, item, _, scratch = workspace
    work.create_attempt("another", item["id"])
    with pytest.raises(WorkConflictError, match="shared"):
        work.set_scratch("another", scratch)


@pytest.mark.parametrize("child_first", [False, True])
def test_scratch_bindings_reject_ancestors_and_descendants(
    workspace, tmp_path, child_first
):
    _, _, work, item, _, _ = workspace
    parent = tmp_path / "separate"
    child = parent / "child"
    child.mkdir(parents=True)
    first, second = (child, parent) if child_first else (parent, child)
    work.create_attempt("first-binding", item["id"])
    work.create_attempt("second-binding", item["id"])
    bound = work.set_scratch("first-binding", first)
    before = work.list_attempts(item["id"])
    with pytest.raises(WorkConflictError, match="overlap"):
        work.set_scratch("second-binding", second)
    assert work.list_attempts(item["id"]) == before
    assert work.set_scratch("first-binding", first) == bound
    sibling = tmp_path / "separate-sibling"
    sibling.mkdir()
    assert work.set_scratch("second-binding", sibling)["scratch_path"] == str(sibling)


def test_scratch_binding_resolves_symlink_aliases(workspace, tmp_path):
    _, _, work, item, _, scratch = workspace
    alias = tmp_path / "alias"
    alias.symlink_to(scratch, target_is_directory=True)
    work.create_attempt("aliased", item["id"])
    with pytest.raises(WorkConflictError, match="shared|overlap"):
        work.set_scratch("aliased", alias)
    assert work.get_attempt("aliased")["scratch_path"] is None


def test_concurrent_overlapping_scratch_bindings_save_only_one(workspace, tmp_path):
    _, _, work, item, _, _ = workspace
    parent = tmp_path / "concurrent"
    child = parent / "child"
    child.mkdir(parents=True)
    work.create_attempt("parent-binding", item["id"])
    work.create_attempt("child-binding", item["id"])

    def bind(attempt_id, directory):
        try:
            return work.set_scratch(attempt_id, directory)
        except WorkConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(bind, "parent-binding", parent),
            pool.submit(bind, "child-binding", child),
        ]
        results = [future.result() for future in futures]
    assert sum(result is not None for result in results) == 1
    attempts = [work.get_attempt(key) for key in ("parent-binding", "child-binding")]
    assert sum(attempt["scratch_path"] is not None for attempt in attempts) == 1


def test_worker_result_and_process_outcome_are_independent(workspace):
    path, goals, work, item, attempt, scratch = workspace
    (scratch / "result").write_bytes(b"recoverable partial work")
    saved = work.submit_work_result(attempt["id"], "first-credential", "result")
    work.record_launch(attempt["id"], "failed-container", "sha256:" + "e" * 64)
    exited = work.record_exit(attempt["id"], 1)
    assert exited["exit_code"] == 1 and exited["artifact_id"] == saved["id"]
    OperatorAPI(path).unregister_operator(item["operator_id"])
    assert work.get_artifact(saved["id"]) == saved
    assert work.read_artifact_bytes(saved["id"]) == b"recoverable partial work"
    assert goals.get_goal(item["goal_id"])["status"] == "active"


def test_invalid_worker_arguments_are_denied_and_audited(workspace):
    _, _, work, _, attempt, _ = workspace
    with pytest.raises(WorkValidationError):
        work.read_skill(attempt["id"], "first-credential", object(), 1)
    with pytest.raises(WorkValidationError):
        work.submit_work_result(attempt["id"], "first-credential", object())
    assert [call["outcome"] for call in work.list_worker_calls(attempt["id"])] == [
        "denied",
        "denied",
    ]
