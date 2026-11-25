export type Ref = {
  task?: string
  incident?: string
  skill?: string
  goal?: string
  request?: string
  memory?: string
  connector?: string
  project?: string
}

/** Where a reusable definition lives in the external Git catalog the operator reads from. */
export type CatalogSource = { repo: string; path: string }

export type CatalogAccess = 'read' | 'read-write'

export type VerificationClaim = {
  claim: string
  method: VerificationMethod
  command: string
  output: string
}

export type SkillRef = { id: string; revision: string }

export type ConnectorTool = { name: string; description: string; access: 'read' | 'write' }

export type DnsRecordChange = {
  zone: string
  name: string
  type: string
  value: string
  ttl: number
  change: 'created' | 'updated' | 'deleted'
}

export type CredentialField = { name: string; label: string; secret: boolean }

export type DecisionOption = {
  id: string
  label: string
  consequence: string
  recommended?: boolean
}

/**
 * One condition of a standing goal. origin says who introduced it; status says whether
 * it is part of the current definition (agreed), only suggested (proposed), or rejected.
 */
export type GoalTerm = {
  id: string
  label: string
  value: string
  origin: 'owner' | 'operator'
  status: 'agreed' | 'proposed' | 'declined'
}

export type GoalTermChange = { id: string; status: GoalTerm['status']; value?: string; origin?: GoalTerm['origin'] }

export type SelfTest = { name: string; input: string; expected: string; passed: boolean }

export type VerificationMethod = 'self' | 'independent'

/**
 * short: answered or done in one pass.
 * long: runs over time with checkpoints, then finishes.
 * standing: never finishes; the operator keeps a goal true and reports holding or drift.
 */
export type TaskHorizon = 'short' | 'long' | 'standing'

type DataMap = {
  'owner.left': { note: string }
  'owner.message': { text: string; intent: 'ask' | 'steer' | 'config' | 'reply' }
  'operator.message': { text: string }
  /** asked is the owner's own words; terms separate what they asked from what the operator added. */
  'goal.standing': { text: string; check: string; asked?: string; terms?: GoalTerm[] }
  /** The operator asks the owner about a goal. It keeps checking while it waits. */
  'goal.asked': { question: string; about: string[]; options: DecisionOption[] }
  'goal.answered': { text: string; optionId?: string; terms: GoalTermChange[] }
  'goal.checked': {
    status: 'holding' | 'drift' | 'blocked'
    observed: string
    command: string
    output: string
  }
  /** Owner-set standing instructions the operator reads before planning any task. */
  'mission.set': { text: string; by: 'install' | 'owner' }
  'task.received': {
    title: string
    source: 'owner' | 'schedule' | 'incident'
    request?: string
    /** Absent on older events, which are treated as short. */
    horizon?: TaskHorizon
  }
  /** Checkpoint on a long-running task. */
  'task.progress': { done: number; total: number; note: string }
  'task.understood': { interpretation: string; plan: string[] }
  'task.step': { summary: string; command?: string; output?: string; routine?: boolean }
  'task.answered': { text: string }
  'task.verification': {
    result: 'passed' | 'failed'
    method: VerificationMethod
    check: string
    command: string
    output: string
    claims?: VerificationClaim[]
  }
  'task.waiting': { on: 'credential' | 'decision' | 'reply' }
  'task.resumed': { reason: string }
  'task.completed': { summary: string }
  'task.stopped': { by: 'owner' }
  'credential.requested': {
    label: string
    why: string
    destination: string
    storage: string
    scope: string
    fields: CredentialField[]
  }
  'credential.supplied': { fingerprint: string; fields: string[] }
  'incident.opened': {
    resource: string
    symptom: string
    detectedBy: string
    severity: 'high' | 'medium' | 'low'
  }
  'incident.step': {
    summary: string
    kind: 'diagnose' | 'change' | 'routine'
    command?: string
    output?: string
    skill?: SkillRef
  }
  'incident.verified': { check: string; command: string; output: string }
  'incident.resolved': { summary: string }
  'incident.decision_needed': {
    known: string[]
    uncertain: string[]
    question: string
    options: DecisionOption[]
  }
  'incident.decided': { optionId: string; label: string }
  'skill.installed': {
    name: string
    purpose: string
    revision: string
    foundational: boolean
    source: string
    catalog: CatalogSource
    procedure: string[]
  }
  'skill.created': {
    name: string
    purpose: string
    fromTask: string
    revision: string
    builtWith?: SkillRef
    catalog: CatalogSource
    procedure: string[]
  }
  'skill.revised': { revision: string; summary: string; task?: string; procedure: string[] }
  'skill.self_tested': { tests: SelfTest[]; authoredBy: string; task: string; revision: string }
  /** A committed revision becomes the one the operator runs. Separate from committing it. */
  'skill.activated': { revision: string; task?: string; reason: string }
  'skill.used': { task?: string; incident?: string; input: string; novelty: string; revision: string }
  'project.registered': {
    name: string
    description: string
    hostname: string
    repo: string
    upstream: string
    catalog: CatalogSource
    memory?: string
  }
  /** Which Git repository and branch the operator reads skills, connectors, and projects from. */
  'catalog.configured': {
    repo: string
    branch: string
    access: CatalogAccess
    commit: string
    by: 'install' | 'owner'
  }
  'memory.written': { title: string; kind: 'fact' | 'preference' | 'procedure'; text: string }
  'memory.read': { task: string; why: string }
  'connector.configured': {
    name: string
    provider: string
    tools: ConnectorTool[]
    scope: string
    manages?: { label: string; value: string }
    credential: { label: string; storage: string; fingerprint?: string; request?: string }
    catalog: CatalogSource
  }
  'connector.used': { task: string; tool: string; summary: string; record?: DnsRecordChange }
  'skill.verified': {
    task: string
    check: string
    command: string
    output: string
    matched: string
  }
}

export type EventType = keyof DataMap
export type EventData<K extends EventType> = DataMap[K]

export type OperatorEvent<K extends EventType = EventType> = {
  [T in K]: { seq: number; at: string; type: T; ref: Ref; data: DataMap[T] }
}[K]

export type EventDraft<K extends EventType = EventType> = {
  [T in K]: { at?: string; type: T; ref: Ref; data: DataMap[T] }
}[K]

export function draft<K extends EventType>(
  type: K,
  ref: Ref,
  data: DataMap[K],
  at?: string,
): EventDraft<K> {
  return { type, ref, data, at } as EventDraft<K>
}
