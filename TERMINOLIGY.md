| Term | Meaning |
|---|---|
| **Operator** | The owner-facing agent. It understands the mission, delegates work to the harness, reads the evidence, and writes a readable memory entry. |
| **Harness engine** | The service behind MCP. It creates runs, chooses what each worker gets, starts and stops workers, records tool calls, and verifies outcomes. |
| **Worker** | The Codex instance launched to carry out a run. It can use a shell, work with files, create skills, and call the connectors provided to it. |
| **Execution backend** | The infrastructure that launches and supervises the worker. In Nomad setup, Nomad schedules the job and Docker runs the worker container. |

The terms I’d use in the API and UI:

| Term | Meaning |
|---|---|
| **Mission** | The owner’s persistent instructions for the operator as a whole. |
| **Task** | A one-time outcome to achieve. “Create `result.txt` with this content.” |
| **Standing goal** | An outcome to maintain over time. “Keep the service healthy.” It can trigger many runs. |
| **Run** | One execution of a task or a standing goal, with its own ID, worker, and evidence. The harness links it to the backend’s job and allocation IDs. |
| **Workspace** | The files a worker is given access to for a run, including a writable area for its outputs. |
| **Catalog** | The Git-backed collection of **skills** (reusable procedures), **connectors** (access to tools or services), and **projects** (definitions of the workloads the operator manages). |
| **Evidence** | The trace the harness saves under the run ID, including tool calls, observed results, and verification. |
| **Memory entry** | The operator’s readable account of what happened and what matters for future work, linked to the evidence. |

For the first slice, that gives us a precise sentence: **The operator submits a task to the harness. The harness creates a run and launches a worker. The worker calls `write_file` over MCP, the harness verifies the file, and the operator reads the evidence by run ID.**