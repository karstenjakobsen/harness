| Term | Meaning |
|---|---|
| **Operator** | The client that submits a task and reads the evidence. Today it is the Python CLI. A future owner-facing agent can use the same MCP API. |
| **Harness** | The MCP service that creates runs, provides run-scoped tools, and owns run state and evidence. |
| **Engine** | The code inside the harness that supervises a run, selects its verifier, records execution facts, and coordinates cleanup. |
| **Worker** | The process that executes the task with the tools provided for its run. The live worker is Codex running in a container. |
| **Execution backend** | Docker or Nomad. It launches the worker and reports status, logs, and backend identifiers to the engine. |
| **Nomad job** | The batch work specification submitted to Nomad for a run. |
| **Nomad allocation** | Nomad’s placement of the job on a client. The harness links the job and allocation IDs to the run ID. |

The terms I’d use in the API and UI:

| Term | Meaning |
|---|---|
| **Mission** | The owner’s persistent instructions for the operator as a whole. |
| **Task** | A one-time outcome to achieve. “Create `result.txt` with this content.” |
| **Standing goal** | An outcome to maintain over time. “Keep the service healthy.” It can trigger many runs. |
| **Run** | One execution of a task or a standing goal, with its own ID, worker, and evidence. The harness links it to the backend’s container ID or Nomad job and allocation IDs. |
| **Workspace** | The files a worker is given access to for a run, including a writable area for its outputs. |
| **Catalog** | The Git-backed collection of **skills** (reusable procedures), **connectors** (access to tools or services), and **projects** (definitions of the workloads the operator manages). |
| **Evidence** | The trace the harness saves under the run ID, including tool calls, observed results, and verification. |
| **Memory entry** | The operator’s readable account of what happened and what matters for future work, linked to the evidence. |
