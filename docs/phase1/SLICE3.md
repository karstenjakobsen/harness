# DIALOG 

"After this we will be adding a first class evidence layer"

That changes what I’d ask the engineer to settle now. Keep the next change focused on the API contract, and make sure a completion decision can later cite first-class evidence. The current complete_goal(..., confirmation=... | reference=...) operation can keep working when that layer arrives.

I’d agree on three definitions before the next slice:

Concept	Question it answers	Example
Goal revision	What counts as success for this version of the goal?	Log food on 14 distinct days.
Evidence	What was reported or observed, by whom, and when?	The owner reports logging Monday’s meals. Later, a food app reports three entries for Monday.
Assessment	What does the available evidence establish against this revision’s criteria?	Monday counts as one of the 14 required days. The goal is still active.
The important distinction is evidence can accumulate while a goal stays open. If the owner extends a seven-day goal to fourteen days, the first seven days of observations can still count where they meet the new criteria. The earlier completion decision remains attached to the seven-day revision. Likewise, an owner-pasted app link and a record retrieved directly from that app have different provenance, even if they refer to the same activity.

For the engineer, I’d add one sentence to the handoff: “Keep completion revision-specific. Preserve who supplied the evidence and what it says. In the next slice, evidence must be recordable independently of completion, and a decision must be able to cite multiple evidence records.” That gives us a concrete boundary without designing app connectors or running workloads yet.

Is this the next best slice ? Should we focus on something else ? Evidence could also mean the audit layer
I’d finish the API-boundary fixes, then make the next slice “record progress and explain it.” That gives you a concrete reason to introduce first-class evidence. I’d use the existing goal history to answer audit questions and defer a platform-wide audit layer until there’s a second consumer.

Evidence and audit overlap, but they answer different questions. Suppose the owner says on Tuesday, “I logged all my meals on Monday.”

Question	What Harness should retain
Evidence — what do we know about Monday?	The owner reports logging all meals on Monday. Monday is the date the claim concerns.
Audit — who recorded it, and when?	The owner submitted that statement on Tuesday. Harness records the submission time and the resulting evidence ID.
Assessment — what does it establish?	If the goal accepts owner confirmation, Monday counts as one of the required days. The goal remains active.
The audit record establishes that the owner made the statement. Whether that statement satisfies the goal depends on the revision’s verification criteria. A single submission can produce both records in the same transaction.

I’d give the engineer one acceptance story:

Through the CLI, create an active goal to track food for seven distinct days. Its criteria accept owner-confirmed daily logs.
Record an observation for Monday. Ask the operator, “What progress have I made, and how do we know?” It should report one of seven days, attribute the observation to the owner, and say the goal is active.
Add a second piece of evidence about Monday. The operator should still report one distinct day and be able to cite both records.
Revise the target to fourteen days and ask again. The answer should be one of fourteen, using the original evidence. History should show when the evidence was submitted and when the target changed.
That story exercises the model decisions worth getting right early: stable evidence IDs, source attribution, observation time versus recording time, and revision-specific interpretation. It also gives you a sharper test than another completion flow: can Harness explain meaningful progress while the goal is still open?

"And some goals (like the file 600) can be fetched by an interface on the running container returning 200"


Yes. The file-mode example adds a second kind of evidence: an observation returned by an interface. I’d use it alongside the food log to test whether the evidence model works for both people and software.

For a standing goal like “keep /app/config at mode 0600,” the important question is what the interface promises. A generic /health returning HTTP 200 tells us the container answered. A dedicated check that reads the file mode can return 200 with an observation such as {"path":"/app/config","mode":"0600"}. If the endpoint contract explicitly defines 200 as “this file currently has mode 0600,” the status alone can also serve as evidence.

What the check returns	What Harness can say
Observed mode 0600 at 10:00	“The file met the requirement at 10:00.” The standing goal stays active.
Observed mode 0644 at 10:05	“The file was out of compliance at 10:05.”
Request times out at 10:10	“The latest check could not determine the mode. The last successful observation was 0644 at 10:05.”
This gives us a model distinction worth making early: goal status and the latest assessment are separate. The goal can be active while the check result is met, unmet, or unknown. Evidence records which interface observed which container, what it returned, and when. The audit trail records who requested the check and when Harness recorded the result.

For the next slice, I’d add a small HTTP test fixture that reads a temporary file’s actual mode. Set it to 0600, fetch the observation, change it to 0644, and fetch again. Then ask the operator “Does the file meet the goal, and when did that change?” It should cite both observations and say the change happened between the checks. That exercises machine-sourced evidence without creating a workload or introducing a scheduler.

## SLICE 3

### Proposed operations

Consider `GoalAPI.record_observation(...)` for recording evidence against a stable goal and `GoalAPI.get_goal_progress(goal_id, revision=None)` for assessing it. Both names and signatures are provisional. A submission retains its source, the date or time the report concerns, and when Harness received it. Derive the submitter from established caller context and preserve the requester and observer separately when known. [Identity and attribution](../../TERMINOLOGY.md#identity-and-attribution)

### Historical progress

The [approved implementation plan](SLICE3_TODO.md#agreed-decisions) selects the first contract below. Suppose revision N ends Monday night. On Tuesday Harness receives a qualifying report about Monday.

| Possible contract | What revision N would show |
| --- | --- |
| Evaluate N’s criteria against all evidence available today | Tuesday’s report can make Monday count toward N. The answer identifies the criteria revision and the evidence used. |
| Reproduce what Harness knew at a historical cutoff | With a cutoff of Monday night, Tuesday’s submission is excluded even though it concerns Monday. Define the cutoff in the API contract and use the recording time to decide what was known. |

Under either contract, a saved completion decision retains the revision and exact evidence it cited when recorded. A later submission can support a new assessment. It cannot change that decision’s citations.

### Proposed Monday acceptance example

Use a plain Python model test first. Create an active goal whose criteria accept owner-confirmed food logs on seven distinct days. Record two qualifying reports for the same Monday and verify that progress is one of seven, cites both evidence IDs, and leaves the goal active. Revise the current target to fourteen and verify one of fourteen from the same reports. Then check that MCP returns the model’s result and the assistant explains who supplied it. [Slice 3 implementation plan](SLICE3_TODO.md)
