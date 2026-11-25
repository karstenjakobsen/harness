'use client'

import Link from 'next/link'
import { useDeferredValue, useState, type FormEvent } from 'react'
import { Check, GitBranch, Pencil, Search } from 'lucide-react'
import { useOperator } from './store'
import { AppHeader } from './app-header'
import { CatalogIcon } from './catalog-icon'
import type { CatalogConfig, Projection } from '@/lib/operator/project'
import type { CatalogAccess } from '@/lib/operator/types'
import { CATALOG_INDEX, normalizeRepo, validBranch, type CatalogEntry, type CatalogKind } from '@/lib/operator/catalog'
import { dayClock } from '@/lib/operator/format'
import { cn } from '@/lib/utils'

type Filter = 'all' | CatalogKind

const kindLabel: Record<CatalogKind, string> = { skill: 'Skill', connector: 'Connector', project: 'Project' }
const filters: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'skill', label: 'Skills' },
  { id: 'connector', label: 'Connectors' },
  { id: 'project', label: 'Projects' },
]
const accessText: Record<CatalogAccess, { label: string; detail: string }> = {
  'read-write': {
    label: 'Read and write',
    detail: 'Installs from the catalog and commits the skills it learns back to it.',
  },
  read: {
    label: 'Read only',
    detail: 'Installs from the catalog. Skills it learns stay on the VPS until you allow writes.',
  },
}

type Installed = { href: string; detail: string }

function installedOf(s: Projection, e: CatalogEntry): Installed | null {
  if (e.kind === 'skill') {
    const k = s.skillOrder.map((id) => s.skills[id]).find((x) => x.catalog.path === e.path)
    return k ? { href: `/skills/${k.id}`, detail: k.revision ? `rev ${k.revision}` : 'not active yet' } : null
  }
  if (e.kind === 'connector') {
    const c = s.connectorOrder.map((id) => s.connectors[id]).find((x) => x.catalog.path === e.path)
    return c
      ? {
          href: `/inspect/connectors/${c.id}`,
          detail: c.credential.status === 'stored' ? 'credential stored' : 'awaiting credential',
        }
      : null
  }
  const p = s.projectOrder.map((id) => s.projects[id]).find((x) => x.catalog.path === e.path)
  return p ? { href: `/inspect/projects/${p.id}`, detail: p.hostname } : null
}

export function CatalogView() {
  const { state, loaded } = useOperator()
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const q = useDeferredValue(query).trim().toLowerCase()

  const matches = (e: CatalogEntry) => !q || `${e.name}\n${e.summary}\n${e.publisher}\n${e.path}`.toLowerCase().includes(q)
  const items = CATALOG_INDEX.filter((e) => (filter === 'all' || e.kind === filter) && matches(e))
  const count = (f: Filter) => CATALOG_INDEX.filter((e) => (f === 'all' || e.kind === f) && matches(e)).length

  return (
    <div className="flex flex-1 flex-col">
      <AppHeader back={{ href: '/', label: 'Back to brief' }} />
      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-4 pb-12 pt-5">
        <div className="flex flex-col gap-1">
          <p className="font-mono text-xs text-muted-foreground">Configure</p>
          <h1 className="text-2xl font-semibold">Catalog</h1>
          <p className="text-pretty text-sm leading-relaxed text-muted-foreground">
            Skills, connectors, and projects come from a Git repository. The operator installs from it and, with write
            access, commits what it learns back.
          </p>
        </div>

        {loaded && state.catalog ? (
          <SourceCard source={state.catalog} />
        ) : (
          <div className="h-36 animate-pulse rounded-xl bg-card" aria-busy="true" />
        )}

        <section aria-labelledby="catalog-items" className="flex flex-col gap-4">
          <h2 id="catalog-items" className="sr-only">
            Catalog items
          </h2>
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div role="group" aria-label="Filter by kind" className="grid grid-cols-4 gap-1 rounded-xl bg-card p-1 md:flex">
              {filters.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  aria-pressed={filter === f.id}
                  onClick={() => setFilter(f.id)}
                  className={cn(
                    'flex min-h-11 flex-col items-center justify-center rounded-lg px-2 text-[13px] leading-tight md:flex-row md:gap-1.5 md:px-3',
                    filter === f.id ? 'bg-secondary font-medium text-foreground' : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {f.label}
                  <span className="font-mono text-[11px] text-muted-foreground">{count(f.id)}</span>
                </button>
              ))}
            </div>
            <label className="relative block md:w-72">
              <span className="sr-only">Search the catalog</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search the catalog"
                className="h-11 w-full rounded-lg border border-border bg-card pl-9 pr-3 text-base outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring md:text-sm"
              />
            </label>
          </div>

          {items.length ? (
            <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {items.map((e) => (
                <CatalogCard key={e.path} entry={e} installed={loaded ? installedOf(state, e) : null} loaded={loaded} />
              ))}
            </ul>
          ) : (
            <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
              Nothing in the catalog matches “{query.trim()}”.
            </p>
          )}
        </section>
      </main>
    </div>
  )
}

function SourceCard({ source }: { source: CatalogConfig }) {
  const [editing, setEditing] = useState(false)
  const github = source.repo.startsWith('github.com/')

  return (
    <section aria-labelledby="catalog-source" className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4 md:p-5">
      <div className="flex items-start gap-3">
        <CatalogIcon icon={github ? { brand: 'github' } : { glyph: 'archive' }} />
        <div className="min-w-0 flex-1">
          <h2 id="catalog-source" className="text-xs text-muted-foreground">
            Source repository
          </h2>
          <p className="break-all font-mono text-sm font-medium">{source.repo}</p>
        </div>
        {!editing ? (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="-mr-1 flex min-h-11 shrink-0 items-center gap-2 rounded-lg px-3 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            <Pencil className="size-4" aria-hidden="true" />
            Configure
          </button>
        ) : null}
      </div>

      {editing ? (
        <SourceForm source={source} onDone={() => setEditing(false)} />
      ) : (
        <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
          <div className="flex flex-col gap-0.5">
            <dt className="text-xs text-muted-foreground">Branch and commit</dt>
            <dd className="flex items-center gap-1.5 font-mono text-xs">
              <GitBranch className="size-3.5 text-muted-foreground" aria-hidden="true" />
              {source.branch} · {source.commit}
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-xs text-muted-foreground">Operator access</dt>
            <dd>
              <span className="font-medium">{accessText[source.access].label}.</span>{' '}
              <span className="text-pretty text-muted-foreground">{accessText[source.access].detail}</span>
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-xs text-muted-foreground">Set</dt>
            <dd className="font-mono text-xs">
              {source.by === 'owner' ? 'By you' : 'At install'} · {dayClock(source.at)} · #{source.seq}
            </dd>
          </div>
        </dl>
      )}
    </section>
  )
}

function SourceForm({ source, onDone }: { source: CatalogConfig; onDone: () => void }) {
  const { send } = useOperator()
  const [repo, setRepo] = useState(source.repo)
  const [branch, setBranch] = useState(source.branch)
  const [access, setAccess] = useState<CatalogAccess>(source.access)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const r = normalizeRepo(repo)
    if (!r) return setError('Use host/owner/name, for example github.com/kj-dev/operator-catalog.')
    if (!validBranch(branch.trim())) return setError('Branch can use letters, numbers, dots, dashes, and slashes.')
    setBusy(true)
    setError(null)
    const res = await send({ kind: 'catalog', repo: r, branch: branch.trim(), access })
    setBusy(false)
    if (!res.ok) return setError(res.error ?? 'Could not reach the operator.')
    onDone()
  }

  const field =
    'h-12 w-full rounded-lg border border-border bg-background px-3 font-mono text-base outline-none focus-visible:ring-2 focus-visible:ring-ring'

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4 border-t border-border pt-4">
      <div className="grid gap-4 md:grid-cols-[2fr_1fr]">
        <label className="flex flex-col gap-1.5 text-sm">
          Repository
          <input
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            inputMode="url"
            className={field}
          />
        </label>
        <label className="flex flex-col gap-1.5 text-sm">
          Branch
          <input
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            className={field}
          />
        </label>
      </div>
      <fieldset className="flex flex-col gap-2">
        <legend className="pb-1.5 text-sm">Operator access</legend>
        <div className="grid gap-2 md:grid-cols-2">
          {(Object.keys(accessText) as CatalogAccess[]).map((a) => (
            <label
              key={a}
              className={cn(
                'flex cursor-pointer items-start gap-3 rounded-lg border p-3',
                access === a ? 'border-foreground/40 bg-secondary' : 'border-border',
              )}
            >
              <input
                type="radio"
                name="access"
                value={a}
                checked={access === a}
                onChange={() => setAccess(a)}
                className="mt-1 size-4 accent-primary"
              />
              <span className="flex flex-col gap-0.5">
                <span className="text-sm font-medium">{accessText[a].label}</span>
                <span className="text-pretty text-xs leading-relaxed text-muted-foreground">{accessText[a].detail}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <p className="text-pretty text-xs leading-relaxed text-muted-foreground">
        The change is recorded in the event log. Demo: the operator does not clone anything, and the items below stay the
        same for any repository.
      </p>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          className="flex min-h-11 items-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-60"
        >
          {busy ? 'Saving…' : 'Save source'}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="flex min-h-11 items-center rounded-lg px-4 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground"
        >
          Cancel
        </button>
      </div>
    </form>
  )
}

function CatalogCard({ entry, installed, loaded }: { entry: CatalogEntry; installed: Installed | null; loaded: boolean }) {
  const { send } = useOperator()
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')

  const ask = async () => {
    setStatus('sending')
    const res = await send({
      kind: 'message',
      text: `Install the ${kindLabel[entry.kind].toLowerCase()} ${entry.name} from the catalog (${entry.path})`,
    })
    setStatus(res.ok ? 'sent' : 'error')
  }

  return (
    <li className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
      <div className="flex items-start gap-3">
        <CatalogIcon icon={entry.icon} />
        <div className="min-w-0 flex-1">
          <p className={cn('font-medium leading-snug', entry.kind === 'skill' && 'break-all font-mono text-sm')}>{entry.name}</p>
          <p className="truncate text-xs text-muted-foreground">
            {entry.publisher} · {/^\d/.test(entry.version) ? `v${entry.version}` : entry.version}
          </p>
        </div>
        <span className="shrink-0 rounded-full border border-border px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
          {kindLabel[entry.kind]}
        </span>
      </div>
      <p className="text-pretty text-sm leading-relaxed text-muted-foreground">{entry.summary}</p>
      <div className="mt-auto flex min-h-11 items-center justify-between gap-3 border-t border-border pt-3">
        {!loaded ? (
          <span className="text-xs text-muted-foreground">…</span>
        ) : installed ? (
          <>
            <span className="flex min-w-0 items-center gap-1.5 text-xs">
              <Check className="size-3.5 shrink-0 text-verified" aria-hidden="true" />
              <span className="text-verified">Installed</span>
              <span className="truncate font-mono text-muted-foreground">{installed.detail}</span>
            </span>
            <Link
              href={installed.href}
              className="flex min-h-11 shrink-0 items-center rounded-lg bg-secondary px-4 text-sm font-medium hover:bg-secondary/70"
            >
              Open<span className="sr-only"> {entry.name}</span>
            </Link>
          </>
        ) : status === 'sent' ? (
          <p role="status" className="text-pretty text-xs leading-relaxed">
            Sent. The operator will prepare the install and wait for you to apply it.{' '}
            <Link href="/" className="underline underline-offset-4">
              Open brief
            </Link>
          </p>
        ) : (
          <>
            <span className="text-xs text-muted-foreground">{status === 'error' ? 'Could not reach the operator.' : 'Available'}</span>
            <button
              type="button"
              onClick={ask}
              disabled={status === 'sending'}
              className="flex min-h-11 shrink-0 items-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-60"
            >
              {status === 'sending' ? 'Sending…' : 'Ask to install'}
              <span className="sr-only"> {entry.name}</span>
            </button>
          </>
        )}
      </div>
    </li>
  )
}
