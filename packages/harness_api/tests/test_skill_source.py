import subprocess

import pytest

from harness_api import SkillCatalogError, read_skill_catalog


@pytest.fixture
def git(tmp_path):
    def invoke(*args):
        return subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.org",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    invoke("init", "-q")
    return invoke


def test_catalog_provenance_uses_committed_git_objects(tmp_path, git, monkeypatch):
    folder = tmp_path / "skills" / "sample"
    folder.mkdir(parents=True)
    (folder / "operator.yaml").write_text("id: sample\n")
    instructions = folder / "SKILL.md"
    instructions.write_text("Original instructions\n")
    git("add", "skills")
    git("commit", "-qm", "Original")
    original = git("rev-parse", "HEAD")
    instructions.write_text("Different instructions\n")
    git("commit", "-qam", "Second")
    second = git("rev-parse", "HEAD")
    git("replace", second, original)
    caller_objects = tmp_path / "caller-objects"
    caller_objects.mkdir()
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(caller_objects))
    catalog = read_skill_catalog(tmp_path)
    assert catalog.commit_sha == second
    assert catalog.sources[0].instructions == "Different instructions\n"


def test_missing_and_malformed_catalog_roots_are_distinct(tmp_path, git):
    (tmp_path / "README").write_text("Empty catalog")
    git("add", "-A")
    git("commit", "-qm", "Catalog")
    assert read_skill_catalog(tmp_path).sources == ()
    (tmp_path / "skills").write_text("This committed entry is a file")
    git("add", "-A")
    git("commit", "-qm", "Catalog")
    with pytest.raises(SkillCatalogError, match="skills.*directory"):
        read_skill_catalog(tmp_path)
