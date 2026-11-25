import type { Goal } from '@/lib/operator/project'

export const goalTone: Record<Goal['status'], string> = {
  holding: 'bg-verified',
  drift: 'bg-attention',
  blocked: 'bg-destructive',
  unknown: 'bg-muted-foreground',
}

export const goalWord: Record<Goal['status'], string> = {
  holding: 'Holding',
  drift: 'Drifted',
  blocked: 'Blocked',
  unknown: 'Not checked',
}

export const goalText: Record<Goal['status'], string> = {
  holding: 'text-verified',
  drift: 'text-attention',
  blocked: 'text-destructive',
  unknown: 'text-muted-foreground',
}
