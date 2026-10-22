import { cn } from '@/lib/utils'
import { BRAND } from './brand'

const SIZES = {
  // Mobile menu sheet.
  md: { logo: 'h-9 w-9', text: 'text-xl' },
  // App navbar (56 px tall) and public page headers.
  lg: { logo: 'h-10 w-10', text: 'text-2xl' },
} as const

interface BrandLockupProps {
  size?: keyof typeof SIZES
  /** Hide the name below the sm breakpoint so tight headers keep only the mark. */
  hideNameOnMobile?: boolean
  className?: string
}

/**
 * Logo plus product name, used in every header. The FastAlgo wordmark sets
 * "Fast" heavy and "Algo" medium (design-language.md section 2.4); a
 * white-labelled install shows the client's name in plain bold instead.
 */
export function BrandLockup({
  size = 'lg',
  hideNameOnMobile = false,
  className,
}: BrandLockupProps) {
  const s = SIZES[size]
  const isProductName = BRAND.displayName === BRAND.productName
  return (
    <span className={cn('flex items-center gap-2.5', className)}>
      <img src={BRAND.logoUrl} alt="" aria-hidden="true" className={cn(s.logo, 'shrink-0')} />
      <span
        aria-hidden="true"
        className={cn(
          s.text,
          'leading-none tracking-tight',
          hideNameOnMobile && 'hidden sm:inline'
        )}
      >
        {isProductName ? (
          <>
            <span className="font-extrabold">Fast</span>
            <span className="font-medium">Algo</span>
          </>
        ) : (
          <span className="font-bold">{BRAND.displayName}</span>
        )}
      </span>
      {/* One accessible name for the lockup, whichever way it is drawn. */}
      <span className="sr-only">{BRAND.displayName}</span>
    </span>
  )
}
