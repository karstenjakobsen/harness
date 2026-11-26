# CHESS.md — A Harness thought experiment

> Build a chess game in Go that I can play in a browser at `https://chess.karstenjakobsen.dk:8001`. Open TCP port 8001 with UFW on my VPS. Use my DigitalOcean account for the `karstenjakobsen.dk` zone to point the hostname at the VPS, and use a Let’s Encrypt certificate. Track every game I play. My long-term goal is to win at least 50% of the time.

This scenario gives us a way to evaluate future Harness slices. Can the operator take an owner’s request, choose skills, delegate work, inspect the result, and decide what to do next? Can the owner later start from a goal and see who did what, under which grant, and with what evidence?

Assume the owner selects the VPS and wants to track games played in this app. Games played elsewhere would require another source of results.

## What goals would the operator propose?

There is one chess project, one delivery goal, and two standing goals. They have different lifetimes and require different evidence.

| Goal | Lifetime | Evidence the operator can inspect |
| --- | --- | --- |
| **I can play chess in a browser.** | One-time delivery | A browser test plays a legal move, rejects a move that would leave the player’s king in check, and finishes a game against the intended opponent. The worker hands over the source revision, test results, and image digest. |
| **My chess game stays available over HTTPS on port 8001.** | Standing | An external client resolves the hostname, validates the certificate served on port 8001, and loads the playable UI. The operator can trace the deployment to its image, workload, firewall rule, and certificate renewal status. |
| **I win at least 50% of my games.** | Standing | The owner can see wins, losses, draws, and the exact finished games behind the percentage. The assessment identifies the player, opponent criteria, and measurement window. |

**“Record every finished game exactly once”** is a one-time subgoal supporting the win-rate goal. A worker can demonstrate it by finishing games while the operator is offline and reading the results twice afterward. Both reads should recover the games, and each game should count once.

The operator has two questions for the owner: **Who do you want to play against? Which games should count toward 50%?** One possible definition is “win at least 10 of my last 20 completed games against the computer at normal difficulty, with draws counting as games played.” After 12 games, the operator can report the record so far. At 10 wins in 20 games, the condition is met and the goal stays active. The next game can change the assessment.

## What gets built, and where does it run?

A **project** holds the chess application’s source and build definition. A **skill** gives the operator or worker versioned instructions. A **connector** implements operations against a service. A **connection** binds a connector to an owner-configured destination and credential. A **host capability** performs a specific operation on a named machine, such as ensuring a firewall rule.

A worker can build a missing connector or host helper and demonstrate it against a disposable target. The owner grants the operator authority to use the reviewed capability against the real destination. The chess build worker can deliver its artifact without access to the DigitalOcean account or the VPS firewall.

**MCP baseline at Slice 9.** Operators already have `list_skills`, `read_skill`, `get_goal_progress`, and, under a parent-scoped grant, `create_subgoal`. Slice 9 provides a Python execution backend for batch workloads. The other MCP actions below, worker access to skills, and long-lived service deployment are proposals.

| Need | What the worker creates or reuses | What the operator needs at runtime | Where it runs when finished | MCP actions we would use |
| --- | --- | --- | --- | --- |
| **Chess project** | A repo with Go source, web UI, tests, a `Dockerfile`, and a schema for durable game history. Reuse the chess and Go-testing skills. | A project workspace, an image registry, and a handoff identifying the commit, image digest, and test results. | The Go server runs in a Nomad-managed container on the VPS. The UI runs in the browser. Git holds the source and the registry holds the image. | **Operator** can `create_subgoal`, `list_skills`, `read_skill`, and `start_work` with a goal revision, brief, and pinned skills. **Worker** can `get_work_brief`, `read_skill` for assigned revisions, and `submit_work_result`. |
| **Deployment** | A service definition for the pinned image and persistent game data. The service has its own identity and outlives the build worker. | Authority to deploy, inspect, update, and stop this service on the selected Nomad target. | Nomad supervises the service on the VPS. Its persistent volume retains games across container replacements. | **Operator** can `deploy_service` with the target and image digest, `inspect_service` to see the running digest and allocation, and `stop_service`. A later deployment can update the same service ID. |
| **DNS and TLS** | Reuse a DigitalOcean DNS connector and an ACME client. Configure certificate issuance and renewal for the chess hostname. | An owner-configured DNS connection. Harness scopes the grant to the chess address record and its ACME challenge record. Credentials and private keys stay out of briefs and audit payloads. | DigitalOcean hosts the DNS records. The connector runs in Harness when invoked. On the VPS, the ACME client renews the certificate and a TLS proxy serves port 8001, forwarding to the private chess listener. | **Operator** can `invoke_connector` with `get_record` or `ensure_record`, configure issuance and renewal with `ensure_certificate`, and use an external `check_https` to verify the endpoint a player reaches. |
| **Host firewall** | Reuse a host helper that inspects and ensures a UFW rule. A worker can build a missing helper and test it on a disposable host. | A grant for inbound TCP 8001 on the named VPS. | The helper runs on the VPS when invoked. The host kernel continues enforcing the rule after the helper exits. | **Operator** can `inspect_firewall_rule` and `ensure_firewall_rule` through audited MCP. The helper owns the UFW command. |
| **Game monitoring** | Record a stable game ID, player ID, opponent, result, and finish time. Expose a read-only feed that resumes after the last game seen. | A read-only chess connection scoped to the owner’s player. | The chess service persists each result when the game finishes. The operator reads the feed when reviewing the goal, including games played between sessions. | **Operator** can `invoke_connector` with `list_finished_games(player_id, after_cursor)`, attach source observations to the goal revision with `record_observation`, and review evidence with `get_goal_progress`. The measurement counts distinct source game IDs. |

The DNS setup illustrates why these responsibilities matter. The address record points `chess.karstenjakobsen.dk` at the VPS. For DNS-01 validation, the ACME client publishes a separate, temporary TXT value at `_acme-challenge.chess.karstenjakobsen.dk` and removes that value after validation. Renewal needs continuing access to that narrow operation. An external HTTPS check then verifies the certificate actually served to a player. [Let’s Encrypt challenge types](https://letsencrypt.org/docs/challenge-types/#dns-01-challenge)
