# Example Harness registry

This fixture shows the package structure proposed for Harness. Start by opening
the engineering manifest, then the two profiles and the worked worker result.

```text
registry/
├── catalog.json
├── marketplace.json
├── default/
│   ├── modes/
│   ├── prompts/
│   └── steering/
├── adapters/
└── plugins/
    ├── engineering/
    │   ├── plugin.yaml
    │   ├── profiles/
    │   ├── skills/
    │   ├── references/
    │   ├── templates/
    │   ├── examples/
    │   ├── schemas/
    │   ├── evals/
    │   ├── workflows/
    │   ├── integrations/
    │   ├── hooks/
    │   └── scripts/
    └── evidence-review/
        ├── plugin.yaml
        └── profiles/
```

`plugin.yaml` declares the skill and profile snapshots and the result format
proposed for Slice 10. Templates, references, evaluations, and example data
support authoring and review. The catalog illustrates a discovery index and
two collections. The evidence-review preview pins an exact dependency on the
engineering package. The marketplace, runtime adapter, default content,
workflow, integration, and hook illustrate later extensions. The validation
script is a manual example using Python and `jsonschema`.

From the `engineering` plugin directory, run the helper against the included
fixture.

```sh
python scripts/validate_result.py examples/king-safety.json
```

The fixture describes expected chess behavior and records execution as pending.
The schema check confirms that the payload has the required fields and types.
The worker run and the operator's review supply the rest of the evidence.

[Manifest](plugins/engineering/plugin.yaml) · [Brief](plugins/engineering/templates/work-brief.md) · [Worked result](plugins/engineering/examples/king-safety.json)
