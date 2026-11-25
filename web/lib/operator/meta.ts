export const CONSOLE_VERSION = '1.6.0'

/** The VPS the operator manages. The harness runs here; workers run in containers on it. */
export const HOST = {
  host: 'vps-fra-1',
  domain: 'kj.dev',
  ip: '46.101.23.7',
  provider: 'DigitalOcean',
  region: 'Frankfurt (fra1)',
  size: '2 vCPU · 4 GB RAM · 80 GB disk',
  os: 'Ubuntu 24.04.1 LTS',
} as const

/** The persistent service the console talks to. It accepts work, starts runs, and keeps evidence. */
export const HARNESS = {
  name: 'operator-harness',
  version: '0.6.0',
  endpoint: 'https://harness.kj.dev/mcp',
  transport: 'MCP over streamable HTTP',
  unit: 'operator-harness.service',
  evidence: '/var/lib/operator/evidence',
  vault: '/etc/operator/vault',
} as const

/** What the harness launches for each run. */
export const WORKERS = {
  agent: 'Codex',
  image: 'ghcr.io/kj-dev/codex-worker:2026.11.2',
  launchers: ['Nomad', 'Docker'] as const,
  nomadJob: 'operator-run',
  workspaceRoot: '/runs',
} as const
