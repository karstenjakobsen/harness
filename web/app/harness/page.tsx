import type { Metadata } from 'next'
import { HarnessView } from '@/components/operator/harness-view'

export const metadata: Metadata = { title: 'Harness · Operator' }

export default function HarnessPage() {
  return <HarnessView />
}
