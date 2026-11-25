import type { Metadata } from 'next'
import { MissionView } from '@/components/operator/mission-view'

export const metadata: Metadata = { title: 'Mission · Operator' }

export default function Page() {
  return <MissionView />
}
