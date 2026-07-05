/**
 * AuthHero — animated brand panel for the auth pages' right-hand <aside>
 * (Login, Register, ResetPassword). Radar sweep rotating over a static
 * network graph with pinging nodes; respects `prefers-reduced-motion`.
 * Fills its parent — the parent keeps `hidden lg:flex relative overflow-hidden`.
 */
import type { CSSProperties } from 'react'

interface AuthHeroProps {
  headline: string
  subcopy: string
  features?: string[]
}

// Fixed layout — deterministic so SSR/CSR markup matches and the graph
// never "jumps" between renders. Coordinates are in the 0-100 viewBox
// space, which conveniently doubles as percentages of the panel.
const NODES: { x: number; y: number; r: number; delay: number }[] = [
  { x: 18, y: 22, r: 3, delay: 0 },
  { x: 42, y: 14, r: 2, delay: 0.6 },
  { x: 68, y: 20, r: 2.5, delay: 1.4 },
  { x: 82, y: 40, r: 3, delay: 0.2 },
  { x: 74, y: 64, r: 2, delay: 1.8 },
  { x: 54, y: 78, r: 3, delay: 1.0 },
  { x: 28, y: 70, r: 2.5, delay: 2.2 },
  { x: 14, y: 48, r: 2, delay: 0.9 },
  { x: 48, y: 46, r: 2, delay: 1.6 },
]

const EDGES: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 7], [7, 0],
  [0, 8], [2, 8], [4, 8], [6, 8],
]

export default function AuthHero({ headline, subcopy, features = [] }: AuthHeroProps) {
  return (
    <div className="authhero relative flex h-full w-full flex-col items-center justify-center overflow-hidden bg-gradient-to-br from-primary/20 via-primary/10 to-background">
      {/* ── layer 1: static graph-paper grid ── */}
      <svg className="pointer-events-none absolute inset-0 h-full w-full opacity-[0.07]" aria-hidden="true">
        <defs>
          <pattern id="authhero-grid" width="32" height="32" patternUnits="userSpaceOnUse">
            <path d="M32 0H0V32" fill="none" stroke="hsl(var(--primary))" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#authhero-grid)" />
      </svg>

      {/* ── layer 2: network graph — static edges, pinging nodes ── */}
      <svg
        className="pointer-events-none absolute inset-0 h-full w-full"
        viewBox="0 0 100 100"
        preserveAspectRatio="xMidYMid slice"
        aria-hidden="true"
      >
        <g stroke="hsl(var(--primary))" strokeWidth="0.25" opacity="0.25">
          {EDGES.map(([a, b], i) => {
            const from = NODES[a]
            const to = NODES[b]
            return <line key={i} x1={from.x} y1={from.y} x2={to.x} y2={to.y} />
          })}
        </g>
        {NODES.map((n, i) => (
          <g key={i}>
            <circle cx={n.x} cy={n.y} r={n.r * 0.55} fill="hsl(var(--primary))" opacity="0.85" />
            <circle
              className="authhero-ping"
              cx={n.x}
              cy={n.y}
              r={n.r * 0.55}
              fill="none"
              stroke="hsl(var(--primary))"
              strokeWidth="0.4"
              style={{ '--ahp-delay': `${n.delay}s` } as CSSProperties}
            />
          </g>
        ))}
      </svg>

      {/* ── layer 3: rotating radar sweep + static concentric rings ── */}
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <div className="relative h-[140%] w-[140%]">
          <div className="authhero-sweep absolute inset-0" />
          <div className="absolute inset-[18%] rounded-full border border-primary/20" />
          <div className="absolute inset-[34%] rounded-full border border-primary/15" />
          <div className="absolute inset-[50%] rounded-full border border-primary/10" />
        </div>
      </div>

      {/* ── scrim: base vertical grounding + a centered radial focus so the
          copy reads cleanly over the graph while the edges stay visible ── */}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-background/65 via-background/25 to-background/45" />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(75%_62%_at_50%_52%,hsl(var(--background)/0.72)_0%,hsl(var(--background)/0.4)_48%,transparent_80%)]" />

      {/* ── content ── */}
      <div className="relative z-10 max-w-md px-10 text-center">
        <h2 className="text-3xl font-bold leading-tight tracking-tight text-foreground [text-wrap:balance] [text-shadow:0_2px_18px_hsl(var(--background)/0.85)]">
          {headline}
        </h2>
        <p className="mt-4 text-base leading-relaxed text-foreground/80 [text-wrap:balance] [text-shadow:0_1px_12px_hsl(var(--background))]">
          {subcopy}
        </p>
        {features.length > 0 && (
          <ul className="mt-8 flex flex-col items-center gap-2.5">
            {features.map((f) => (
              <li key={f} className="flex items-center gap-2 text-left">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary shadow-[0_0_8px_hsl(var(--primary)/0.8)]" />
                <span className="font-mono text-[13px] tracking-tight text-foreground/75 [text-shadow:0_1px_8px_hsl(var(--background))]">
                  {f}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Scoped keyframes — kept self-contained rather than moved into
          tailwind.config.js since this is the only consumer. */}
      <style>{`
        .authhero-sweep {
          background: conic-gradient(
            from 0deg,
            hsl(var(--primary) / 0.35),
            hsl(var(--primary) / 0) 18%,
            hsl(var(--primary) / 0) 100%
          );
          border-radius: 9999px;
          animation: authhero-rotate 7s linear infinite;
          will-change: transform;
        }
        .authhero-ping {
          transform-box: fill-box;
          transform-origin: center;
          animation: authhero-ping 3.2s cubic-bezier(0, 0, 0.2, 1) infinite;
          animation-delay: var(--ahp-delay, 0s);
          will-change: transform, opacity;
        }
        @keyframes authhero-rotate {
          to { transform: rotate(360deg); }
        }
        @keyframes authhero-ping {
          0% { transform: scale(1); opacity: 0.9; }
          75%, 100% { transform: scale(5); opacity: 0; }
        }
        @media (prefers-reduced-motion: reduce) {
          .authhero-sweep,
          .authhero-ping {
            animation: none !important;
          }
          .authhero-sweep {
            opacity: 0.5;
          }
        }
      `}</style>
    </div>
  )
}
