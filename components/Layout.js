import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/router'
import Head from 'next/head'

const NAV = [
  {
    label: 'Games',
    href: '/games',
    sub: [
      { label: 'Log5',          href: '/games/log5' },
      { label: 'Research-Based',href: '/games/research' },
      { label: 'XGBoost',       href: '/games/xgboost' },
      { label: 'Random Forest', href: '/games/random-forest' },
      { label: 'Composite',     href: '/games/composite' },
    ],
  },
  {
    label: 'Hitters',
    href: '/hitters',
    sub: [
      { label: 'Log5 Hit Model', href: '/hitters/log5-hit' },
      { label: 'ML Hit Model',   href: '/hitters/ml-hit' },
      { label: 'HR Model',       href: '/hitters/hr-model' },
    ],
  },
  {
    label: 'Pitchers',
    href: '/pitchers',
    sub: [
      { label: 'Strikeout Model', href: '/pitchers/strikeout' },
    ],
  },
]

export default function Layout({ children, title }) {
  const router = useRouter()
  const [mobileOpen, setMobileOpen] = useState(false)

  const inSection = (href) => router.pathname.startsWith(href)
  const isActive  = (href) => router.pathname === href

  const pageTitle = title ? `${title} · BaseballIQ` : 'BaseballIQ'

  return (
    <>
      <Head>
        <title>{pageTitle}</title>
        <meta name="description" content="MLB prediction models powered by Statcast and the MLB API" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg)' }}>

        {/* ── Top bar ── */}
        <header style={{
          borderBottom: '1px solid var(--border)', background: 'var(--surface)',
          position: 'sticky', top: 0, zIndex: 50,
        }}>
          <div style={{ maxWidth: 1400, margin: '0 auto', padding: '0 1.5rem', height: 52,
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>

            {/* Logo */}
            <Link href="/" style={{ display: 'flex', alignItems: 'center', gap: 12, textDecoration: 'none' }}>
              <div style={{
                width: 30, height: 30, background: 'var(--red)', borderRadius: 4,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontFamily: 'var(--font-d)', color: '#fff', fontSize: 18, letterSpacing: 1,
              }}>B</div>
              <span className="display" style={{ color: 'var(--text)', fontSize: 22, letterSpacing: 3 }}>
                BaseballIQ
              </span>
            </Link>

            {/* Desktop nav links */}
            <nav style={{ display: 'flex', gap: 32 }} className="hidden-mobile">
              {NAV.map(n => (
                <Link key={n.href} href={n.href} style={{
                  fontSize: 13, fontWeight: 500, textDecoration: 'none', letterSpacing: 1,
                  color: inSection(n.href) ? 'var(--red)' : 'var(--muted)',
                  transition: 'color 0.15s',
                }}>
                  {n.label.toUpperCase()}
                </Link>
              ))}
            </nav>

            {/* Status badge */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: 'var(--font-m)', fontSize: 11 }}>
              <span className="pulse" style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--green)', display: 'inline-block' }} />
              <span style={{ color: 'var(--green)' }}>MLB API</span>
            </div>
          </div>
        </header>

        {/* ── Body ── */}
        <div style={{ display: 'flex', flex: 1, maxWidth: 1400, margin: '0 auto', width: '100%' }}>

          {/* Sidebar */}
          <aside style={{
            width: 210, flexShrink: 0,
            borderRight: '1px solid var(--border)',
            padding: '1.5rem 0',
            display: 'flex', flexDirection: 'column',
          }}>
            {NAV.map(section => (
              <div key={section.label} style={{ marginBottom: 4 }}>

                {/* Section heading */}
                <Link href={section.href} style={{
                  display: 'block', padding: '6px 20px',
                  fontFamily: 'var(--font-m)', fontSize: 11,
                  letterSpacing: '0.12em', textTransform: 'uppercase',
                  color: inSection(section.href) ? 'var(--red)' : 'var(--muted)',
                  textDecoration: 'none', fontWeight: 600,
                }}>
                  {section.label}
                </Link>

                {/* Sub-pages */}
                {section.sub.map(child => (
                  <Link key={child.href} href={child.href} style={{
                    display: 'block', padding: '5px 20px 5px 28px',
                    fontSize: 13, textDecoration: 'none',
                    borderLeft: `2px solid ${isActive(child.href) ? 'var(--red)' : 'transparent'}`,
                    marginLeft: 8,
                    color: isActive(child.href) ? 'var(--text)' : 'var(--muted)',
                    background: isActive(child.href) ? 'var(--red-glow)' : 'transparent',
                    transition: 'all 0.15s',
                  }}>
                    {child.label}
                  </Link>
                ))}
              </div>
            ))}

            {/* Bottom info */}
            <div style={{ marginTop: 'auto', padding: '1rem 20px', borderTop: '1px solid var(--border)' }}>
              <div className="mono" style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.8 }}>
                <div>Updated daily</div>
                <div>via GitHub Actions</div>
              </div>
            </div>
          </aside>

          {/* Main */}
          <main className="fade-in" style={{ flex: 1, minWidth: 0, padding: '2rem 2.5rem' }}>
            {children}
          </main>
        </div>

        {/* Footer */}
        <footer style={{
          borderTop: '1px solid var(--border)', padding: '12px 24px',
          textAlign: 'center', fontFamily: 'var(--font-m)', fontSize: 11, color: 'var(--muted)',
        }}>
          BaseballIQ · Data via MLB Statsapi · Predictions updated daily via GitHub Actions
        </footer>
      </div>

      <style jsx global>{`
        @media (max-width: 768px) { .hidden-mobile { display: none !important; } }
      `}</style>
    </>
  )
}
