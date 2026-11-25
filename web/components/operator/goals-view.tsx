'use client'

import Link from 'next/link'
import { ChevronRight, MessageSquareReply } from 'lucide-react'
import { useOperator } from './store'
import { AppHeader } from './app-header'
import { Composer } from './composer'
import { goalText, goalTone, goalWord } from './goal-status'
import { openQuestion, type Goal } from '@/lib/operator/project'
import { clock, dayClock } from '@/lib/operator/format'
import { cn } from '@/lib/utils'

export function GoalsView() {
  const { state, loaded } = useOperator()
  const goals = state.goalOrder.map((id) => state.goals[id])
  const active = goals.filter((g) => !g.dropped)
  const dropped = goals.filter((g) => g.dropped)

  return (
    <div className="flex flex-1 flex-col">
      <AppHeader />
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 pb-8 pt-5">
        <header className="flex flex-col gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">Goals</h1>
          <p className="text-pretty text-sm leading-relaxed text-muted-foreground">
            Each goal stays here before, during and between runs. A fresh worker runs each check, and the harness keeps
            every result.
          </p>
        </header>

        {!loaded ? (
          <div className="h-40 animate-pulse rounded-xl bg-card" aria-busy="true" />
        ) : active.length ? (
          <GoalList goals={active} />
        ) : (
          <p className="rounded-xl border border-dashed border-border p-5 text-sm text-muted-foreground">
            No standing goals yet. Ask the operator to keep something true, for example a file mode or a service being up.
          </p>
        )}

        {dropped.length ? (
          <section aria-labelledby="dropped-h" className="flex flex-col gap-3">
            <h2 id="dropped-h" className="text-sm font-semibold">
              Dropped
            </h2>
            <GoalList goals={dropped} />
          </section>
        ) : null}
      </main>
      <Composer />
    </div>
  )
}

function GoalList({ goals }: { goals: Goal[] }) {
  return (
    <ul className="flex flex-col divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
      {goals.map((g) => {
        const q = openQuestion(g)
        const proposed = g.terms.filter((t) => t.status === 'proposed').length
        return (
          <li key={g.id}>
            <Link href={`/goals/${g.id}`} className="flex min-h-16 items-center gap-3 px-4 py-3 hover:bg-secondary/60">
              <span className={cn('size-2.5 shrink-0 rounded-full', g.dropped ? 'bg-muted-foreground' : goalTone[g.status])} aria-hidden="true" />
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="text-pretty text-sm font-medium leading-snug">{g.text}</span>
                <span className="text-xs text-muted-foreground">
                  {g.dropped ? (
                    `Dropped ${dayClock(g.dropped.at)}`
                  ) : (
                    <>
                      <span className={goalText[g.status]}>{goalWord[g.status]}</span>
                      {g.checkedAt ? ` · checked ${clock(g.checkedAt)}` : ''}
                      {proposed ? ` · ${proposed} proposed ${proposed === 1 ? 'term' : 'terms'}` : ''}
                    </>
                  )}
                </span>
                {q ? (
                  <span className="flex items-center gap-1.5 self-start rounded-full bg-attention/15 px-2.5 py-1 text-xs font-medium text-attention">
                    <MessageSquareReply className="size-3.5" aria-hidden="true" />
                    Question for you
                  </span>
                ) : null}
              </span>
              <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            </Link>
          </li>
        )
      })}
    </ul>
  )
}
