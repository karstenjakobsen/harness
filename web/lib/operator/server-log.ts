import { createHash, randomUUID } from 'node:crypto'
import { draft, type CatalogAccess, type EventDraft, type OperatorEvent, type TaskHorizon } from './types'
import {
  BACKUP_TASK,
  DISK_DECISION,
  DISK_INCIDENT,
  DISK_REV,
  S3_REQUEST,
  S3_CONNECTOR,
  liveScript,
  permissionAnswer,
  permissionQuestion,
  permissionTerms,
  seedHistory,
} from './scenario'
import { replay } from './project'

type Pending = { due: number; ev: EventDraft }

const WORD_NUMBERS: Record<string, number> = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7 }

function parseCount(text: string) {
  const m = text.match(/\b(\d+|one|two|three|four|five|six|seven)\s+(?:days?|hours?|weeks?)\b/i)
  if (!m) return undefined
  return /^\d+$/.test(m[1]) ? Number(m[1]) : WORD_NUMBERS[m[1].toLowerCase()]
}

export function classifyHorizon(text: string): TaskHorizon {
  if (/\b(always|at all times|make sure|ensure|never|stays?|remains?|keep\b.*\b(at|on|off|running|up|below|above|under))\b/i.test(text))
    return 'standing'
  if (parseCount(text) || /\b(over the next|monitor|watch|track|collect|record)\b/i.test(text)) return 'long'
  return 'short'
}

function forecastNote(place: string, k: number) {
  const day = new Date(Date.now() + k * 86_400_000).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
  const rows = [
    ['7°C', 'light rain'],
    ['5°C', 'overcast'],
    ['9°C', 'sunny spells'],
    ['4°C', 'sleet'],
    ['8°C', 'fog clearing'],
    ['6°C', 'showers'],
    ['10°C', 'clear'],
  ]
  const [t, c] = rows[(k - 1) % rows.length]
  return `${day} ${place}: ${t}, ${c}`
}

class OperatorLog {
  readonly epoch = randomUUID()
  private events: OperatorEvent[] = []
  private pending: Pending[] = []
  private started = false
  private counter = 0
  /** Secret values live only here: never in events, never returned to any client. */
  private vault = new Map<string, Record<string, string>>()
  /** Tasks paused on a question: what to run once the owner replies. */
  private onReply = new Map<string, (reply: string) => [number, EventDraft][]>()

  constructor() {
    for (const d of seedHistory(Date.now())) this.append(d)
  }

  private append(d: EventDraft): OperatorEvent {
    const e = { ...d, seq: this.events.length + 1, at: d.at ?? new Date().toISOString() } as OperatorEvent
    this.events.push(e)
    return e
  }

  private schedule(items: [number, EventDraft][]) {
    const now = Date.now()
    for (const [delay, ev] of items) this.pending.push({ due: now + delay, ev })
    this.pending.sort((a, b) => a.due - b.due)
  }

  private flush() {
    const now = Date.now()
    while (this.pending.length && this.pending[0].due <= now) {
      const p = this.pending.shift()!
      const task = p.ev.ref.task
      if (task && this.state().tasks[task]?.stopped) continue
      this.append(p.ev)
    }
  }

  private state() {
    return replay(this.events)
  }

  /** The overnight task keeps running from the moment the owner first connects. */
  begin() {
    if (this.started) return
    this.started = true
    this.schedule(liveScript())
  }

  readAfter(seq: number) {
    this.flush()
    return this.events.filter((e) => e.seq > seq)
  }

  private nextTaskId() {
    this.counter += 1
    return `t-new-${this.counter}`
  }

  message(text: string, taskId?: string) {
    this.flush()
    const s = this.state()
    const task = taskId ? s.tasks[taskId] : undefined

    if (task) {
      if (task.waiting?.on === 'reply') {
        this.append(draft('owner.message', { task: task.id }, { text, intent: 'reply' }))
        const resume = this.onReply.get(task.id)
        if (resume) {
          this.onReply.delete(task.id)
          this.schedule([[600, draft('task.resumed', { task: task.id }, { reason: 'You answered.' })], ...resume(text)])
          return
        }
        if (/^\s*(apply|go|yes|ok|do it|confirm)/i.test(text)) {
          this.schedule([
            [600, draft('task.resumed', { task: task.id }, { reason: 'You confirmed the change.' })],
            [2_500, draft('task.step', { task: task.id }, { summary: 'Applied the change and reloaded the affected service', command: 'systemctl reload <unit>', output: 'ok' })],
            [4_500, draft('task.verification', { task: task.id }, { result: 'passed', method: 'independent', check: 'Re-read the live configuration and confirmed the service is active.', command: 'systemctl is-active <unit>', output: 'active' })],
            [5_000, draft('task.completed', { task: task.id }, { summary: 'Change applied and confirmed.' })],
          ])
        } else {
          this.schedule([[1_500, draft('operator.message', { task: task.id }, { text: 'Noted. I will hold the change. Reply "apply" when you want it made.' })]])
        }
        return
      }
      this.append(draft('owner.message', { task: task.id }, { text, intent: 'steer' }))
      this.schedule([
        [1_500, draft('operator.message', { task: task.id }, { text: `Noted for "${task.title}". I will apply that from the next step.` })],
      ])
      return
    }

    const id = this.nextTaskId()
    const horizon = classifyHorizon(text)
    const isConfig = /\b(change|set|enable|disable|config|configure|update|install|increase|lower|raise|turn|allow|block|open|close)\b/i.test(text)
    this.append(draft('owner.message', { task: id }, { text, intent: isConfig || horizon === 'standing' ? 'config' : 'ask' }))
    this.append(draft('task.received', { task: id }, { title: text.length > 72 ? `${text.slice(0, 70)}…` : text, source: 'owner', horizon }))

    if (horizon === 'standing') return this.startStanding(id, text)
    if (horizon === 'long') return this.startLong(id, text)

    if (isConfig) {
      this.schedule([
        [1_200, draft('task.understood', { task: id }, { interpretation: `Configuration change: ${text}`, plan: ['Read the current configuration', 'Show you the exact change', 'Apply only after you confirm', 'Verify the service afterwards'] })],
        [3_000, draft('task.step', { task: id }, { summary: 'Read the current configuration', routine: true })],
        [4_500, draft('operator.message', { task: id }, { text: 'I have the change ready and have not applied it. Reply "apply" on this task to go ahead.' })],
        [4_600, draft('task.waiting', { task: id }, { on: 'reply' })],
      ])
      return
    }

    const answer = this.cannedAnswer(text)
    this.schedule([
      [1_200, draft('task.understood', { task: id }, { interpretation: `Answer: ${text}`, plan: ['Read the live state', 'Answer', 'Re-check the values I quote'] })],
      [3_000, draft('task.step', { task: id }, { summary: 'Read the live state', command: answer.command, output: answer.output, routine: true })],
      [4_500, draft('task.answered', { task: id }, { text: answer.text })],
      [6_000, draft('task.verification', { task: id }, { result: 'passed', method: 'independent', check: 'Re-ran the source command and compared the values quoted in the answer.', command: answer.command, output: answer.output })],
      [6_300, draft('task.completed', { task: id }, { summary: 'Answered.' })],
    ])
  }

  /** Standing goal: turn the request into a check, hold it, and ask when it cannot be checked. */
  private startStanding(id: string, text: string) {
    const ref = { task: id }
    const goal = `g-${id}`
    const path = text.match(/(\/[\w.\/-]+)/)?.[1]
    const mode = text.match(/\b(?:chmod\s*)?([0-7]{3,4})\b/)?.[1]
    const plan = ['Turn this into a check I can run', 'Run it now and correct any drift', 'Re-check every 15 minutes', 'Ask you if I cannot keep it true']

    if (path && mode) {
      const check = `stat -c '%a %U:%G %n' ${path}`
      this.schedule([
        [1_200, draft('task.understood', ref, { interpretation: `Standing goal: ${path} stays at mode ${mode}. I correct drift on sight and tell you when it happens.`, plan })],
        [2_800, draft('goal.standing', { goal, task: id }, { text: `${path} stays at mode ${mode}`, check, asked: text, terms: permissionTerms(mode) })],
        [4_200, draft('goal.checked', { goal }, { status: 'drift', observed: `Mode 644 when I started, expected ${mode}`, command: check, output: `644 root:root ${path}` })],
        [5_600, draft('task.step', ref, { summary: `Set the mode to ${mode}`, command: `chmod ${mode} ${path}`, output: '' })],
        [7_000, draft('goal.checked', { goal }, { status: 'holding', observed: `Mode ${mode}, owner root`, command: check, output: `${mode} root:root ${path}` })],
        [7_800, draft('goal.asked', { goal, request: `q-${id}` }, permissionQuestion(mode))],
        [27_000, draft('goal.checked', { goal }, { status: 'holding', observed: `Mode ${mode}, owner root`, command: check, output: `${mode} root:root ${path}` })],
      ])
      return
    }

    this.onReply.set(id, (reply) => [
      [1_500, draft('goal.standing', { goal, task: id }, { text, check: reply.trim(), asked: text, terms: [{ id: 'check', label: 'Holds when', value: `${reply.trim()} succeeds`, origin: 'owner', status: 'agreed' }] })],
      [3_000, draft('goal.checked', { goal }, { status: 'holding', observed: 'Your check passes', command: reply.trim(), output: 'exit 0' })],
    ])
    this.schedule([
      [1_200, draft('task.understood', ref, { interpretation: `Standing goal: ${text}`, plan })],
      [2_800, draft('operator.message', ref, { text: 'I need a way to tell whether this holds. Reply with a command that succeeds when it is true, for example: systemctl is-active caddy' })],
      [2_900, draft('task.waiting', ref, { on: 'reply' })],
    ])
  }

  /** Long-running task: checkpoints on a demo clock, then an answer. Asks first when a required input is missing. */
  private startLong(id: string, text: string) {
    const ref = { task: id }
    const total = Math.min(parseCount(text) ?? 3, 7)
    const unit = text.match(/\b(day|hour|week)s?\b/i)?.[1]?.toLowerCase() ?? 'day'
    const weather = /weather|forecast/i.test(text)
    const place = text.match(/\b(?:in|for|at)\s+([A-Z][a-zA-Z]+)/)?.[1]
    const plan = weather
      ? ['Pick a forecast source and location', `Record the forecast once per ${unit}`, 'Summarise what was recorded', 'Re-check the stored values']
      : [`Record a checkpoint once per ${unit}`, 'Summarise what was recorded', 'Re-check the stored values']

    const run = (where: string): [number, EventDraft][] => {
      const step = 5_000
      const items: [number, EventDraft][] = [
        [1_000, draft('operator.message', ref, { text: `Running for ${total} ${unit}s. Demo clock: each ${unit} takes 5 seconds here.` })],
      ]
      const notes: string[] = []
      for (let k = 1; k <= total; k++) {
        const note = weather ? forecastNote(where, k) : `Recorded ${unit} ${k}`
        notes.push(note)
        items.push([1_000 + k * step, draft('task.progress', ref, { done: k, total, note })])
      }
      const end = 1_000 + total * step
      items.push(
        [end + 800, draft('task.answered', ref, { text: weather ? `Forecast for ${where}, ${total} ${unit}s:\n${notes.join('\n')}` : `${total} checkpoints recorded.` })],
        [end + 2_000, draft('task.verification', ref, { result: 'passed', method: 'independent', check: `Read back the ${total} stored records and compared them with the answer.`, command: `wc -l /var/lib/operator/tasks/${id}.jsonl`, output: `${total} /var/lib/operator/tasks/${id}.jsonl` })],
        [end + 2_300, draft('task.completed', ref, { summary: `Ran for ${total} ${unit}s.` })],
      )
      return items
    }

    this.schedule([[1_200, draft('task.understood', ref, { interpretation: `Long-running: ${text}`, plan })]])
    if (weather && !place) {
      this.onReply.set(id, (reply) => {
        const r = reply.trim()
        return run(/^default$/i.test(r) || !r ? 'Frankfurt' : r.replace(/^./, (c) => c.toUpperCase()))
      })
      this.schedule([
        [2_600, draft('operator.message', ref, { text: 'Which location? Reply with a city, or "default" for Frankfurt, where vps-fra-1 runs.' })],
        [2_700, draft('task.waiting', ref, { on: 'reply' })],
      ])
      return
    }
    this.schedule(run(place ?? 'Frankfurt').map(([d, ev]) => [d + 1_500, ev] as [number, EventDraft]))
  }

  setMission(text: string) {
    this.flush()
    if (this.state().mission?.text === text) return false
    this.append(draft('mission.set', {}, { text, by: 'owner' }))
    this.schedule([
      [1_500, draft('operator.message', {}, { text: 'Mission updated. I read it before planning every task from now on. Running tasks keep their plan unless it conflicts, and then I ask you.' })],
    ])
    return true
  }

  private cannedAnswer(text: string) {
    const s = this.state()
    if (/disk|space|storage|var/i.test(text)) {
      const g = s.goals['g-disk']
      return { text: `${g?.observed ?? '/var usage unknown'}. Largest consumer is the ingest-worker log.`, command: 'df -h /var', output: g?.output ?? '' }
    }
    if (/backup|postgres|s3/i.test(text)) {
      const g = s.goals['g-backup']
      return { text: g?.observed ?? 'No backup status yet.', command: 'aws s3 ls s3://kj-backups/pg/', output: g?.output ?? '' }
    }
    if (/tls|cert|ssl|https/i.test(text)) {
      return { text: 'kj.dev certificate is valid for 61 more days and renews automatically.', command: 'openssl x509 -noout -enddate', output: 'notAfter=Jan 22 09:14:03 2027 GMT' }
    }
    return { text: 'Load is normal (0.42), 31 services active, last reboot 12 days ago.', command: 'uptime; systemctl list-units --state=active --type=service | tail -1', output: 'load average: 0.42, 0.38, 0.35\n31 loaded units listed.' }
  }

  /** Owner answers an open question on a goal, by option or in their own words. */
  answerGoal(requestId: string, optionId?: string, text?: string) {
    this.flush()
    const s = this.state()
    const goal = Object.values(s.goals).find((g) => g.questions.some((q) => q.requestId === requestId))
    const q = goal?.questions.find((x) => x.requestId === requestId)
    if (!goal || !q || q.answer || goal.dropped) return { ok: false as const, error: 'This question is no longer open.' }
    if (optionId && !q.options.some((o) => o.id === optionId)) return { ok: false as const, error: 'Unknown option.' }

    const words = text?.trim() ?? ''
    const chosen =
      optionId ??
      (/\b(ask|before|wait|don'?t (fix|correct))\b/i.test(words)
        ? 'ask-first'
        : /\b(only|just)\b.*\bmode\b/i.test(words)
          ? 'mode-only'
          : /^\s*(yes|agree|all|ok|okay|fine|sure|accept)\b/i.test(words)
            ? 'agree-all'
            : undefined)
    const ref = { goal: goal.id, request: requestId, task: goal.task }

    if (!chosen) {
      this.append(draft('owner.message', { task: goal.task }, { text: words, intent: 'reply' }))
      this.schedule([
        [1_500, draft('operator.message', { task: goal.task }, { text: 'I could not match that to the terms, so they stay proposed. Pick an option, or tell me which term to change.' })],
      ])
      return { ok: true as const }
    }

    const changes = permissionAnswer(chosen)
    if (!changes) return { ok: false as const, error: 'Unknown option.' }
    const label = q.options.find((o) => o.id === chosen)?.label ?? chosen
    this.append(draft('goal.answered', ref, { text: words || label, optionId: chosen, terms: changes }))
    const next = this.state().goals[goal.id]
    const agreed = next.terms.filter((t) => t.status === 'agreed').map((t) => `${t.label.toLowerCase()} ${t.value.toLowerCase()}`)
    this.schedule([
      [1_500, draft('operator.message', { task: goal.task }, { text: `Goal updated. Current definition: ${agreed.join('; ')}. The next check runs against these terms.` })],
    ])
    return { ok: true as const }
  }

  stop(taskId: string) {
    this.flush()
    const t = this.state().tasks[taskId]
    if (!t || t.stopped || t.completed) return false
    this.pending = this.pending.filter((p) => p.ev.ref.task !== taskId && p.ev.ref.goal !== t.goal)
    this.onReply.delete(taskId)
    this.append(draft('task.stopped', { task: taskId }, { by: 'owner' }))
    return true
  }

  decide(requestId: string, optionId: string) {
    this.flush()
    const s = this.state()
    const inc = Object.values(s.incidents).find((i) => i.decision?.requestId === requestId)
    const option = inc?.decision?.options.find((o) => o.id === optionId)
    if (!inc || !option || inc.decision?.decided) return false
    const ref = { incident: inc.id }
    this.append(draft('incident.decided', { ...ref, request: requestId }, { optionId, label: option.label }))

    const cap: [number, EventDraft][] = [
      [2_000, draft('incident.step', ref, { kind: 'change', skill: DISK_REV, summary: 'Capped ingest-worker logs: max-size 100m, max-file 5', command: 'docker update is not enough; recreated with --log-opt max-size=100m --log-opt max-file=5', output: 'ingest-worker  Up 2 seconds' })],
      [4_000, draft('incident.step', ref, { kind: 'change', skill: DISK_REV, summary: 'Truncated the old 14 GB log after the container restarted', command: 'truncate -s 0 /var/lib/docker/containers/7f3c…/7f3c…-json.log', output: '' })],
    ]
    if (optionId === 'cap' || optionId === 'both') {
      const extra: [number, EventDraft][] =
        optionId === 'both'
          ? [[5_500, draft('incident.step', ref, { kind: 'change', skill: DISK_REV, summary: 'Deleted volume staging-db (12 GB)', command: 'docker volume rm staging-db', output: 'staging-db' })]]
          : []
      this.schedule([
        ...cap,
        ...extra,
        [8_000, draft('incident.verified', ref, { check: `/var measured at ${optionId === 'both' ? '12' : '27'}% and flat over 2 minutes; ingest-worker log bounded at 100 MB.`, command: 'df --output=pcent /var; sleep 120; df --output=pcent /var', output: `Use%\n ${optionId === 'both' ? '12' : '27'}%\nUse%\n ${optionId === 'both' ? '12' : '27'}%` })],
        [8_500, draft('incident.resolved', ref, { summary: optionId === 'both' ? 'Log growth stopped and staging-db deleted.' : 'Log growth stopped. staging-db kept.' })],
      ])
    } else {
      this.schedule([
        ...cap,
        [5_000, draft('incident.step', ref, { kind: 'diagnose', summary: 'Snapshot of staging-db is queued until the S3 credential arrives' })],
      ])
    }
    return true
  }

  configureCatalog(repo: string, branch: string, access: CatalogAccess) {
    this.flush()
    const cur = this.state().catalog
    if (cur && cur.repo === repo && cur.branch === branch && cur.access === access) return false
    const commit = createHash('sha1').update(`${repo}#${branch}`).digest('hex').slice(0, 7)
    this.append(draft('catalog.configured', {}, { repo, branch, access, commit, by: 'owner' }))
    const writes =
      access === 'read-write'
        ? 'I will commit the skills I learn there.'
        : 'Read only: skills I learn stay on this VPS until you allow writes.'
    this.schedule([
      [
        1_500,
        draft('operator.message', {}, {
          text: `Catalog source is now ${repo} on ${branch} at ${commit}. ${writes} Installed items keep their current revision until you ask me to update them.`,
        }),
      ],
    ])
    return true
  }

  supplyDemoCredential(requestId: string) {
    this.flush()
    const req = this.state().credentials[requestId]
    if (!req || req.supplied) return { ok: false as const, error: 'This request is no longer open.' }
    return this.supplyCredential(requestId, Object.fromEntries(req.fields.map((f) => [f.name, `demo-placeholder-${f.name}`])))
  }

  private supplyCredential(requestId: string, fields: Record<string, string>) {
    this.flush()
    const s = this.state()
    const req = s.credentials[requestId]
    if (!req || req.supplied) return { ok: false as const, error: 'This request is no longer open.' }
    for (const f of req.fields) {
      const v = fields[f.name]
      if (typeof v !== 'string' || !v.trim() || v.length > 512) {
        return { ok: false as const, error: `${f.label} is required.` }
      }
    }
    this.vault.set(requestId, Object.fromEntries(req.fields.map((f) => [f.name, fields[f.name].trim()])))
    const fingerprint =
      'sha256:' +
      createHash('sha256').update(req.fields.map((f) => fields[f.name]).join('\u0000')).digest('hex').slice(0, 10)
    this.append(draft('credential.supplied', { task: req.task, request: requestId }, { fingerprint, fields: req.fields.map((f) => f.name) }))

    const t = req.task
    const items: [number, EventDraft][] = [
      [800, draft('task.resumed', { task: t }, { reason: 'Credential received. Continuing where it paused.' })],
    ]
    if (t === BACKUP_TASK && requestId === S3_REQUEST) {
      items.push(
        [3_000, draft('connector.used', { connector: S3_CONNECTOR }, { task: t, tool: 's3.list', summary: 'Bucket reachable with the new key' })],
        [6_000, draft('connector.used', { connector: S3_CONNECTOR }, { task: t, tool: 's3.put_lifecycle', summary: 'Set lifecycle rule: expire pg/ after 14 days' })],
        [10_000, draft('connector.used', { connector: S3_CONNECTOR }, { task: t, tool: 's3.put_object', summary: 'Uploaded first dump: pg/app-latest.sql.gz (412 MB)' })],
        [12_000, draft('task.answered', { task: t }, { text: 'Nightly backups run at 02:30 and land in s3://kj-backups/pg/. Copies expire after 14 days.' })],
        [14_500, draft('task.verification', { task: t }, { result: 'passed', method: 'independent', check: 'Fetched the uploaded object\u2019s checksum from S3 and compared it with the local file. Read back the lifecycle rule.', command: 'aws s3api head-object --bucket kj-backups --key pg/app-latest.sql.gz --query ETag; md5sum app-latest.sql.gz', output: '"9c2e41b07fd3a1e5"\n9c2e41b07fd3a1e5  app-latest.sql.gz' })],
        [15_000, draft('goal.checked', { goal: 'g-backup' }, { status: 'holding', observed: 'Latest copy uploaded today, 14-day expiry set', command: 'aws s3 ls s3://kj-backups/pg/', output: '412 MiB  app-latest.sql.gz' })],
        [15_500, draft('task.completed', { task: t }, { summary: 'Backups configured and first copy verified offsite.' })],
      )
      const disk = s.incidents[DISK_INCIDENT]
      if (disk?.decision?.decided?.optionId === 'snapshot' && !disk.resolved) {
        const ref = { incident: DISK_INCIDENT, request: DISK_DECISION }
        items.push(
          [18_000, draft('incident.step', ref, { kind: 'change', summary: 'Snapshot of staging-db uploaded to s3://kj-backups/volumes/', command: 'docker run --rm -v staging-db:/v alpine tar cz /v | aws s3 cp - s3://kj-backups/volumes/staging-db.tgz', output: 'ok' })],
          [20_000, draft('incident.step', ref, { kind: 'change', summary: 'Deleted volume staging-db', command: 'docker volume rm staging-db', output: 'staging-db' })],
          [22_000, draft('incident.verified', ref, { check: 'Snapshot readable in S3; /var at 12% and flat.', command: 'aws s3 ls s3://kj-backups/volumes/; df --output=pcent /var', output: '1.9 GiB staging-db.tgz\nUse%\n 12%' })],
          [22_500, draft('incident.resolved', ref, { summary: 'Logs capped, staging-db snapshotted offsite and removed.' })],
        )
      }
    }
    this.schedule(items)
    return { ok: true as const }
  }
}

const g = globalThis as unknown as { __operatorLog?: OperatorLog }

export function getLog() {
  g.__operatorLog ??= new OperatorLog()
  return g.__operatorLog
}

export function resetLog() {
  g.__operatorLog = new OperatorLog()
  return g.__operatorLog
}
