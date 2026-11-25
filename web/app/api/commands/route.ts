import { getLog, resetLog } from '@/lib/operator/server-log'
import { normalizeRepo, validBranch } from '@/lib/operator/catalog'

export const dynamic = 'force-dynamic'

type Body =
  | { kind: 'message'; text: string; taskId?: string }
  | { kind: 'stop'; taskId: string }
  | { kind: 'decide'; requestId: string; optionId: string }
  | { kind: 'goal-answer'; requestId: string; optionId?: string; text?: string }
  | { kind: 'catalog'; repo: string; branch: string; access: string }
  | { kind: 'mission'; text: string }
  | { kind: 'reset' }

const isStr = (v: unknown, max = 200): v is string => typeof v === 'string' && v.length > 0 && v.length <= max

export async function POST(req: Request) {
  let body: Body
  try {
    body = (await req.json()) as Body
  } catch {
    return Response.json({ error: 'Invalid JSON' }, { status: 400 })
  }
  const log = getLog()
  switch (body.kind) {
    case 'message': {
      const text = typeof body.text === 'string' ? body.text.trim() : ''
      if (!text || text.length > 2000) return Response.json({ error: 'Message is empty or too long' }, { status: 400 })
      if (body.taskId !== undefined && !isStr(body.taskId)) return Response.json({ error: 'Bad task' }, { status: 400 })
      log.message(text, body.taskId)
      return Response.json({ ok: true })
    }
    case 'stop':
      if (!isStr(body.taskId)) return Response.json({ error: 'Bad task' }, { status: 400 })
      return log.stop(body.taskId)
        ? Response.json({ ok: true })
        : Response.json({ error: 'Task is not running' }, { status: 409 })
    case 'decide':
      if (!isStr(body.requestId) || !isStr(body.optionId)) return Response.json({ error: 'Bad decision' }, { status: 400 })
      return log.decide(body.requestId, body.optionId)
        ? Response.json({ ok: true })
        : Response.json({ error: 'Decision already made or unknown' }, { status: 409 })
    case 'goal-answer': {
      if (!isStr(body.requestId)) return Response.json({ error: 'Bad question' }, { status: 400 })
      if (body.optionId !== undefined && !isStr(body.optionId)) return Response.json({ error: 'Bad option' }, { status: 400 })
      const text = typeof body.text === 'string' ? body.text.trim() : ''
      if (text.length > 2_000) return Response.json({ error: 'Keep the answer under 2,000 characters.' }, { status: 400 })
      if (!body.optionId && !text) return Response.json({ error: 'Pick an option or write an answer.' }, { status: 400 })
      const r = log.answerGoal(body.requestId, body.optionId, text)
      return r.ok ? Response.json({ ok: true }) : Response.json({ error: r.error }, { status: 409 })
    }
    case 'catalog': {
      const repo = typeof body.repo === 'string' ? normalizeRepo(body.repo) : null
      const branch = typeof body.branch === 'string' ? body.branch.trim() : ''
      if (!repo) return Response.json({ error: 'Repository must look like github.com/owner/name' }, { status: 400 })
      if (!validBranch(branch)) return Response.json({ error: 'Branch name is not valid' }, { status: 400 })
      if (body.access !== 'read' && body.access !== 'read-write') {
        return Response.json({ error: 'Access must be read or read-write' }, { status: 400 })
      }
      return log.configureCatalog(repo, branch, body.access)
        ? Response.json({ ok: true })
        : Response.json({ error: 'That is already the catalog source.' }, { status: 409 })
    }
    case 'mission': {
      const text = typeof body.text === 'string' ? body.text.trim() : ''
      if (!text) return Response.json({ error: 'Write at least one line of mission.' }, { status: 400 })
      if (text.length > 2_000) return Response.json({ error: 'Keep the mission under 2,000 characters.' }, { status: 400 })
      return log.setMission(text)
        ? Response.json({ ok: true })
        : Response.json({ error: 'That is already the mission.' }, { status: 409 })
    }
    case 'reset':
      resetLog().begin()
      return Response.json({ ok: true })
    default:
      return Response.json({ error: 'Unknown command' }, { status: 400 })
  }
}
