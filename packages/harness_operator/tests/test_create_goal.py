import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from harness_api import DATABASE_PATH, GoalAPI
from harness_operator import main


def test_create_saves_draft_and_clarification(monkeypatch, tmp_path, capsys):
    request = "Help make the handover clear for the next engineer."
    question = "Is this for one handover or for every handover?"
    draft = {
        "title": "Make the handover clear",
        "desired_outcome": "The next engineer can take over confidently.",
        "duration": None,
        "duration_days": None,
        "assessment_type": "judgment",
        "success_criteria": "The next engineer says the handover is clear.",
        "measurement_plan": "Ask the next engineer for feedback.",
        "clarification": question,
    }
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["operator", "goal", "create", request])

    def run(command, **options):
        schema_path = Path(command[command.index("--output-schema") + 1])
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert set(schema["required"]) == set(draft)
        assert options["input"].endswith(f"\n{request}")
        assert options["stdout"] == subprocess.PIPE
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(draft))

    monkeypatch.setattr(subprocess, "run", run)
    assert main() == 0
    output = capsys.readouterr().out
    assert "Saved draft goal #1" in output and question in output

    api = GoalAPI()
    saved = api.get_goal(1)
    assert saved["status"] == "draft"
    assert saved["duration"] is None
    assert saved["duration_days"] is None
    assert saved["assessment_type"] == "judgment"
    assert saved["measurement_plan"] == draft["measurement_plan"]
    assert api.list_goals("active") == []
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        messages = connection.execute(
            "SELECT actor, json_extract(payload, '$.text') FROM goal_events ORDER BY id"
        ).fetchall()
    assert messages == [("user", request), ("operator", question)]


def test_seven_day_draft_persists_structured_window(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    message = "Track food for seven days"
    monkeypatch.setattr(sys, "argv", ["operator", "goal", "create", message])

    def run(command, **options):
        schema_path = Path(command[command.index("--output-schema") + 1])
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert "duration_days" in schema["required"]
        assert {"type": "integer"} in schema["properties"]["duration_days"]["anyOf"]
        assert options["input"].endswith(message)
        draft = {
            "title": "Track food",
            "desired_outcome": "Keep a food log",
            "duration": "one_time",
            "duration_days": 7,
            "assessment_type": "objective",
            "success_criteria": "Log daily",
            "measurement_plan": "Review the log",
            "clarification": None,
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(draft))

    monkeypatch.setattr(subprocess, "run", run)
    assert main() == 0
    api = GoalAPI()
    (saved,) = api.list_goals()
    assert saved["status"] == "draft"
    (revision,) = api.get_goal_history(saved["id"])
    assert (revision["revision"], revision["duration"], revision["duration_days"]) == (
        1,
        "one_time",
        7,
    )


def test_create_rejects_invalid_codex_output(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["operator", "goal", "create", "My goal"])
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **_: subprocess.CompletedProcess(command, 0, stdout="{}"),
    )
    assert main() == 1
    assert "invalid goal draft" in capsys.readouterr().err
    assert not DATABASE_PATH.exists()
