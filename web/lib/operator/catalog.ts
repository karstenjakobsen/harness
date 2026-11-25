export type CatalogKind = 'skill' | 'connector' | 'project'

export type CatalogGlyph = 'sparkles' | 'hard-drive' | 'activity' | 'shield' | 'scroll' | 'globe' | 'server' | 'archive'

/** A brand mark served from theSVG, or a neutral glyph for items without a brand. */
export type CatalogIcon = { brand: string } | { glyph: CatalogGlyph }

export type CatalogEntry = {
  kind: CatalogKind
  path: string
  name: string
  summary: string
  publisher: string
  version: string
  icon: CatalogIcon
}

/** Mirrors index.json at the root of the catalog repository. Simulated for the demo. */
export const CATALOG_INDEX: CatalogEntry[] = [
  {
    kind: 'skill',
    path: 'skills/create-skill/SKILL.md',
    name: 'create-skill',
    summary: 'Builds a new skill when no existing one covers a request: procedure, fixtures from this VPS, and tests.',
    publisher: 'Operator base image',
    version: '1.4.0',
    icon: { glyph: 'sparkles' },
  },
  {
    kind: 'skill',
    path: 'skills/add-https-subdomain/SKILL.md',
    name: 'add-https-subdomain',
    summary: 'Points a subdomain at this VPS, adds a Caddy site, and checks the certificate from outside.',
    publisher: 'Learned on vps-fra-1',
    version: 'a41f9c2',
    icon: { brand: 'letsencrypt' },
  },
  {
    kind: 'skill',
    path: 'skills/reclaim-disk-space/SKILL.md',
    name: 'reclaim-disk-space',
    summary: 'Finds what is filling a mount, caps runaway logs, and asks before deleting data.',
    publisher: 'Learned on vps-fra-1',
    version: '2.1',
    icon: { glyph: 'hard-drive' },
  },
  {
    kind: 'skill',
    path: 'skills/summarize-failed-services/SKILL.md',
    name: 'summarize-failed-services',
    summary: 'Lists failed systemd units with the log lines that explain each failure.',
    publisher: 'Learned on vps-fra-1',
    version: '1.2',
    icon: { glyph: 'activity' },
  },
  {
    kind: 'skill',
    path: 'skills/postgres-restore-drill/SKILL.md',
    name: 'postgres-restore-drill',
    summary: 'Restores the latest offsite dump into a scratch database and compares row counts.',
    publisher: 'kj-dev',
    version: '0.3.0',
    icon: { brand: 'postgresql' },
  },
  {
    kind: 'skill',
    path: 'skills/harden-ssh/SKILL.md',
    name: 'harden-ssh',
    summary: 'Disables password login and root SSH, keeps your key working, and verifies from a second session.',
    publisher: 'kj-dev',
    version: '1.0.1',
    icon: { glyph: 'shield' },
  },
  {
    kind: 'skill',
    path: 'skills/docker-prune/SKILL.md',
    name: 'docker-prune',
    summary: 'Removes stopped containers and dangling images. Lists volumes but never deletes them.',
    publisher: 'kj-dev',
    version: '0.9.0',
    icon: { brand: 'docker' },
  },
  {
    kind: 'skill',
    path: 'skills/unattended-upgrades/SKILL.md',
    name: 'unattended-upgrades',
    summary: 'Turns on Ubuntu security updates and reports which ones need a reboot.',
    publisher: 'kj-dev',
    version: '1.1.0',
    icon: { brand: 'ubuntu' },
  },
  {
    kind: 'connector',
    path: 'connectors/digitalocean.yaml',
    name: 'DigitalOcean',
    summary: 'DNS records for the kj.dev zone. Reads and creates records.',
    publisher: 'kj-dev',
    version: '1.2.0',
    icon: { brand: 'digitalocean' },
  },
  {
    kind: 'connector',
    path: 'connectors/aws-s3.yaml',
    name: 'AWS S3',
    summary: 'Uploads and lists offsite backups in one bucket, and sets its lifecycle rules.',
    publisher: 'kj-dev',
    version: '1.0.3',
    icon: { brand: 'aws' },
  },
  {
    kind: 'connector',
    path: 'connectors/cloudflare.yaml',
    name: 'Cloudflare',
    summary: 'DNS and cache purge for zones hosted on Cloudflare.',
    publisher: 'kj-dev',
    version: '0.8.0',
    icon: { brand: 'cloudflare' },
  },
  {
    kind: 'connector',
    path: 'connectors/github.yaml',
    name: 'GitHub',
    summary: 'Reads app repositories and opens pull requests for config changes.',
    publisher: 'kj-dev',
    version: '1.3.0',
    icon: { brand: 'github' },
  },
  {
    kind: 'connector',
    path: 'connectors/slack.yaml',
    name: 'Slack',
    summary: 'Posts incident updates to a channel and accepts replies to decisions.',
    publisher: 'kj-dev',
    version: '0.5.2',
    icon: { brand: 'slack' },
  },
  {
    kind: 'connector',
    path: 'connectors/tailscale.yaml',
    name: 'Tailscale',
    summary: 'Reaches services on your tailnet without opening public ports.',
    publisher: 'kj-dev',
    version: '0.4.0',
    icon: { brand: 'tailscale' },
  },
  {
    kind: 'project',
    path: 'projects/api.yaml',
    name: 'kj API',
    summary: 'kj-api behind Caddy at api.kj.dev, upstream localhost:8080.',
    publisher: 'kj-dev',
    version: '2.14.1',
    icon: { glyph: 'server' },
  },
  {
    kind: 'project',
    path: 'projects/node-app.yaml',
    name: 'Node app',
    summary: 'Template for a Node.js service under systemd with a Caddy site and health check.',
    publisher: 'kj-dev',
    version: '1.0.0',
    icon: { brand: 'nodejs' },
  },
  {
    kind: 'project',
    path: 'projects/static-site.yaml',
    name: 'Static site',
    summary: 'Template for a static site served by Caddy from /srv, deployed from a Git repo.',
    publisher: 'kj-dev',
    version: '1.1.0',
    icon: { glyph: 'globe' },
  },
  {
    kind: 'project',
    path: 'projects/redis-cache.yaml',
    name: 'Redis cache',
    summary: 'Local Redis bound to 127.0.0.1 with memory limits and persistence off.',
    publisher: 'kj-dev',
    version: '0.6.0',
    icon: { brand: 'redis' },
  },
]

export const brandIconUrl = (slug: string) =>
  `https://cdn.jsdelivr.net/gh/glincker/thesvg@main/public/icons/${encodeURIComponent(slug)}/default.svg`

/** Accepts host/owner/name with or without https:// and .git. Returns null when the shape is wrong. */
export function normalizeRepo(input: string): string | null {
  const r = input
    .trim()
    .replace(/^https?:\/\//i, '')
    .replace(/\.git$/i, '')
    .replace(/\/+$/, '')
  if (r.length > 200) return null
  return /^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}\/[\w.-]+\/[\w.-]+$/i.test(r) ? r : null
}

export function validBranch(b: string): boolean {
  return b.length > 0 && b.length <= 100 && /^[\w./-]+$/.test(b) && !b.includes('..') && !/^[-/]|\/$/.test(b)
}

export const shortRepo = (repo: string) => repo.replace(/^[^/]+\//, '')
