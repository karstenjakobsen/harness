import { isTaskFinished, type Projection, type Task } from './project'
import { WORKERS } from './meta'

export type WorkerStatus = 'running' | 'exited' | 'parked' | 'stopped' | 'between-runs'

export type RunInfo = {
  id: string
  launcher: (typeof WORKERS.launchers)[number]
  image: string
  workspace: string
  status: WorkerStatus
  label: string
  detail: string
  startedAt: string
  endedAt?: string
  exitCode?: number
  tools: string[]
  toolCalls: number
}

function hash(s: string) {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619)
  return (h >>> 0).toString(16).padStart(8, '0')
}

/** Derives the harness run for a task from the task's own events. */
export function runFor(task: Task, state: Projection): RunInfo {
  const h = hash(task.id)
  const id = `run_${h.slice(0, 6)}`
  const launcher: RunInfo['launcher'] = task.source === 'owner' && parseInt(h[6], 16) % 2 === 0 ? 'Docker' : 'Nomad'

  const tools = new Set<string>()
  if (task.trail.some((t) => t.command)) tools.add('shell')
  for (const r of task.used.skillRuns) tools.add(`skill:${state.skills[r.skill]?.name ?? r.skill}`)
  for (const b of task.used.skillsBuilt) tools.add(`skill:${state.skills[b.skill]?.name ?? b.skill}`)
  for (const c of task.used.connectors) tools.add(`${state.connectors[c.connector]?.name ?? c.connector} ${c.tool}`)
  if (task.used.memoriesRead.length || task.used.memoriesWritten.length) tools.add('memory')

  const toolCalls = task.trail.filter((t) => t.command).length + task.used.connectors.length
  const startedAt = task.trail[0]?.at ?? task.receivedAt
  const base = {
    id,
    launcher,
    image: WORKERS.image,
    workspace: `${WORKERS.workspaceRoot}/${id}/workspace`,
    startedAt,
    tools: [...tools],
    toolCalls,
  }

  if (task.stopped)
    return {
      ...base,
      status: 'stopped',
      label: 'Worker stopped',
      detail: 'You stopped this run. The harness stopped the container and kept the evidence recorded so far.',
      endedAt: task.stopped.at,
      exitCode: 143,
    }
  if (task.horizon === 'standing')
    return {
      ...base,
      status: 'between-runs',
      label: 'Between checks',
      detail:
        'No worker is running. The harness starts a fresh worker for each check and keeps every result. If the goal drifts and the fix needs you, the run waits here.',
      endedAt: task.goalState?.at ?? task.lastAt,
      exitCode: 0,
    }
  if (task.waiting)
    return {
      ...base,
      status: 'parked',
      label: 'Waiting for you',
      detail:
        'The worker exited while this run waits for you. The harness kept the run, its workspace, and the evidence so far. After you act, a fresh worker continues it.',
      endedAt: task.lastAt,
      exitCode: 0,
    }
  if (isTaskFinished(task) || task.verification || task.completed)
    return {
      ...base,
      status: 'exited',
      label: 'Worker exited',
      detail:
        task.verification?.method === 'independent'
          ? 'The worker exited after its last step. The harness checked the result independently and keeps the result and evidence.'
          : 'The worker exited after its last step. The harness keeps the result and evidence.',
      endedAt: task.completed?.at ?? task.lastAt,
      exitCode: 0,
    }
  return {
    ...base,
    status: 'running',
    label: 'Worker running',
    detail: 'A Codex worker is running in its own container. The harness records each tool call as it happens.',
  }
}

export function activeRuns(state: Projection) {
  return state.taskOrder.filter((id) => {
    const t = state.tasks[id]
    return t && runFor(t, state).status === 'running'
  }).length
}
