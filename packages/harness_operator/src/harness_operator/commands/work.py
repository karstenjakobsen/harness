"""Owner commands for worker briefs, attempts, and immutable deliverables."""

from pathlib import Path

import click

from harness_api import GoalAPI, WorkAPI, read_skill_catalog

from ..terminal import POSITIVE_INTEGER, print_record
from ..worker import DockerWorkerLauncher


@click.group()
def work():
    """Prepare worker assignments and inspect their submitted files."""


@work.command("create")
@click.option("--goal-id", type=POSITIVE_INTEGER, required=True)
@click.option("--revision", type=POSITIVE_INTEGER, required=True)
@click.option("--operator-id", type=POSITIVE_INTEGER, required=True)
@click.option("--brief", required=True)
@click.option("--skill", "skills", multiple=True, metavar="ID@REVISION")
@click.option("--source", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--base-sha")
def create_work(goal_id, revision, operator_id, brief, skills, source, base_sha):
    """Save an immutable brief tied to an exact goal revision."""
    selected = []
    for skill in skills:
        identifier, separator, number = skill.rpartition("@")
        if not separator or not identifier or not number.isdecimal():
            raise click.BadParameter("Use ID@REVISION.", param_hint="--skill")
        selected.append({"id": identifier, "revision": int(number)})
    goals = GoalAPI()
    goals.skills.import_catalog(read_skill_catalog())
    print_record(
        WorkAPI().create_work_item(
            goal_id,
            revision,
            operator_id,
            brief,
            skills=selected,
            source_path=source.resolve() if source else None,
            base_sha=base_sha,
        )
    )


@work.command("start")
@click.argument("work_item_id", type=POSITIVE_INTEGER)
@click.option("--attempt-id", required=True)
@click.option("--image", envvar="HARNESS_WORKER_IMAGE", required=True)
@click.option("--timeout", type=click.IntRange(min=1), default=600, show_default=True)
def start_work(work_item_id, attempt_id, image, timeout):
    """Start or recover one Docker attempt, wait for exit, and clean scratch."""
    print_record(
        DockerWorkerLauncher(WorkAPI()).start(
            work_item_id, attempt_id, image, timeout=timeout
        )
    )


@work.command("show")
@click.argument("attempt_id")
def show_work(attempt_id):
    """Read the saved attempt, handoff metadata and worker MCP audit."""
    print_record(DockerWorkerLauncher(WorkAPI()).show(attempt_id))


@work.command("artifact")
@click.argument("goal_id", type=POSITIVE_INTEGER)
@click.option(
    "--output", type=click.Path(dir_okay=False, path_type=Path), required=True
)
def get_work_artifact(goal_id, output):
    """Retrieve the newest saved deliverable for a goal into an owner file."""
    api = WorkAPI()
    artifacts = api.list_artifacts(goal_id)
    if not artifacts:
        raise click.ClickException("This goal has no saved worker artifact.")
    artifact = artifacts[-1]
    # Exclusive creation avoids replacing an unrelated owner file.
    with output.open("xb") as destination:
        destination.write(api.read_artifact_bytes(artifact["id"]))
    print_record(artifact)
