'use client'

import { Network, Plug, Unplug } from 'lucide-react'
import { useOperator } from './store'
import { AppHeader } from './app-header'
import { HARNESS, HOST, WORKERS } from '@/lib/operator/meta'
import { activeRuns } from '@/lib/operator/runs'
import { clock, dayClock } from '@/lib/operator/format'
import { cn } from '@/lib/utils'

type Row = { k: string; v: string; mono?: boolean }

export function HarnessView() {
  const { state, events, loaded, connection, connectedSince, disconnect, reconnect } = useOperator()
  const live = connection === 'live'
  const pending = connection === 'connecting' || connection === 'reconnecting'
  const first = events[0]
  const last = events[events.length - 1]

  const title = live ? 'Connected to the harness' : connection === 'offline' ? 'Disconnected' : 'Connecting'
  const detail = live
    ? connectedSince
      ? `Receiving updates since ${clock(connectedSince)}.`
      : 'Receiving updates.'
    : connection === 'offline'
      ? `This console stopped receiving updates at #${last?.seq ?? 0}. Runs on the harness may still be active.`
      : `Opening a connection to ${HARNESS.endpoint}.`

  const harness: Row[] = [
    { k: 'Service', v: `${HARNESS.name} ${HARNESS.version}`, mono: true },
    { k: 'Endpoint', v: HARNESS.endpoint, mono: true },
    { k: 'Protocol', v: HARNESS.transport },
    { k: 'Evidence store', v: HARNESS.evidence, mono: true },
    { k: 'Vault', v: `${HARNESS.vault} (root-only)`, mono: true },
    { k: 'First event', v: first ? `#${first.seq} · ${dayClock(first.at)}` : '…', mono: true },
    { k: 'Latest event', v: last ? `#${last.seq} · ${dayClock(last.at)}` : '…', mono: true },
  ]
  const workers: Row[] = [
    { k: 'Agent', v: WORKERS.agent },
    { k: 'Image', v: WORKERS.image, mono: true },
    { k: 'Launched by', v: `${WORKERS.launchers.join(' or ')} (job ${WORKERS.nomadJob})` },
    { k: 'Per run', v: 'Fresh container, own workspace, only the tools assigned to that run' },
    { k: 'After exit', v: 'Container removed. Result and evidence stay on the harness.' },
  ]
  const host: Row[] = [
    { k: 'Hostname', v: `${HOST.host}.${HOST.domain}`, mono: true },
    { k: 'Public IP', v: HOST.ip, mono: true },
    { k: 'Provider', v: `${HOST.provider}, ${HOST.region}` },
    { k: 'Size', v: HOST.size },
    { k: 'OS', v: HOST.os },
  ]
  const activity: Row[] = [
    { k: 'Workers running', v: String(activeRuns(state)) },
    { k: 'Tasks', v: String(state.taskOrder.length) },
    { k: 'Incidents', v: String(state.incidentOrder.length) },
    { k: 'Skills', v: String(state.skillOrder.length) },
  ]

  return (
    <div className="flex flex-1 flex-col">
      <AppHeader back={{ href: '/', label: 'Back to brief' }} />
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 pb-12 pt-5">
        <div className="flex flex-col gap-1">
          <p className="font-mono text-xs text-muted-foreground">Configure</p>
          <h1 className="text-2xl font-semibold">Harness</h1>
          <p className="text-pretty text-sm leading-relaxed text-muted-foreground">
            The harness is the persistent service on {HOST.host}. It accepts work from this console, launches a fresh{' '}
            {WORKERS.agent} worker for each run, and keeps the result and evidence after the worker exits.
          </p>
        </div>

        <section aria-labelledby="harness-status" className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4 md:p-5">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
            <div className="flex min-w-0 flex-1 items-center gap-3">
              <span className="relative flex size-12 shrink-0 items-center justify-center rounded-xl bg-secondary ring-1 ring-border">
                <Network className="size-6" aria-hidden="true" />
                <span
                  className={cn(
                    'absolute -right-0.5 -top-0.5 size-3 rounded-full ring-2 ring-card',
                    live ? 'bg-verified' : 'bg-attention',
                    pending && 'animate-pulse',
                  )}
                  aria-hidden="true"
                />
              </span>
              <div className="min-w-0" role="status" aria-live="polite">
                <h2 id="harness-status" className="text-lg font-semibold">
                  {title}
                </h2>
                <p className="text-pretty text-sm text-muted-foreground">{detail}</p>
              </div>
            </div>
            {live ? (
              <button
                type="button"
                onClick={disconnect}
                className="flex min-h-11 items-center justify-center gap-2 rounded-lg border border-border px-4 text-sm font-medium hover:bg-secondary"
              >
                <Unplug className="size-4" aria-hidden="true" />
                Disconnect
              </button>
            ) : (
              <button
                type="button"
                onClick={reconnect}
                disabled={pending}
                className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-60"
              >
                <Plug className="size-4" aria-hidden="true" />
                {pending ? 'Connecting…' : 'Connect'}
              </button>
            )}
          </div>
          <p className="text-pretty border-t border-border pt-3 text-xs leading-relaxed text-muted-foreground">
            Disconnecting only stops this console from receiving updates. The harness keeps accepting work, and runs that
            are active keep going. Connect again to see their status and evidence; the console replays every event it
            missed. Worker status for each run is on its task, under Run details.
          </p>
        </section>

        {loaded ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Info title="Harness" rows={harness} />
            <Info title="Workers" rows={workers} />
            <Info title="Host" rows={host} />
            <Info title="Activity" rows={activity} />
          </div>
        ) : (
          <div className="h-48 animate-pulse rounded-xl bg-card" aria-busy="true" />
        )}
      </main>
    </div>
  )
}

function Info({ title, rows }: { title: string; rows: Row[] }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-medium text-muted-foreground">{title}</h2>
      <dl className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
        {rows.map((r) => (
          <div key={r.k} className="flex items-baseline justify-between gap-4 px-4 py-2.5 text-sm">
            <dt className="shrink-0 text-muted-foreground">{r.k}</dt>
            <dd className={cn('min-w-0 break-words text-right', r.mono && 'font-mono text-xs')}>{r.v}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
