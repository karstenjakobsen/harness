"""Owner commands for worker briefs, attempts, and immutable deliverables."""

from pathlib import Path

import click

from harness_api import DATABASE_PATH, GoalAPI, WorkAPI, read_skill_catalog
from harness_mcp.worker import serve_worker_mcp

from ..terminal import POSITIVE_INTEGER, print_record


@click.group()
@click.option(
    "--workspace",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    show_default=True,
)
@click.pass_context
def work(ctx, workspace):
    """Prepare worker assignments and inspect their submitted files."""
    ctx.obj = WorkAPI(workspace / DATABASE_PATH)


@work.command("create")
@click.option("--goal-id", type=POSITIVE_INTEGER, required=True)
@click.option("--revision", type=POSITIVE_INTEGER, required=True)
@click.option("--operator-id", type=POSITIVE_INTEGER, required=True)
@click.option("--brief", required=True)
@click.option("--skill", "skills", multiple=True, metavar="ID@REVISION")
@click.option("--source", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--base-sha")
@click.pass_obj
def create_work(api, goal_id, revision, operator_id, brief, skills, source, base_sha):
    """Save an immutable brief tied to an exact goal revision."""
    selected = []
    for skill in skills:
        identifier, separator, number = skill.rpartition("@")
        if not separator or not identifier or not number.isdecimal():
            raise click.BadParameter("Use ID@REVISION.", param_hint="--skill")
        selected.append({"id": identifier, "revision": int(number)})
    goals = GoalAPI(api.database_path)
    goals.skills.import_catalog(read_skill_catalog())
    print_record(
        api.create_work_item(
            goal_id,
            revision,
            operator_id,
            brief,
            skills=selected,
            source_path=source.resolve() if source else None,
            base_sha=base_sha,
        )
    )


@work.command("prepare")
@click.argument("work_item_id", type=POSITIVE_INTEGER)
@click.option("--attempt-id", required=True)
@click.pass_obj
def prepare_work(api, work_item_id, attempt_id):
    """Persist an attempt for later execution."""
    print_record(api.create_attempt(attempt_id, work_item_id))


@work.command("bind-scratch")
@click.argument("attempt_id")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.pass_obj
def bind_scratch(api, attempt_id, path):
    """Bind an existing scratch directory for file submissions."""
    print_record(api.set_scratch(attempt_id, path.resolve()))


@work.command("issue-credential")
@click.argument("attempt_id")
@click.option(
    "--output", type=click.Path(dir_okay=False, path_type=Path), required=True
)
@click.pass_obj
def issue_credential(api, attempt_id, output):
    """Issue an attempt credential into a new private file."""
    print_record(api.issue_attempt_credential(attempt_id, output))


@work.command("revoke-credential")
@click.argument("attempt_id")
@click.pass_obj
def revoke_credential(api, attempt_id):
    """Revoke the attempt's current credential."""
    print_record(api.revoke_attempt_grant(attempt_id))


@work.command("serve-mcp")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option(
    "--port", type=click.IntRange(min=1, max=65535), default=8001, show_default=True
)
@click.option(
    "--allowed-host", multiple=True, help="Allowed HTTP Host for remote access."
)
@click.pass_obj
def serve_mcp(api, host, port, allowed_host):
    """Serve worker MCP for the selected workspace until interrupted."""
    serve_worker_mcp(
        api, host=host, port=port, allowed_hosts=list(allowed_host) or None
    )


@work.command("show")
@click.argument("attempt_id")
@click.pass_obj
def show_work(api, attempt_id):
    """Read the saved attempt, handoff metadata and worker MCP audit."""
    print_record(api.get_attempt_details(attempt_id))


@work.command("artifact")
@click.argument("goal_id", type=POSITIVE_INTEGER)
@click.option(
    "--output", type=click.Path(dir_okay=False, path_type=Path), required=True
)
@click.pass_obj
def get_work_artifact(api, goal_id, output):
    """Retrieve the newest saved deliverable for a goal into an owner file."""
    artifacts = api.list_artifacts(goal_id)
    if not artifacts:
        raise click.ClickException("This goal has no saved worker artifact.")
    artifact = artifacts[-1]
    content = api.read_artifact_bytes(artifact["id"])
    # Exclusive creation avoids replacing an unrelated owner file.
    with output.open("xb") as destination:
        destination.write(content)
    print_record(artifact)
