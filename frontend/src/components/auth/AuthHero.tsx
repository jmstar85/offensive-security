/**
 * AuthHero — brand panel for the auth pages' right-hand <aside>
 * (Login, Register, ResetPassword).
 *
 * Layout (top → bottom): headline · OSA emblem artwork (emblem + wordmark,
 * ~1/3 of the panel, center) · subcopy + feature list. Behind it sits an
 * animated "coding screen" whose palette follows the emblem's own vibe and
 * the active theme:
 *   • dark theme  → dark background, green console font (matrix-style)
 *   • light theme → gray background, pastel-red console font
 *
 * The emblem art has a dark backdrop baked in, so it rides on a soft dark
 * "spotlight" plate — invisible on the dark panel, a deliberate spotlight on
 * the light panel — keeping its white wordmark legible in BOTH themes.
 * Foreground copy is theme-aware too. Motion respects
 * `prefers-reduced-motion`; a text fallback renders if the art fails.
 */
import { useState } from 'react'
import type { CSSProperties } from 'react'

interface AuthHeroProps {
  headline: string
  subcopy: string
  features?: string[]
  /** Emblem artwork served from the public root. */
  image?: string
}

// Red-team console flavor text for the scrolling code columns. Decorative;
// tripled per column so the vertical loop is seamless.
const CODE_COLUMNS: string[] = [
  `$ nmap -sV -p- 10.0.0.5
[+] 22/tcp   open  ssh
[+] 443/tcp  open  https
async def exploit(t):
  rop = build_chain(gadgets)
  await sess.send(rop)
[*] fuzzing params ...
recon.enum(subdomains)
if cve.cvss >= 9.0:
  escalate(priv="root")
[!] shell uid=0(root)
c2.beacon(interval=30)`,
  `POST /api/login HTTP/1.1
sqlmap -u $URL --dbs
[+] payload delivered
for host in scope:
  scan(host, deep=True)
[*] pivoting 10.0.2.0/24
hashcat -m 1000 ntlm.txt
[+] cracked admin:hunter2
token = forge_jwt(key)
grant("admin", token)
[!] lateral move ok
exfil(loot, tunnel)`,
  `import offsec as osa
agent = osa.Operator()
agent.plan(target)
while not agent.done:
  step = agent.next()
  run(step.tool, step.arg)
[+] foothold @ dmz-web01
priv = kernel.exploit()
[*] dumping lsass ...
report.finding(sev=CRIT)
[+] engagement complete
osa.autonomous(loop=True)`,
]

export default function AuthHero({
  headline,
  subcopy,
  features = [],
  image = '/osa-icon.jpg',
}: AuthHeroProps) {
  const [iconOk, setIconOk] = useState(true)

  return (
    <div className="authhero relative h-full w-full overflow-hidden">
      {/* ── theme-aware coding-screen backdrop ── */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden font-mono text-[13px] leading-5" aria-hidden="true">
        {CODE_COLUMNS.map((code, i) => (
          <pre
            key={i}
            className="authhero-code absolute top-0 m-0 whitespace-pre"
            style={{
              left: `${4 + i * 33}%`,
              '--code-dur': `${20 + i * 6}s`,
            } as CSSProperties}
          >
            {code + '\n' + code + '\n' + code}
          </pre>
        ))}
      </div>

      {/* CRT scanlines + readability scrim */}
      <div className="authhero-scanlines pointer-events-none absolute inset-0" aria-hidden="true" />
      <div className="authhero-scrim pointer-events-none absolute inset-0" aria-hidden="true" />

      {/* ── content: headline · icon (center 1/3) · copy ──
          `pointer-events-none`: this panel is decorative (aria-hidden) and
          fills the whole <aside>, which overlaps the page's absolutely
          positioned theme-toggle button in the top-right corner. Without
          this, the panel would intercept clicks meant for that button. */}
      <div className="pointer-events-none relative flex h-full flex-col items-center justify-center gap-6 px-10 py-10 text-center">
        <h2 className="authhero-title max-w-md text-3xl font-bold leading-tight tracking-tight [text-wrap:balance]">
          {headline}
        </h2>

        {iconOk ? (
          <div className="authhero-icon relative aspect-[1040/1152] w-[38%] min-w-[210px] max-w-[290px]">
            <img
              src={image}
              alt=""
              aria-hidden="true"
              draggable={false}
              onError={() => setIconOk(false)}
              className="authhero-icon-img relative h-full w-full select-none object-contain"
            />
          </div>
        ) : (
          <div
            className="flex h-40 w-40 items-center justify-center rounded-2xl border border-red-500/40 bg-black/50 text-4xl font-black tracking-tight text-red-400 shadow-[0_0_40px_rgba(239,68,68,0.4)]"
            aria-hidden="true"
          >
            OSA
          </div>
        )}

        <div className="flex max-w-md flex-col items-center gap-5">
          <p className="authhero-sub text-base leading-relaxed [text-wrap:balance]">
            {subcopy}
          </p>
          {features.length > 0 && (
            <ul className="flex flex-col items-center gap-2.5">
              {features.map((f) => (
                <li key={f} className="flex items-center gap-2 text-left">
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.9)]" />
                  <span className="authhero-feat font-mono text-[13px] tracking-tight">{f}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Scoped keyframes + theme-aware palette — kept self-contained rather
          than moved into tailwind.config.js since this is the only consumer.
          `.dark` on <html> drives the dark palette; the base rules are the
          light palette. */}
      <style>{`
        /* panel base: gray (light) / dark (dark) */
        .authhero { background: linear-gradient(180deg, #eceef2 0%, #dcdfe5 100%); }
        .dark .authhero { background: linear-gradient(180deg, #08110f 0%, #04080a 100%); }

        /* console font: pastel red (light) / green (dark) */
        .authhero-code { color: rgba(239,68,68,0.30); }
        .dark .authhero-code { color: rgba(34,197,94,0.28); }
        .authhero-code {
          animation: authhero-code var(--code-dur, 22s) linear infinite;
          will-change: transform;
        }

        /* readability scrim tuned per theme */
        .authhero-scrim {
          background: radial-gradient(72% 66% at 50% 46%,
            rgba(236,238,242,0.74), rgba(236,238,242,0.42) 55%, rgba(236,238,242,0.64));
        }
        .dark .authhero-scrim {
          background: radial-gradient(72% 66% at 50% 46%,
            rgba(6,10,12,0.80), rgba(6,10,12,0.48) 55%, rgba(6,10,12,0.70));
        }

        .authhero-scanlines {
          background-image: repeating-linear-gradient(0deg, rgba(0,0,0,0.06) 0 1px, transparent 1px 3px);
          opacity: 0.6;
        }
        .dark .authhero-scanlines {
          background-image: repeating-linear-gradient(0deg, rgba(0,0,0,0.30) 0 1px, transparent 1px 3px);
        }

        .authhero-icon {
          animation: authhero-float 6.5s ease-in-out infinite;
          will-change: transform;
        }
        .authhero-icon-img {
          -webkit-mask-image: radial-gradient(ellipse 86% 92% at 50% 49%, #000 66%, transparent 100%);
          mask-image: radial-gradient(ellipse 86% 92% at 50% 49%, #000 66%, transparent 100%);
          /* light theme: invert lightness so the metallic art becomes dark-on-light
             and its dark matrix backdrop lightens to blend with the gray panel;
             hue-rotate restores the red/green brand hues that invert would flip. */
          filter: invert(1) hue-rotate(180deg) saturate(1.12) contrast(1.03);
        }
        .dark .authhero-icon-img {
          /* dark theme: original metallic art blends on the dark panel */
          filter: drop-shadow(0 8px 26px rgba(239,68,68,0.42));
        }

        /* theme-aware foreground copy */
        .authhero-title { color: #0f172a; text-shadow: 0 1px 12px rgba(255,255,255,0.6); }
        .dark .authhero-title { color: #ffffff; text-shadow: 0 2px 16px rgba(0,0,0,0.9); }
        .authhero-sub { color: #334155; text-shadow: 0 1px 10px rgba(255,255,255,0.6); }
        .dark .authhero-sub { color: rgba(255,255,255,0.78); text-shadow: 0 1px 10px rgba(0,0,0,0.9); }
        .authhero-feat { color: #475569; }
        .dark .authhero-feat { color: rgba(255,255,255,0.72); }

        @keyframes authhero-code {
          from { transform: translateY(0); }
          to { transform: translateY(-33.333%); }
        }
        @keyframes authhero-float {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-8px); }
        }
        @media (prefers-reduced-motion: reduce) {
          .authhero-code, .authhero-icon { animation: none !important; }
        }
      `}</style>
    </div>
  )
}
