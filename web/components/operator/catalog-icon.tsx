import { Activity, Archive, Globe, HardDrive, ScrollText, Server, ShieldCheck, Sparkles, type LucideIcon } from 'lucide-react'
import { brandIconUrl, type CatalogGlyph, type CatalogIcon as Icon } from '@/lib/operator/catalog'
import { cn } from '@/lib/utils'

const glyphs: Record<CatalogGlyph, LucideIcon> = {
  sparkles: Sparkles,
  'hard-drive': HardDrive,
  activity: Activity,
  shield: ShieldCheck,
  scroll: ScrollText,
  globe: Globe,
  server: Server,
  archive: Archive,
}

export function CatalogIcon({ icon, size = 'md' }: { icon: Icon; size?: 'sm' | 'md' }) {
  const box = size === 'sm' ? 'size-9 rounded-lg' : 'size-12 rounded-xl'
  if ('brand' in icon) {
    return (
      <span className={cn('flex shrink-0 items-center justify-center bg-tile ring-1 ring-border', box)}>
        {/* eslint-disable-next-line @next/next/no-img-element -- remote SVG brand marks from theSVG */}
        <img
          src={brandIconUrl(icon.brand)}
          alt=""
          width={28}
          height={28}
          loading="lazy"
          className={size === 'sm' ? 'size-5' : 'size-7'}
        />
      </span>
    )
  }
  const G = glyphs[icon.glyph]
  return (
    <span className={cn('flex shrink-0 items-center justify-center bg-secondary text-foreground ring-1 ring-border', box)}>
      <G className={size === 'sm' ? 'size-4' : 'size-6'} aria-hidden="true" />
    </span>
  )
}
