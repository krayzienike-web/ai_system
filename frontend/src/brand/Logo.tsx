// SousChef AI logo: chef's toque in a basil tile with a saffron "AI" spark (docs/ux/02-brand-design-system.md §3).

export function LogoMark({ size = 32, inverted = false }: { size?: number; inverted?: boolean }) {
  const tile = inverted ? "#FFFFFF" : "#0A8F84";
  const hat = inverted ? "#0A8F84" : "#FFFFFF";
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label="SousChef AI">
      <rect width="32" height="32" rx="9" fill={tile} />
      {/* toque: three puffs over a band */}
      <path
        d="M10 19.5c-2.2-.4-3.6-2.2-3.4-4.3.2-2.2 2.1-3.8 4.3-3.6.7-2.1 2.7-3.4 4.9-3.2 1.8.1 3.3 1.2 4 2.8 2.3-.4 4.4 1.2 4.7 3.5.3 2.3-1.3 4.4-3.6 4.8"
        fill="none"
        stroke={hat}
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      <rect x="10" y="19.5" width="11" height="4.5" rx="1.5" fill={hat} />
      {/* AI spark */}
      <path d="M25.5 3.5l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9z" fill="#F2B33D" />
    </svg>
  );
}

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <LogoMark />
      {!compact && (
        <span className="flex items-center gap-1.5">
          <span className="font-display text-[17px] font-semibold tracking-tight text-ink">SousChef</span>
          <span className="rounded-md border border-ink/20 px-1 py-px text-[10px] font-semibold tracking-wide text-ink-2">AI</span>
        </span>
      )}
    </span>
  );
}
