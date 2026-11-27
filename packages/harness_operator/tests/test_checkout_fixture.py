"""Checkout patch acceptance oracle retained from Slice 10."""

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures/invoice_checkout"
TEST_COMMAND = "python3 -m unittest discover -s tests -p check_invoice.py -v"
TEST_PATH = "tests/check_invoice.py"
TEST_NAME = "test_quantities_are_included_without_losing_decimal_precision"
CITIES = ["København", "Aarhus", "Odense", "Aalborg", "Esbjerg"]
SKILL = {"id": "worker-handoff", "revision": 1}


def process(directory, *args, check=True, timeout=30):
    result = subprocess.run(
        list(map(str, args)),
        cwd=directory,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if check:
        assert result.returncode == 0, (
            f"Command failed: {args!r}\n{result.stdout}\n{result.stderr}"
        )
    return result


def git(directory, *args):
    return process(directory, "git", *args).stdout.strip()


def run_invoice_test(directory):
    return process(directory, *shlex.split(TEST_COMMAND), check=False)


def make_checkout_fixture(directory):
    """Commit a real fixture and prove its specific test fails at that SHA."""
    shutil.copytree(FIXTURE, directory, ignore=shutil.ignore_patterns("__pycache__"))
    git(directory, "init", "--quiet")
    git(directory, "config", "user.email", "fixture@example.invalid")
    git(directory, "config", "user.name", "Checkout fixture")
    git(directory, "add", ".")
    git(directory, "commit", "--quiet", "-m", "Record failing invoice fixture")
    base_sha = git(directory, "rev-parse", "HEAD")
    baseline = run_invoice_test(directory)
    assert baseline.returncode != 0
    assert TEST_NAME in baseline.stderr
    assert "AssertionError" in baseline.stderr
    assert "FAILED (failures=1)" in baseline.stderr
    assert not git(directory, "status", "--porcelain")
    return base_sha


def source_snapshot(directory):
    return {
        path: (directory / path).read_bytes()
        for path in git(directory, "ls-files").splitlines()
    }


def verify_checkout_patch(source, base_sha, patch, destination):
    """Apply the ordinary artifact and run the unchanged test from its base."""
    process(
        source.parent, "git", "clone", "--quiet", "--no-hardlinks", source, destination
    )
    git(destination, "checkout", "--quiet", "--detach", base_sha)
    original_test = (destination / TEST_PATH).read_bytes()
    changes = git(destination, "apply", "--numstat", "--", patch)
    changed_paths = {line.split("\t", 2)[2] for line in changes.splitlines()}
    assert changed_paths == {"invoice.py", "WORKER_TEST_REPORT.txt"}, (
        "The handoff must fix invoice.py and include its test report; "
        f"the acceptance test must stay unchanged. Got {changed_paths!r}"
    )
    git(destination, "apply", "--check", "--", patch)
    git(destination, "apply", "--", patch)
    assert (destination / TEST_PATH).read_bytes() == original_test
    report = (destination / "WORKER_TEST_REPORT.txt").read_text(encoding="utf-8")
    assert TEST_NAME in report
    assert "Ran 1 test" in report and "OK" in report and "FAILED" not in report
    result = run_invoice_test(destination)
    assert result.returncode == 0, result.stdout + result.stderr
    assert TEST_NAME in result.stderr and "OK" in result.stderr
    assert (destination / TEST_PATH).read_bytes() == original_test
    return result


def reference_patch(directory, patch):
    """Create a known good ordinary patch solely to test the acceptance oracle."""
    implementation = directory / "invoice.py"
    implementation.write_text(
        implementation.read_text(encoding="utf-8").replace(
            "Decimal(price) for price, quantity",
            "Decimal(price) * quantity for price, quantity",
        ),
        encoding="utf-8",
    )
    result = run_invoice_test(directory)
    assert result.returncode == 0, result.stderr
    (directory / "WORKER_TEST_REPORT.txt").write_text(
        result.stdout + result.stderr, encoding="utf-8"
    )
    git(directory, "add", "--intent-to-add", "WORKER_TEST_REPORT.txt")
    patch.write_text(
        process(directory, "git", "diff", "--binary").stdout, encoding="utf-8"
    )


def test_checkout_fixture_is_red_and_patch_passes_the_same_unchanged_test(tmp_path):
    source = tmp_path / "source"
    base_sha = make_checkout_fixture(source)
    initial = source_snapshot(source)
    proposal = tmp_path / "proposal"
    process(tmp_path, "git", "clone", "--quiet", source, proposal)
    patch = tmp_path / "changes.patch"
    reference_patch(proposal, patch)
    verify_checkout_patch(source, base_sha, patch, tmp_path / "verification")
    assert source_snapshot(source) == initial
    assert not git(source, "status", "--porcelain")
    assert run_invoice_test(source).returncode != 0


def test_checkout_handoff_rejects_a_patch_that_changes_the_acceptance_test(tmp_path):
    source = tmp_path / "source"
    base_sha = make_checkout_fixture(source)
    proposal = tmp_path / "proposal"
    process(tmp_path, "git", "clone", "--quiet", source, proposal)
    patch = tmp_path / "tampered.patch"
    reference_patch(proposal, patch)
    test_file = proposal / TEST_PATH
    test_file.write_text(
        test_file.read_text(encoding="utf-8").replace(
            'Decimal("5.00")', 'Decimal("5.0")'
        ),
        encoding="utf-8",
    )
    assert run_invoice_test(proposal).returncode == 0
    patch.write_text(
        process(proposal, "git", "diff", "--binary").stdout, encoding="utf-8"
    )
    with pytest.raises(AssertionError, match="acceptance test must stay unchanged"):
        verify_checkout_patch(source, base_sha, patch, tmp_path / "verification")
