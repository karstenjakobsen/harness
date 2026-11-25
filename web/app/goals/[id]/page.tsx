import { GoalView } from '@/components/operator/goal-view'

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return <GoalView id={id} />
}
