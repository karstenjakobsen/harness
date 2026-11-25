import type { Metadata } from 'next'
import { CatalogView } from '@/components/operator/catalog-view'

export const metadata: Metadata = { title: 'Catalog · Operator' }

export default function Page() {
  return <CatalogView />
}
