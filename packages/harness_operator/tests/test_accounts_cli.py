import json
import sys

import pytest

from harness_operator import main


def test_workspace_account_lifecycle_through_cli(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)

    def invoke(*args, error=None):
        monkeypatch.setattr(sys, "argv", ["operator", *args])
        code = main()
        out = capsys.readouterr()
        if error is not None:
            assert code == 1 and error in out.err
            assert out.out == ""
            return
        assert code == 0, out.err
        return json.loads(out.out)

    [admin] = invoke("user", "list")
    assert admin["id"] == "admin"
    invoke("user", "delete", "admin", error="admin cannot be deleted")
    owner = invoke("user", "create", "sam", "--name", "Sam")
    assert invoke("user", "get", "sam") == owner
    assert (
        invoke("user", "update", "sam", "--name", "Sam Lee")["display_name"]
        == "Sam Lee"
    )
    operator = invoke(
        "register", "Planner", "--user", "sam", "--mission", "Review goals"
    )
    operator_id = str(operator["id"])
    assert operator["owner_user_id"] == "sam" and operator["mission"] == "Review goals"
    assert invoke("get", operator_id) == operator
    assert invoke("list", "--user", "sam") == [operator]
    assert invoke("list", "--user", "admin") == []
    invoke("user", "delete", "sam", error="still owns a registered operator")
    assert invoke("unregister", operator_id)["deleted_at"]
    invoke("get", operator_id, error="was not found")
    assert invoke("list") == []
    assert invoke("user", "delete", "sam")["deleted_at"]
    assert invoke("user", "list") == [admin]
    invoke("user", "get", "sam", error="was not found")
    invoke("register", "Other", "--user", "sam", error="was not found")
    invoke("user", "create", "sam", error="reserved")
    assert invoke("register", "Default")["owner_user_id"] == "admin"


@pytest.mark.parametrize("option", ["--user", "--mission"])
def test_workspace_registration_options_require_name(
    monkeypatch, tmp_path, capsys, option
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["operator", "register", option, "value"])
    assert main() == 2
    assert "Supply the operator NAME" in capsys.readouterr().err
    assert not (tmp_path / ".harness").exists()
