'use client'

import Link from 'next/link'
import { usePathname, useSearchParams } from 'next/navigation'
import { Boxes, Brain, Compass, Inbox, KeyRound, Server, Sparkles, Store, Target, Terminal, type LucideIcon } from 'lucide-react'
import { useOperator } from './store'
import type { Projection } from '@/lib/operator/project'
import { HOST } from '@/lib/operator/meta'
import { cn } from '@/lib/utils'

type Item = {
  href: string
  label: string
  icon: LucideIcon
  active: (path: string, tab: string | null) => boolean
  count?: (s: Projection) => number
}

const groups: { label?: string; items: Item[] }[] = [
  {
    items: [
      { href: '/', label: 'Brief', icon: Inbox, active: (p) => p === '/' || p.startsWith('/work/') },
      { href: '/goals', label: 'Goals', icon: Target, active: (p) => p.startsWith('/goals') },
    ],
  },
  {
    label: 'Inspect',
    items: [
      {
        href: '/inspect',
        label: 'Memory',
        icon: Brain,
        active: (p, t) => (p === '/inspect' && !t) || p.startsWith('/inspect/memory'),
        count: (s) => s.memoryOrder.length,
      },
      {
        href: '/inspect?tab=skills',
        label: 'Skills',
        icon: Sparkles,
        active: (p, t) => (p === '/inspect' && t === 'skills') || /\/skills?(\/|$)/.test(p),
        count: (s) => s.skillOrder.length,
      },
      {
        href: '/inspect?tab=connectors',
        label: 'Connectors',
        icon: KeyRound,
        active: (p, t) => (p === '/inspect' && t === 'connectors') || /\/connectors?(\/|$)/.test(p),
        count: (s) => s.connectorOrder.length,
      },
      {
        href: '/inspect?tab=projects',
        label: 'Projects',
        icon: Boxes,
        active: (p, t) => (p === '/inspect' && t === 'projects') || /\/projects?(\/|$)/.test(p),
        count: (s) => s.projectOrder.length,
      },
    ],
  },
  {
    label: 'Configure',
    items: [
      { href: '/mission', label: 'Mission', icon: Compass, active: (p) => p.startsWith('/mission') },
      { href: '/catalog', label: 'Catalog', icon: Store, active: (p) => p.startsWith('/catalog') },
      { href: '/harness', label: 'Harness', icon: Server, active: (p) => p.startsWith('/harness') },
    ],
  },
]

export function SideNav() {
  const path = usePathname()
  const tab = useSearchParams().get('tab')
  const { state, loaded, connection } = useOperator()
  const live = connection === 'live'

  return (
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-60 flex-col border-r border-border bg-card/40 lg:flex">
      <Link href="/" className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-5">
        <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Terminal className="size-4" aria-hidden="true" />
        </span>
        <span className="flex min-w-0 flex-col leading-tight">
          <span className="text-sm font-semibold">Operator</span>
          <span className="truncate font-mono text-xs text-muted-foreground">
            {HOST.host} · {HOST.domain}
          </span>
        </span>
      </Link>
      <nav aria-label="Main" className="flex flex-1 flex-col gap-5 overflow-y-auto px-3 py-4">
        {groups.map((g, i) => (
          <div key={g.label ?? i} className="flex flex-col gap-0.5">
            {g.label ? (
              <p className="px-3 pb-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{g.label}</p>
            ) : null}
            {g.items.map((it) => {
              const on = it.active(path, tab)
              return (
                <Link
                  key={it.href}
                  href={it.href}
                  aria-current={on ? 'page' : undefined}
                  className={cn(
                    'flex h-10 items-center gap-3 rounded-lg px-3 text-sm',
                    on ? 'bg-secondary font-medium text-foreground' : 'text-muted-foreground hover:bg-secondary/60 hover:text-foreground',
                  )}
                >
                  <it.icon className="size-4 shrink-0" aria-hidden="true" />
                  <span className="flex-1">{it.label}</span>
                  {it.count && loaded ? (
                    <span className="font-mono text-xs text-muted-foreground">{it.count(state)}</span>
                  ) : null}
                  {it.href === '/harness' && loaded ? (
                    <span
                      className={cn('size-2 rounded-full', live ? 'bg-verified' : 'bg-attention')}
                      aria-label={live ? 'Connected' : 'Not connected'}
                    />
                  ) : null}
                </Link>
              )
            })}
          </div>
        ))}
      </nav>
    </aside>
  )
}
