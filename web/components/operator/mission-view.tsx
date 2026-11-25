'use client'

import { useState } from 'react'
import { useOperator } from './store'
import { AppHeader } from './app-header'
import { dayClock } from '@/lib/operator/format'

export function MissionView() {
  const { state, send, loaded } = useOperator()
  const mission = state.mission
  const [draftText, setDraftText] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const text = draftText ?? mission?.text ?? ''
  const dirty = draftText !== null && draftText.trim() !== (mission?.text ?? '')
  const history = [...state.missionHistory].reverse().slice(1)

  async function save() {
    setBusy(true)
    setError(null)
    const res = await send({ kind: 'mission', text: text.trim() })
    setBusy(false)
    if (!res.ok) return setError(res.error ?? 'Could not save the mission.')
    setDraftText(null)
    setSaved(true)
  }

  return (
    <div className="flex flex-1 flex-col">
      <AppHeader back={{ href: '/', label: 'Back to brief' }} />
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 pb-12 pt-5">
        <div className="flex flex-col gap-1">
          <p className="font-mono text-xs text-muted-foreground">Configure</p>
          <h1 className="text-2xl font-semibold">Mission</h1>
          <p className="text-pretty text-sm leading-relaxed text-muted-foreground">
            Standing instructions the operator reads before planning every task: what this server is for, what matters, and
            what it must never do. Tasks you send are judged against it.
          </p>
        </div>

        <form
          className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (dirty && !busy) void save()
          }}
        >
          <label htmlFor="mission" className="text-sm font-medium">
            Mission
          </label>
          <textarea
            id="mission"
            value={text}
            disabled={!loaded}
            onChange={(e) => {
              setDraftText(e.target.value)
              setSaved(false)
            }}
            rows={9}
            maxLength={2000}
            className="w-full resize-y rounded-xl border border-input bg-background p-3 font-mono text-base leading-relaxed outline-none focus-visible:ring-2 focus-visible:ring-ring md:text-sm"
          />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="font-mono text-xs text-muted-foreground">
              {mission ? `Set ${mission.by === 'install' ? 'at install' : 'by you'} · ${dayClock(mission.at)} · #${mission.seq}` : 'Not set'}
            </p>
            <div className="flex items-center gap-2">
              {dirty ? (
                <button
                  type="button"
                  onClick={() => setDraftText(null)}
                  className="h-11 rounded-xl px-4 text-sm text-muted-foreground hover:text-foreground"
                >
                  Discard
                </button>
              ) : null}
              <button
                type="submit"
                disabled={!dirty || busy}
                className="h-11 rounded-xl bg-primary px-5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
              >
                {busy ? 'Saving…' : 'Save mission'}
              </button>
            </div>
          </div>
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          {saved && !dirty ? (
            <p role="status" className="text-sm text-verified">
              Saved. The operator applies it from the next task it plans.
            </p>
          ) : null}
        </form>

        <section className="flex flex-col gap-3" aria-labelledby="horizons">
          <h2 id="horizons" className="text-sm font-medium text-muted-foreground">
            How the operator treats what you send
          </h2>
          <ul className="flex flex-col divide-y divide-border rounded-2xl border border-border bg-card">
            {[
              ['Quick', 'Say hello, what is using disk', 'Done when the answer is verified.'],
              ['Long-running', 'Record the forecast for the next three days', 'Shows progress until it finishes, then verifies.'],
              ['Standing goal', 'Keep /etc/app.env at chmod 600 always', 'Never finishes. It holds, corrects drift, or asks you.'],
            ].map(([name, example, rule]) => (
              <li key={name} className="flex flex-col gap-1 p-4">
                <p className="text-sm font-semibold">{name}</p>
                <p className="font-mono text-xs text-muted-foreground">{example}</p>
                <p className="text-pretty text-sm leading-relaxed">{rule}</p>
              </li>
            ))}
          </ul>
          <p className="text-pretty text-xs leading-relaxed text-muted-foreground">
            Any of them can pause and ask you when it needs input. They resume from where they stopped.
          </p>
        </section>

        {history.length ? (
          <section className="flex flex-col gap-3" aria-labelledby="earlier">
            <h2 id="earlier" className="text-sm font-medium text-muted-foreground">
              Earlier versions
            </h2>
            <ul className="flex flex-col gap-3">
              {history.map((m) => (
                <li key={m.seq} className="flex flex-col gap-2 rounded-xl border border-border p-3">
                  <p className="font-mono text-xs text-muted-foreground">
                    #{m.seq} · {dayClock(m.at)}
                  </p>
                  <p className="whitespace-pre-wrap text-pretty text-sm leading-relaxed text-muted-foreground">{m.text}</p>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </main>
    </div>
  )
}
