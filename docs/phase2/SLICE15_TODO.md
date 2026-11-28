# Slice 15 — Read the Codex key from a Nomad Variable

Run one Codex city delivery on the local Nomad cluster. Manually create `harness/dev/providers/codex` with an `api_key` item. Keep the Harness attempt credential on its existing issue-and-revoke path. [Worker experiment](../../dev/phase2/experiment.py) · [Nomad task templates](https://developer.hashicorp.com/nomad/docs/job-specification/template)

- [x] Add an opt-in renderer flag for Codex API-key auth. Render the variable once into the task’s secrets directory with mode `0600` and load it in the bootstrap. Verify the rendered job contains the variable reference and the runner can prepare without a local provider key.
- [x] Run one live Codex delivery. Verify the audited brief, skill read and artifact submission, Nomad exit, and exact file bytes after cleanup. Verify the provider key is absent from the submitted job, receipt and retained output.
- [x] Run the evidence script and record the offline and live results. [Evidence](SLICE15_EVIDENCE.md)
