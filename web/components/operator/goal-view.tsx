'use client'

import Link from 'next/link'
import { useState } from 'react'
import { ChevronRight, MessageSquareReply } from 'lucide-react'
import { useOperator } from './store'
import { AppHeader } from './app-header'
import { Evidence } from './home-view'
import { goalText, goalTone, goalWord } from './goal-status'
import { openQuestion, type Goal, type GoalQuestion } from '@/lib/operator/project'
import type { GoalTerm } from '@/lib/operator/types'
import { clock, dayClock } from '@/lib/operator/format'
import { cn } from '@/lib/utils'

export function GoalView({ id }: { id: string }) {
  const { state, loaded } = useOperator()
  const goal = state.goals[id]

  return (
    <div className="flex flex-1 flex-col">
      <AppHeader back={{ href: '/goals', label: 'All goals' }} />
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-7 px-4 pb-10 pt-5">
        {!loaded ? (
          <div className="h-60 animate-pulse rounded-xl bg-card" aria-busy="true" />
        ) : goal ? (
          <GoalDetail goal={goal} taskTitle={goal.task ? state.tasks[goal.task]?.title : undefined} />
        ) : (
          <p className="text-sm text-muted-foreground">
            This goal is not in the harness log.{' '}
            <Link href="/goals" className="text-foreground underline underline-offset-4">
              See all goals
            </Link>
          </p>
        )}
      </main>
    </div>
  )
}

function GoalDetail({ goal, taskTitle }: { goal: Goal; taskTitle?: string }) {
  const q = openQuestion(goal)
  const agreed = goal.terms.filter((t) => t.status === 'agreed')
  const proposed = goal.terms.filter((t) => t.status === 'proposed')
  const declined = goal.terms.filter((t) => t.status === 'declined')
  const answered = goal.questions.filter((x) => x.answer)
  const checks = [...goal.checks].reverse()

  return (
    <>
      <header className="flex flex-col gap-3">
        <p className="font-mono text-xs text-muted-foreground">Standing goal · since {dayClock(goal.createdAt)}</p>
        <h1 className="text-pretty text-2xl font-semibold leading-tight tracking-tight">{goal.text}</h1>
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <span className={cn('size-2.5 rounded-full', goal.dropped ? 'bg-muted-foreground' : goalTone[goal.status])} aria-hidden="true" />
          {goal.dropped ? (
            <span className="text-muted-foreground">Dropped {dayClock(goal.dropped.at)}. No more checks run.</span>
          ) : (
            <>
              <span className={cn('font-medium', goalText[goal.status])}>{goalWord[goal.status]}</span>
              {goal.checkedAt ? <span className="text-muted-foreground">· last checked {clock(goal.checkedAt)}</span> : null}
            </>
          )}
        </p>
      </header>

      {q ? <AnswerQuestion question={q} terms={goal.terms} /> : null}

      <Section title="What you asked">
        {goal.asked ? (
          <figure className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4">
            <blockquote className="text-pretty text-base leading-relaxed">{`\u201C${goal.asked}\u201D`}</blockquote>
            <figcaption className="font-mono text-xs text-muted-foreground">You · {dayClock(goal.createdAt)}</figcaption>
          </figure>
        ) : (
          <p className="text-sm text-muted-foreground">The operator set this goal up. You have not asked for it in your own words.</p>
        )}
      </Section>

      <Section title="Current definition" note="This is the goal the next check runs against.">
        {agreed.length ? (
          <TermList terms={agreed} />
        ) : (
          <p className="text-sm text-muted-foreground">Nothing is agreed yet.</p>
        )}
      </Section>

      {proposed.length ? (
        <Section title="Proposed by the operator" note="Its reading of your request. Not agreed until you answer.">
          <TermList terms={proposed} />
        </Section>
      ) : null}

      {declined.length ? (
        <Section title="Not part of this goal">
          <TermList terms={declined} />
        </Section>
      ) : null}

      {answered.length ? (
        <Section title="Your answers">
          <ul className="flex flex-col gap-2">
            {answered.map((a) => (
              <li key={a.requestId} className="flex flex-col gap-1 rounded-xl border border-border bg-card p-4">
                <p className="text-pretty text-sm text-muted-foreground">{a.question}</p>
                <p className="text-pretty text-sm font-medium">{a.answer?.label ?? a.answer?.text}</p>
                <p className="font-mono text-xs text-muted-foreground">
                  You · {a.answer ? clock(a.answer.at) : ''} · event #{a.answer?.seq}
                </p>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      <Section title="Latest check" note="Each check runs in a fresh worker. The harness keeps the result after the worker exits.">
        {goal.command ? (
          <div className="flex flex-col gap-3">
            <p className="text-pretty text-sm">
              <span className={cn('font-medium', goalText[goal.status])}>{goalWord[goal.status]}</span>
              {goal.observed ? ` · ${goal.observed}` : ''}
            </p>
            <Evidence command={goal.command} output={goal.output} seq={goal.checkedSeq} />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No check has run yet.</p>
        )}
      </Section>

      {checks.length > 1 ? (
        <Section title="Check history">
          <ol className="flex flex-col divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
            {checks.map((c) => (
              <li key={c.seq}>
                <details>
                  <summary className="flex min-h-12 cursor-pointer items-center gap-3 px-4 py-2.5">
                    <span className="w-11 shrink-0 font-mono text-xs text-muted-foreground">{clock(c.at)}</span>
                    <span className={cn('size-2 shrink-0 rounded-full', goalTone[c.status])} aria-hidden="true" />
                    <span className="min-w-0 flex-1 text-pretty text-sm">{c.observed}</span>
                  </summary>
                  <div className="px-4 pb-4">
                    <Evidence command={c.command} output={c.output} seq={c.seq} />
                  </div>
                </details>
              </li>
            ))}
          </ol>
        </Section>
      ) : null}

      {goal.task ? (
        <Section title="Set up by">
          <Link
            href={`/work/${goal.task}`}
            className="flex min-h-14 items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 hover:bg-secondary/60"
          >
            <span className="min-w-0 flex-1 text-pretty text-sm">{taskTitle ?? 'The task that set up this goal'}</span>
            <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          </Link>
        </Section>
      ) : null}
    </>
  )
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h2 className="text-sm font-semibold">{title}</h2>
        {note ? <p className="text-pretty text-xs leading-relaxed text-muted-foreground">{note}</p> : null}
      </div>
      {children}
    </section>
  )
}

const originLabel: Record<GoalTerm['origin'], string> = { owner: 'You asked', operator: 'Operator' }

function TermList({ terms }: { terms: GoalTerm[] }) {
  return (
    <dl className="flex flex-col divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
      {terms.map((t) => (
        <div
          key={t.id}
          className={cn('flex flex-col gap-1 px-4 py-3', t.status === 'proposed' && 'border-l-0 bg-well', t.status === 'declined' && 'opacity-70')}
        >
          <div className="flex items-center justify-between gap-3">
            <dt className="text-xs text-muted-foreground">{t.label}</dt>
            <TermBadge term={t} />
          </div>
          <dd className={cn('text-pretty text-sm', t.status === 'declined' && 'line-through')}>{t.value}</dd>
        </div>
      ))}
    </dl>
  )
}

function TermBadge({ term }: { term: GoalTerm }) {
  if (term.status === 'proposed')
    return (
      <span className="shrink-0 rounded-full border border-dashed border-attention/70 px-2 py-0.5 text-[11px] text-attention">
        Proposed
      </span>
    )
  if (term.status === 'declined')
    return <span className="shrink-0 rounded-full bg-secondary px-2 py-0.5 text-[11px] text-muted-foreground">Declined</span>
  return (
    <span className="shrink-0 rounded-full bg-verified/15 px-2 py-0.5 text-[11px] text-verified">
      {term.origin === 'owner' ? originLabel.owner : 'Agreed'}
    </span>
  )
}

function AnswerQuestion({ question, terms }: { question: GoalQuestion; terms: GoalTerm[] }) {
  const { send } = useOperator()
  const recommended = question.options.find((o) => o.recommended)?.id
  const [choice, setChoice] = useState<string | undefined>(recommended)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const about = terms.filter((t) => question.about.includes(t.id))

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const words = text.trim()
    if (!words && !choice) return setError('Pick an option or write an answer.')
    setBusy(true)
    setError(undefined)
    const r = await send({ kind: 'goal-answer', requestId: question.requestId, ...(words ? { text: words } : { optionId: choice }) })
    setBusy(false)
    if (!r.ok) setError(r.error ?? 'The harness did not accept the answer.')
    else setText('')
  }

  return (
    <section aria-labelledby="question-h" className="rise flex flex-col gap-4 rounded-2xl border border-attention/40 bg-card p-4">
      <p className="flex items-center gap-1.5 text-xs font-medium text-attention">
        <MessageSquareReply className="size-3.5" aria-hidden="true" />
        Question for you · asked {clock(question.at)}
      </p>
      <h2 id="question-h" className="text-pretty text-base font-medium leading-snug">
        {question.question}
      </h2>
      {about.length ? (
        <p className="text-xs text-muted-foreground">About: {about.map((t) => t.label.toLowerCase()).join(', ')}</p>
      ) : null}

      <form onSubmit={submit} className="flex flex-col gap-3">
        <fieldset className="flex flex-col gap-2" disabled={busy}>
          <legend className="sr-only">Your answer</legend>
          {question.options.map((o) => (
            <label
              key={o.id}
              className={cn(
                'flex min-h-11 cursor-pointer gap-3 rounded-xl border p-3 transition-colors',
                choice === o.id && !text.trim() ? 'border-foreground/60 bg-secondary' : 'border-border hover:bg-secondary/60',
              )}
            >
              <input
                type="radio"
                name={`answer-${question.requestId}`}
                value={o.id}
                checked={choice === o.id}
                onChange={() => {
                  setChoice(o.id)
                  setText('')
                }}
                className="mt-1 size-4 shrink-0 accent-[var(--color-foreground)]"
              />
              <span className="flex min-w-0 flex-col gap-1">
                <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
                  {o.label}
                  {o.recommended ? (
                    <span className="rounded-full bg-secondary px-2 py-0.5 text-[11px] font-normal text-muted-foreground">Suggested</span>
                  ) : null}
                </span>
                <span className="text-pretty text-sm leading-relaxed text-muted-foreground">{o.consequence}</span>
              </span>
            </label>
          ))}
          <label className="flex flex-col gap-1.5 pt-1">
            <span className="text-xs text-muted-foreground">Or answer in your own words</span>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={2}
              maxLength={2000}
              placeholder="For example: keep root ownership, but ask before fixing"
              className="w-full resize-none rounded-xl border border-border bg-well px-3 py-2.5 text-base leading-relaxed placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </label>
        </fieldset>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={busy}
          className="flex min-h-11 items-center justify-center rounded-lg bg-attention px-4 text-sm font-medium text-attention-foreground hover:opacity-90 disabled:opacity-60"
        >
          {busy ? 'Sending' : text.trim() ? 'Send answer' : 'Answer'}
        </button>
        <p className="text-pretty text-xs leading-relaxed text-muted-foreground">
          Checks keep running while this is open. Your answer changes the definition the next check uses.
        </p>
      </form>
    </section>
  )
}
