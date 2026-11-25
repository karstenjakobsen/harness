import json
import sys

import pytest

from harness_operator import main


def test_workspace_account_lifecycle_through_cli(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)

    def invoke(*args, error=None):
        monkeypatch.setattr(sys, "argv", ["operator", *map(str, args)])
        code = main()
        out = capsys.readouterr()
        if error is not None:
            assert code == 1 and error in out.err
            assert out.out == ""
            return
        assert code == 0, out.err
        return json.loads(out.out)

    [admin] = invoke("user", "list")
    assert admin["id"] == 1 and admin["username"] == "admin"
    invoke("user", "delete", admin["id"], error="admin cannot be deleted")
    owner = invoke("user", "create", "sam", "--name", "Sam")
    owner_id = owner["id"]
    assert type(owner_id) is int and owner["username"] == "sam"
    assert invoke("user", "get", owner_id) == owner
    assert (
        invoke("user", "update", owner_id, "--name", "Sam Lee")["display_name"]
        == "Sam Lee"
    )
    operator = invoke(
        "register", "Planner", "--user", owner_id, "--mission", "Review goals"
    )
    operator_id = str(operator["id"])
    assert (
        operator["owner_user_id"] == owner_id and operator["mission"] == "Review goals"
    )
    assert invoke("get", operator_id) == operator
    assert invoke("list", "--user", owner_id) == [operator]
    assert invoke("list", "--user", admin["id"]) == []
    invoke("user", "delete", owner_id, error="still owns a registered operator")
    assert invoke("unregister", operator_id)["deleted_at"]
    invoke("get", operator_id, error="was not found")
    assert invoke("list") == []
    assert invoke("user", "delete", owner_id)["deleted_at"]
    assert invoke("user", "list") == [admin]
    invoke("user", "get", owner_id, error="was not found")
    invoke("register", "Other", "--user", owner_id, error="was not found")
    invoke("user", "create", "sam", error="reserved")
    assert invoke("register", "Default")["owner_user_id"] == admin["id"]


@pytest.mark.parametrize("option", ["--user", "--mission"])
def test_workspace_registration_options_require_name(
    monkeypatch, tmp_path, capsys, option
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["operator", "register", option, "1"])
    assert main() == 2
    assert "Supply the operator NAME" in capsys.readouterr().err
    assert not (tmp_path / ".harness").exists()


def test_cli_rejects_explicit_user_id(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["operator", "user", "create", "sam", "--id", "50"]
    )
    assert main() == 2
    assert "No such option '--id'" in capsys.readouterr().err
    assert not (tmp_path / ".harness").exists()
