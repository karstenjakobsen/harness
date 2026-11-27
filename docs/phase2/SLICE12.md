I’d make **Slice 12** the first time a worker delivers something that keeps doing useful work **after the worker exits**. The standing goal is the one we’ve discussed: keep one designated file at mode `0600`.

Slice 11 gave us a file we could retrieve. The question for Slice 12 is: **can we take exactly what the worker submitted, run it independently, and observe whether it maintains the goal?**

| Step | What we do | What it proves |
|---|---|---|
| **Prepare** | Through the CLI, create the standing goal and a work item asking for a small shell script that maintains the mode of a supplied file. | The goal and brief exist before anything runs. |
| **Build** | We manually launch one live Codex worker on Nomad. It reads the brief, writes the script, submits it through MCP and exits. | The same worker image can deliver executable behavior. |
| **Deploy** | After worker exit, credential revocation and scratch cleanup, retrieve and verify the script through Harness. Stage it separately and mount it read-only into a second Jinja job using a pinned shell image. Mount only disposable test data writable. Inspect the script and exact rendered job through a distinct checkpoint command, then explicitly submit it to Nomad ourselves. | The service has its own job ID and lifetime. It needs neither Codex nor the worker’s MCP credential. |
| **Observe** | Ask for polling once per second. First observe startup correction from initial `0644` to `0600`. Only then deliberately reset the target to `0644` and observe a second correction within three seconds, with contents unchanged and a sibling file still `0644`. Confirm the service is stopped with no running replacement, set `0644` again, and sample for at least four seconds. | The running deliverable maintains the mode after startup and changes only the intended file. |

I’d keep the **worker handoff to one artifact** in this slice: the script. We supply the Nomad template and record the script digest, producing attempt, goal revision, and consuming service job ID in the experiment receipt. That lets us answer *“which running service came from this worker’s delivery?”* before we commit to a deployment model in Harness.

I’d also **defer `/metrics`, `goal_success`, and notifications** for this experiment. File mode gives us a cheap independent observation with `stat`. Once we’ve seen how a standing workload is delivered and verified, we can decide what the service should report and how the operator should discover drift. The standing goal stays active throughout.

"so no changes to anyh package jet. just testing nomad jobs. i like it"

Exactly. **Slice 12 stays under `dev/phase2/`, with zero changes to `packages/`.** We reuse the existing CLI, worker image, and MCP artifact handoff.

We manually submit two Nomad jobs. The first runs a live Codex worker that writes and submits a script, then exits. After its scratch is gone, we retrieve the script through Harness and run those exact bytes in the second job.

First observe the service change the disposable file's initial mode from `0644` to `0600`. Then deliberately reset it to `0644` and observe a second correction. Stop the service, change the file to `0644` again, and verify it stays there. That gives us evidence that the delivered service maintains the file after the worker is gone.

## Acceptance details

The [implementation checklist](SLICE12_TODO.md) records these requirements.

Stage the verified `maintain-mode.sh` in a dedicated delivery directory, mount
that directory read-only at `/delivery`, and mount the disposable test directory
writable at `/data`. Invoke `/bin/sh /delivery/maintain-mode.sh /data/target`.
Independently hash the script visible inside the service allocation and compare
it with the Harness artifact digest before the observation begins. The target
and a sibling file start at `0644` with recorded contents. After correction,
require the target to be `0600` with its original contents and the sibling to
remain `0644` with its original contents.

The worker brief specifies a one-second polling interval and a separate
three-second correction deadline. Record three distinct external observations,
including sample times, modes and actual elapsed time using a monotonic clock.

1. **Startup:** Leave the initial `0644` target untouched and wait to observe
   `0600` within a recorded bounded startup wait. Require this success before
   introducing drift.
2. **Drift:** Deliberately reset the now-`0600` target to `0644` and start a fresh
   three-second clock. Require a second correction to `0600`. After both startup
   and drift correction, verify that the sibling remains `0644` and both files
   retain their original contents.
3. **Shutdown:** After Nomad confirms shutdown with no running replacement,
   reset the target to `0644` and sample it for at least four seconds. Every
   sample must stay `0644`, with both files' contents and the sibling's mode
   preserved. Check that no replacement ran during that observation window.

Include a regression showing that a script which runs `chmod` once at startup
and then sleeps fails the drift observation even if startup succeeds.

Retrieval uses the existing owner CLI with zero AI operator sessions. Select the
same workspace for both commands and use a new output path.

```sh
operator work --workspace "$workspace" show "$attempt_id" > attempt.json
operator work --workspace "$workspace" artifact "$goal_id" \
  --output maintain-mode.sh > export.json
sha256sum maintain-mode.sh
```

Check the saved attempt and work item against the prepared identifiers and goal
revision. Require the exported artifact ID to match the attempt's saved artifact
and its metadata to identify that producing attempt and revision. Require the
file digest to match the recorded artifact digest. `work artifact` exports the
latest artifact for the goal, so a newer submission must cause these comparisons
to fail before deployment.

The service checkpoint is a distinct command that verifies and stages the
delivery, saves its provenance and renders the exact service job without
submitting it. We can inspect those files and choose whether to deploy or request
a corrected delivery. A subsequent explicit submission command rechecks their
digests. A Harness deployment model and automated deployment judgment remain
outside this slice.
