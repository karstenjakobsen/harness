import type { Metadata } from 'next'
import { GoalsView } from '@/components/operator/goals-view'

export const metadata: Metadata = { title: 'Goals · Operator' }

export default function Page() {
  return <GoalsView />
}
