'use client'

import Link from 'next/link'
import { useOperator } from './store'
import { CONSOLE_VERSION, HARNESS, HOST, WORKERS } from '@/lib/operator/meta'
import { shortRepo } from '@/lib/operator/catalog'

export function AppFooter() {
  const { state, loaded } = useOperator()
  const c = state.catalog
  const rows: { k: string; v: string; href?: string }[] = [
    { k: 'Console', v: `v${CONSOLE_VERSION}` },
    { k: 'Harness', v: `${HARNESS.name} ${HARNESS.version} on ${HOST.host}`, href: '/harness' },
    { k: 'Workers', v: `${WORKERS.agent}, one container per run` },
    { k: 'Catalog', v: loaded && c ? `${shortRepo(c.repo)}@${c.branch} · ${c.commit}` : '…', href: '/catalog' },
    { k: 'Event log', v: loaded ? `#${state.lastSeq}` : '…' },
  ]

  return (
    <footer className="border-t border-border pb-[env(safe-area-inset-bottom)]">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-4 text-xs text-muted-foreground lg:flex-row lg:items-center lg:justify-between">
        <dl className="grid grid-cols-[5.5rem_1fr] gap-x-3 gap-y-1.5 font-mono sm:flex sm:flex-wrap sm:gap-x-6">
          {rows.map((r) => (
            <div key={r.k} className="contents sm:flex sm:gap-2">
              <dt>{r.k}</dt>
              <dd className="min-w-0 truncate text-foreground">
                {r.href ? (
                  <Link href={r.href} className="underline decoration-border underline-offset-4 hover:decoration-foreground">
                    {r.v}
                  </Link>
                ) : (
                  r.v
                )}
              </dd>
            </div>
          ))}
        </dl>
        <p className="text-pretty">Public demo. The operator and VPS are simulated.</p>
      </div>
    </footer>
  )
}
