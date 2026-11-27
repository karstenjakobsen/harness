#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
make check
make test
receipt=${SLICE12_RECEIPT:-}
if [[ -z $receipt ]]; then
  mkdir -p .harness/phase2
  log=$(mktemp "$PWD/.harness/phase2/slice12-live-XXXXXX.log")
  make test-phase2-standing > "$log" 2>&1
  receipt=$(.venv/bin/python - "$log" <<'PY'
import re
import sys
from pathlib import Path
directory = re.search(r"Slice 12 receipts and outputs saved under (.+)", Path(sys.argv[1]).read_text())[1]
print(Path(directory) / "phase2/receipt.json")
PY
)
fi
.venv/bin/python - "$receipt" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path('dev/phase2').resolve()))
import experiment
import standing

path = Path(sys.argv[1]).resolve()
worker = json.loads(path.read_text())
service_path = standing.service_path(path)
service = json.loads(service_path.read_text())
assert worker['execution']['verified'] and service['verified']
assert service['phase'] == 'finished'
assert service['job_id'] != worker['job_id']
assert service['worker_job_id'] == worker['job_id']
assert worker['execution']['worker_sessions'] == 1
assert worker['execution']['ai_operator_sessions'] == 0
assert all(command[0] != 'ask' for command in worker['owner_commands'])
events = [json.loads(line) for line in (path.parent / 'evidence/stdout.log').read_text().splitlines() if line.startswith('{')]
assert sum(event.get('type') == 'thread.started' for event in events) == 1
inspection = standing.verify_handoff(worker, path)
assert inspection['artifact'] == service['artifact']
goal = experiment.owner_cli(worker, 'goal', 'show', worker['goal_id'])
assert goal['duration'] == 'standing'
for tool in ('get_work_brief', 'read_skill', 'submit_work_result'):
    assert any(call['tool'] == tool and call['outcome'] == 'returned' for call in inspection['calls'])
artifact = experiment.export_artifact(worker, service_path.parent / 'evidence-retrieved.sh', service['artifact']['sha256'], service['artifact']['id'])
assert artifact == service['artifact']
assert service['deployment']['script_sha256'] == artifact['sha256']
assert service['deployment']['delivery_read_only'] and service['deployment']['data_writable']
assert hashlib.sha256((service_path.parent / 'after-service-maintain-mode.sh').read_bytes()).hexdigest() == artifact['sha256']
for directory in ('delivery', 'data'):
    assert not (service_path.parent / directory).exists()
assert all(service['cleanup'].values()) and not service['cleanup_pending']
for stage in ('startup', 'drift', 'shutdown'):
    observation = service['observations'][stage]
    assert observation['passed']
    for sample in observation['samples']:
        assert sample['sibling']['mode'] == '0644'
        for name in ('target', 'sibling'):
            assert sample[name]['sha256'] == service['files'][name]['sha256']
assert service['observations']['drift']['elapsed_seconds'] <= 3
assert service['observations']['shutdown']['elapsed_seconds'] >= 4
assert all(sample['target']['mode'] == '0644' for sample in service['observations']['shutdown']['samples'])
headers = {'X-Nomad-Token': os.environ['NOMAD_TOKEN']} if os.environ.get('NOMAD_TOKEN') else {}
with httpx.Client(base_url=service['nomad_address'].rstrip('/') + '/v1/', headers=headers, timeout=5, trust_env=False) as client:
    for job_id in (worker['job_id'], service['job_id']):
        assert client.get(f'job/{job_id}').status_code == 404
    volumes = client.get('volumes', params={'type': 'host'})
    volumes.raise_for_status()
    assert not any(volume.get('Name', '').startswith((worker['job_id'] + '-', service['job_id'] + '-')) for volume in volumes.json() or [])
print('Required live Slice 12 acceptance verified from retained traces, observations and fresh owner CLI reads')
print(json.dumps({'worker_receipt': str(path), 'service_receipt': str(service_path),
 'worker_job_id': worker['job_id'], 'service_job_id': service['job_id'],
 'worker_allocation_id': worker['execution']['allocation_id'], 'service_allocation_id': service['allocation_id'],
 'goal_id': worker['goal_id'], 'goal_revision': worker['goal_revision'], 'goal_duration': goal['duration'], 'attempt_id': worker['attempt_id'],
 'artifact': artifact, 'worker_image': worker['image'], 'service_image': service['image'],
 'worker_sessions': worker['execution']['worker_sessions'], 'ai_operator_sessions': worker['execution']['ai_operator_sessions'],
 'observations': {stage: {key: value for key, value in outcome.items() if key != 'samples'} | {'sample_count': len(outcome['samples'])} for stage, outcome in service['observations'].items()},
 'cleanup': service['cleanup']}, indent=2))
print('Retrieved exact script after both jobs and their directories were removed')
print((service_path.parent / 'evidence-retrieved.sh').read_text())
PY
git diff --check
