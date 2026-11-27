I’d start with **three core models: `User`, `Operator`, and `Goal`**. A goal is the durable record of what the user wants. Its definition can evolve, it can relate to other goals, and its history explains how the user and operator reached each decision.

For SQLite, I’d use these seven tables. The last four support the `Goal` model.

| Table | Main fields | Responsibility |
|---|---|---|
| `users` | `id`, `display_name`, `created_at` | Identifies the human who owns the operator. |
| `operators` | `id`, `owner_user_id`, `name`, `mission`, `created_at` | Stores the operator’s identity and standing instructions. |
| `goals` | `id`, `operator_id`, `parent_goal_id?`, `status`, `next_review_at?`, `created_at` | Gives each goal a stable identity, lifecycle, and optional parent. |
| `goal_revisions` | `goal_id`, `revision`, `title`, `desired_outcome`, `duration`, `assessment_type`, `success_criteria`, `measurement_plan`, `created_at`, `source_event_id` | Preserves each definition of the goal and the conversation or decision that caused it to change. Primary key is `(goal_id, revision)`. |
| `goal_links` | `from_goal_id`, `relation`, `to_goal_id`, `condition?`, `created_by_event_id`, `ended_by_event_id?` | Records `depends_on` and `mitigates` relationships. A dependency can specify the condition required from the other goal. |
| `goal_events` | `id`, `goal_id`, `revision?`, `kind`, `actor`, `occurred_at`, `recorded_at`, `payload` | The chronological record of messages, reads, searches, decisions, observations, assessments, and lifecycle changes. |
| `goal_event_links` | `event_id`, `relation`, `related_event_id` | Connects an assessment to its evidence, a reply to its question, or a decision to the search results that informed it. |

### What belongs on a goal

| Field | Proposed values or meaning |
|---|---|
| `status` | `draft`, `active`, `paused`, `completed`, `revoked`. This controls whether the operator may pursue the goal. |
| `duration` | `one_time` or `standing`. A successful check can complete a one-time goal. The same check on a standing goal means it is holding **as of that observation**. |
| `assessment_type` | `objective`, `judgment`, or `mixed`. |
| `success_criteria` | What the user and operator agree would count as success. This can be provisional while the goal is a draft. |
| `measurement_plan` | How progress is assessed, who or what supplies observations, and when the operator should revisit the goal or ask the user for input. |

**I’d keep lifecycle and assessment separate.** A goal can be `active` while its latest assessment says *holding*, *needs attention*, or *insufficient evidence*. That distinction lets the operator answer both “Are you still pursuing this?” and “How is it going?”

### How it works in conversation

Suppose the user says, *“Help me track my weight. Ask me on Sundays.”*

1. The operator opens a draft goal and records the first message. Its search for related active and paused goals is recorded under that same goal.
2. If it finds an existing match, it records that decision and links the conversation to the existing goal. Otherwise, it saves revision 1 with Sunday self-reporting as the measurement plan and activates the goal.
3. A Sunday reply becomes an `observation` event. An assessment references that observation and the revision used to interpret it.
4. Later, *“Use my connected scale and only ask when a reading is missing”* creates revision 2 under the **same goal ID**. Earlier readings retain their original source and timestamps.
5. If the user revokes the goal, its status and revocation event are written together. A subsequent request to mitigate its effects gets a new goal with a `mitigates` link.

I’d keep **one parent per subgoal**, allow **multiple dependencies**, and reject cycles in the goal hierarchy or prerequisites. For this first project, a goal’s conversation is its message events in order. That is enough to build the first complete interaction: the user speaks, the operator checks existing goals, records its interpretation, and can later show exactly why a goal exists or changed.

We can have more operators all can work on any goal but only one operator at a time pr goal

Yes. **A goal belongs to the user. An operator is assigned to work on it.** Any of that user’s operators can take a goal, but each goal has at most one active assignment. An operator can hold several goals at once.

I’d change three parts of the model:

| Table | Change |
|---|---|
| `goals` | Replace `operator_id` with `owner_user_id`. The goal keeps its identity, conversation, and history when operators change. |
| `goal_assignments` | Add `id`, `goal_id`, `operator_id`, `claimed_at`, and nullable `released_at`. Each row records one period of responsibility. |
| `goal_events` | For an operator action, record the specific operator and the `assignment_id` under which it acted. User messages can arrive even while the goal is unassigned. |

SQLite can enforce the one-operator rule directly:

```sql
CREATE UNIQUE INDEX one_active_operator_per_goal
ON goal_assignments (goal_id)
WHERE released_at IS NULL;
```

**The API should enforce ownership when work is recorded, too.** If Alice hands a goal to Bob while Alice is preparing an assessment, Alice’s late response must not update the goal under her old assignment. The handoff closes Alice’s assignment and opens Bob’s in one transaction. Each subsequent operator update checks that its assignment is still active.

This gives the operator three clear actions: `claim_goal`, `release_goal`, and `handoff_goal`. Releasing a goal makes it available to another operator. Revoking a goal ends the user’s authorization to pursue it. Those are distinct events in the history.

First version should just be a CLI no UI. What would we need ? CLI, operator API , MCP and SQLite ? Wait with creating the goals in nomad . But we should have table that ties goals to nomad run id/id

Yes. **V1 can be a CLI, an operator, a small goal API exposed through MCP, and SQLite.** The first milestone is a conversation that creates, updates, and revisits goals. Nomad execution can come later.

| Component | Responsibility in V1 |
|---|---|
| **CLI** | Lets the user talk to a named operator, list goals, open an existing goal, and inspect its history. |
| **Operator** | Interprets the user’s intent, searches existing goals for duplicates or conflicts, and uses MCP tools to create, revise, claim, hand off, or revoke a goal. |
| **Goal API** | Owns the rules and writes to SQLite. It enforces one active operator per goal, records revisions, and commits each state change together with its history event. |
| **MCP** | Exposes the Goal API to the operator as tools such as `list_goals`, `get_goal`, `create_goal`, and `claim_goal`. The Goal API can be a Python module inside the MCP server. A separate HTTP service is optional. |
| **SQLite** | Stores users, operators, goals, assignments, revisions, relationships, conversation events, and execution references. |

**I’d add a `goal_runs` table now** and leave it empty until execution is introduced. That lets us define the identifiers without making goal creation depend on a scheduler.

| Field | Meaning |
|---|---|
| `id` | Our stable run ID. |
| `goal_id` | The goal this execution serves. |
| `goal_revision` | The exact definition the run was pursuing. |
| `assignment_id` | The operator assignment that authorized the run. |
| `nomad_job_id` | The Nomad workload associated with the run. |
| `nomad_allocation_id` | The specific execution on a Nomad client, once known. |

The distinction is **one goal can have many runs over its lifetime**. The `goal_id` survives revisions and operator handoffs. Each run points back to the definition and assignment that applied at the time.

For the first CLI acceptance test, I’d use two operators. Tell Alice, *“Keep `ALICE.md` at `0600`.”* Then tell Bob the same thing in different words. **Bob should find the existing goal, see that Alice holds it, and avoid creating a duplicate.** Hand it to Bob, restart the CLI, and ask *“Who owns the work now, and why does this goal exist?”* The answer should come from SQLite, with the original request and handoff visible in the history. That proves the core of this project before a single Nomad job runs.