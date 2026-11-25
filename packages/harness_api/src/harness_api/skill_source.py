"""Read a catalog from Git objects at one resolved Harness source revision."""

import os
from pathlib import Path, PurePosixPath
from subprocess import CalledProcessError, run

from .models.skills import SkillCatalog, SkillCatalogError, SkillSource


def read_skill_catalog(repository: Path | None = None) -> SkillCatalog:
    if repository is None:
        # make setup installs this package from packages/harness_api/src/harness_api.
        repository = (Path(__file__).resolve().parent / "../../../..").resolve()

    # A caller can launch Harness from another worktree or a Git hook.
    env = os.environ.copy()
    for name in (
        "GIT_COMMON_DIR",
        "GIT_WORK_TREE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
    ):
        env.pop(name, None)

    def git(*args: str) -> bytes:
        try:
            return run(
                [
                    "git",
                    "--no-replace-objects",
                    "-C",
                    str(repository),
                    "--git-dir=.git",
                    *args,
                ],
                env=env,
                capture_output=True,
                check=True,
            ).stdout
        except (CalledProcessError, OSError) as error:
            raise SkillCatalogError(
                f"Could not read the committed skill catalog at {repository}: {error}"
            ) from error

    sha = git("rev-parse", "--verify", "HEAD^{commit}").decode("ascii").strip()
    files: dict[str, dict[str, str]] = {}
    for entry in git(
        "ls-tree", "--full-tree", "-r", "-t", "-z", sha, "--", "skills"
    ).split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        try:
            path = PurePosixPath(name.decode("utf-8"))
        except UnicodeDecodeError as error:
            raise SkillCatalogError("Skill paths must be UTF-8.") from error
        mode, kind, oid = header.split()
        if path == PurePosixPath("skills") and kind != b"tree":
            raise SkillCatalogError(f"skills must be a directory at {sha}.")
        if len(path.parts) == 2 and kind == b"tree":
            files[str(path)] = {}
        if len(path.parts) == 3 and path.name in ("operator.yaml", "SKILL.md"):
            if kind != b"blob" or mode not in (b"100644", b"100755"):
                raise SkillCatalogError(f"{path} must be a regular file.")
            files[str(path.parent)][path.name] = oid.decode("ascii")

    def read(directory: str, name: str) -> str:
        oid = files[directory].get(name)
        if oid is None:
            raise SkillCatalogError(f"Missing {directory}/{name} at {sha}.")
        try:
            return git("cat-file", "blob", oid).decode("utf-8")
        except UnicodeDecodeError as error:
            raise SkillCatalogError(f"{directory}/{name} must be UTF-8.") from error

    return SkillCatalog(
        sha,
        tuple(
            SkillSource(
                directory, read(directory, "operator.yaml"), read(directory, "SKILL.md")
            )
            for directory in files
        ),
    )
