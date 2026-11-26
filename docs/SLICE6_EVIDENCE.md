# Slice 6 acceptance evidence

Run the evidence script from the repository root with the workspace dependencies installed and Codex signed in. [Evidence script](SLICE6_EVIDENCE.sh)

```bash
bash docs/SLICE6_EVIDENCE.sh
```

The signed-in test creates an isolated workspace through the CLI. Operator A revises the library goal. Operator B receives only the goal ID and the owner's question. Starting from that same goal ID over HTTP, the test follows revision 2 to A's `revise_goal` call and follows B's separate `get_goal_activity` and `get_run` calls to the records B inspected. It verifies that B's completion grant covers a different subgoal and that B made no goal changes. [Slice 6 acceptance](SLICE6_TODO.md#acceptance)

A second test uses the real stdio MCP adapter to inspect A's run while the revision call is still `unfinished`. It verifies over HTTP that B's saved read preserves that outcome and the committed revision after A's call becomes `returned`. It also checks that calling `revise_goal` directly under B's grant is denied.

## Captured output

Both tests passed on 25 November 2026 with warnings treated as errors. Each test uses its own temporary workspace, so the IDs in the two outputs refer to different fixtures.

````text

Owner's question
Goal ID 1.
Who changed the success criteria for this goal, what changed, and which run and call saved it?

Signed-in operator B's reply
**Goal 1 — Join the library (active).** Registered operator ID **1** added a new requirement to the success criteria. Revision 1 required an active library membership. Revision 2 also requires successfully completing the first library checkout.

**Run 1, call 3** (`revise_goal`) committed revision 2 on November 25, 2026. The call returned and the run succeeded.

Verified HTTP response excerpts
{
  "/goals/1/history?view=activity": {
    "revision_1_criteria": "Membership is active",
    "revision_2_criteria": "Library membership is active and the first library checkout has been completed successfully.",
    "committing_call": {
      "run_id": 1,
      "sequence": 3
    },
    "activity_read": {
      "run_id": 2,
      "sequence": 2
    }
  },
  "/runs/1": {
    "operator_id": 1,
    "definition_grant": {
      "id": 1,
      "operator_id": 1,
      "action": "revise_goal",
      "goal_id": 1
    },
    "call": {
      "sequence": 3,
      "tool": "revise_goal",
      "outcome": "returned",
      "committed_revision": {
        "goal_id": 1,
        "revision": 2
      }
    }
  },
  "/runs/2": {
    "operator_id": 2,
    "granted_goal_id": 3,
    "calls": [
      {
        "sequence": 2,
        "tool": "get_goal_activity",
        "outcome": "returned",
        "returned_history": {
          "goal_id": 1,
          "timeline": [
            {
              "kind": "revision",
              "revision": 1,
              "committing_call": null
            },
            {
              "run_id": 1,
              "sequence": 1,
              "kind": "call",
              "at": "2026-11-25 19:37:59.748175",
              "tool": "get_goal_tree",
              "outcome": "returned",
              "relationship": "requested"
            },
            {
              "run_id": 1,
              "sequence": 2,
              "kind": "call",
              "at": "2026-11-25 19:38:01.632463",
              "tool": "list_goals",
              "outcome": "returned",
              "relationship": "listed"
            },
            {
              "run_id": 1,
              "sequence": 3,
              "kind": "call",
              "at": "2026-11-25 19:38:06.693985",
              "tool": "revise_goal",
              "outcome": "returned",
              "relationship": "revision_target"
            },
            {
              "kind": "revision",
              "revision": 2,
              "committing_call": {
                "run_id": 1,
                "sequence": 3
              }
            },
            {
              "run_id": 2,
              "sequence": 1,
              "kind": "call",
              "at": "2026-11-25 19:38:20.516387",
              "tool": "list_goals",
              "outcome": "returned",
              "relationship": "listed"
            }
          ]
        }
      },
      {
        "sequence": 3,
        "tool": "get_run",
        "outcome": "returned",
        "returned_history": {
          "run_id": 1,
          "outcome": "succeeded",
          "calls": [
            {
              "run_id": 1,
              "sequence": 1,
              "outcome": "returned",
              "committed_event_id": null,
              "retrieved_event_id": null,
              "committed_revision": null,
              "retrieved_revision": null
            },
            {
              "run_id": 1,
              "sequence": 2,
              "outcome": "returned",
              "committed_event_id": null,
              "retrieved_event_id": null,
              "committed_revision": null,
              "retrieved_revision": null
            },
            {
              "run_id": 1,
              "sequence": 3,
              "outcome": "returned",
              "committed_event_id": null,
              "retrieved_event_id": null,
              "committed_revision": {
                "goal_id": 1,
                "revision": 2
              },
              "retrieved_revision": null
            }
          ]
        }
      }
    ]
  }
}
B's run made no goal changes.
.Processing request of type ListToolsRequest
Processing request of type CallToolRequest
Processing request of type CallToolRequest
Processing request of type CallToolRequest
Processing request of type CallToolRequest
Tool 'revise_goal' not listed, no validation will be performed
Processing request of type ListToolsRequest
Processing request of type CallToolRequest
Processing request of type CallToolRequest

MCP snapshot verified over HTTP. Run 1, call 1 now shows returned.
B's earlier read in run 2, call 3 still shows A's run and call as unfinished and unfinished with revision 2 committed.
B's direct revise_goal in call 4 was denied. The library goal remained at revision 2.
.
2 passed in 37.42s
````
