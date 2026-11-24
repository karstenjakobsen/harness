import subprocess
import sys
from unittest.mock import Mock

import pytest

from harness_operator import main


@pytest.mark.parametrize(("returncode", "exit_code"), [(0, 0), (1, 1), (-15, 143)])
def test_register_runs_device_login_with_terminal_streams(
    monkeypatch, returncode, exit_code
):
    command = ["codex", "login", "--device-auth"]
    run = Mock(return_value=subprocess.CompletedProcess(command, returncode))
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", ["operator", "register"])

    assert main() == exit_code
    run.assert_called_once_with(command, check=False)
