import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from harness_api import (
    GoalAPI,
    GoalValidationError,
    SkillAPI,
    SkillCatalog,
    SkillCatalogError,
    SkillNotFoundError,
    SkillSource,
    SkillValidationError,
    UserAPI,
)
from harness_api.app import create_app

MANIFEST = "kind: skill\nid: example\nrevision: 1\nname: Example\ndescription: Guidance\nauthor: Test\n"


def test_owner_scoped_skill_references(tmp_path):
    path = tmp_path / "workspace.db"
    api = GoalAPI(path)
    source = SkillSource("skills/example", MANIFEST, "Owner's instructions")
    api.skills.import_catalog(SkillCatalog("a" * 40, (source,)))
    other = UserAPI(path).create_user("other")["id"]
    ref = {"id": "example", "revision": 1}
    run = api.start_run()
    attempt = api.start_tool_call(
        run["id"], "read_skill", target_skill_id="example", target_revision=1
    )

    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.execute("PRAGMA foreign_keys = ON")
        # Another owner's catalog contains revision 2 of the same skill.
        db.execute(
            """INSERT INTO skill_revisions
               (owner_user_id, skill_key, revision, name, description, manifest, instructions,
                source_path, commit_sha, content_hash, discoverable)
               SELECT ?, skill_key, 2, name, description, replace(manifest,'revision: 1','revision: 2'),
                      'Private instructions', source_path, commit_sha, content_hash, 1
               FROM skill_revisions WHERE owner_user_id = ?""",
            (other, run["owner_user_id"]),
        )

    # Mismatched or foreign references cannot finish an owner-visible read.
    with pytest.raises(GoalValidationError, match="match the requested"):
        api.finish_tool_call(
            attempt, "returned", returned_skills=[ref | {"revision": 2}]
        )
    api.finish_tool_call(attempt, "returned", returned_skills=[ref])
    foreign = api.start_tool_call(
        run["id"], "read_skill", target_skill_id="example", target_revision=2
    )
    with pytest.raises(GoalValidationError, match="must exist"):
        api.finish_tool_call(
            foreign, "returned", returned_skills=[ref | {"revision": 2}]
        )
    assert api.get_run(run["id"])["calls"][1]["outcome"] == "unfinished"

    with TestClient(create_app(path)) as http:
        assert [s["revision"] for s in http.get("/skills").json()] == [1]
        assert http.get("/skills/example/revisions/2").status_code == 404
        for suffix in ("", "/reads"):
            assert http.get(f"/skills/bad%20id/revisions/1{suffix}").status_code == 422
            assert http.get(f"/skills/example/revisions/0{suffix}").status_code == 422
        assert http.get("/skills/example/revisions/2/reads").status_code == 404
        assert http.get(
            "/skills/example/revisions/1/reads"
        ).raise_for_status().json() == [attempt]
        # A run transferred out of the workspace owner's scope is also excluded
        # from the reverse lookup, even with an existing revision reference.
        with closing(sqlite3.connect(path, autocommit=True)) as db:
            db.execute(
                "UPDATE operator_runs SET owner_user_id = ? WHERE id = ?",
                (other, run["id"]),
            )
        assert http.get("/skills/example/revisions/1/reads").json() == []
        assert http.get(f"/runs/{run['id']}").status_code == 404


def test_ambiguous_manifest_rolls_back_catalog(tmp_path):
    skills = SkillAPI(tmp_path / "workspace.db")
    original = SkillSource("skills/example", MANIFEST, "first")
    skills.import_catalog(SkillCatalog("1" * 40, (original,)))
    update = SkillSource(
        original.path, MANIFEST.replace("revision: 1", "revision: 2"), "second"
    )
    ambiguous = SkillSource("skills/other", MANIFEST + "id: other\n", "ambiguous")
    with pytest.raises(SkillCatalogError, match="other/operator.yaml.*duplicate.*id"):
        skills.import_catalog(SkillCatalog("2" * 40, (update, ambiguous)))
    assert [(s["id"], s["revision"]) for s in skills.list_skills()] == [("example", 1)]
    with pytest.raises(SkillNotFoundError):
        skills.read_skill("example", 2)


def test_skill_calls_cannot_attach_to_an_unrelated_goal(tmp_path):
    api = GoalAPI(tmp_path / "workspace.db")
    goal_id = api.create_goal("A goal")["id"]
    run_id = api.start_run()["id"]
    malformed = api.start_tool_call(
        run_id, "read_skill", target_skill_id="not a skill ID", target_revision=1
    )
    api.finish_tool_call(malformed, "denied")
    assert api.get_run(run_id)["calls"][0]["target_skill_id"] is None
    for tool in ("read_skill", "list_skills"):
        with pytest.raises(GoalValidationError, match="goal target"):
            api.start_tool_call(run_id, tool, target_goal_id=goal_id)
    assert len(api.get_run(run_id)["calls"]) == 1


def test_invalid_listing_references_leave_call_open(tmp_path):
    api = GoalAPI(tmp_path / "workspace.db")
    api.skills.import_catalog(
        SkillCatalog("1" * 40, (SkillSource("skills/example", MANIFEST, "first"),))
    )
    run_id = api.start_run()["id"]
    call = api.start_tool_call(run_id, "list_skills")
    ref = {"id": "example", "revision": 1}
    for invalid in (
        [ref, ref],
        [ref | {"revision": True}],
        [ref | {"revision": "1"}],
        [ref, {"id": "missing", "revision": 1}],
    ):
        with pytest.raises(GoalValidationError):
            api.finish_tool_call(call, "returned", returned_skills=invalid)
        assert api.get_run(run_id)["calls"][0]["outcome"] == "unfinished"
    api.finish_tool_call(call, "returned", returned_skills=[ref])
    assert api.get_run(run_id)["calls"][0]["returned_skills"] == [ref]


def test_invalid_skill_revision_is_a_validation_error(tmp_path):
    skills = SkillAPI(tmp_path / "workspace.db")
    for operation in (skills.read_skill, skills.reading_calls):
        for revision in (0, True, "1", 2**63):
            with pytest.raises(SkillValidationError, match="revision"):
                operation("example", revision)
