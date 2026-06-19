import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';

// ── Navigation structure — Research · Games · Hitters · Pitchers ──────────────
const NAV = [
  {
    section: 'Research',
    items: [
      { label: 'Elo Ratings',    href: '/research/elo' },
      { label: 'Team Metrics',   href: '/research/team-metrics' },
      { label: 'Player Metrics', href: '/research/player-metrics' },
    ],
  },
  {
    section: 'Games',
    items: [
      { label: 'Overview',       href: '/games' },
      { label: 'Log5',           href: '/games/log5' },
      { label: 'Research-Based', href: '/games/research' },
      { label: 'XGBoost',        href: '/games/xgboost' },
      { label: 'Random Forest',  href: '/games/random-forest' },
      { label: 'Composite',      href: '/games/composite' },
    ],
  },
  {
    section: 'Hitters',
    items: [
      { label: 'Overview',     href: '/hitters' },
      { label: 'Log5 Hit',     href: '/hitters/log5-hit' },
      { label: 'ML Hit Model', href: '/hitters/ml-hit' },
      { label: 'HR Model',     href: '/hitters/hr-model' },
      { label: 'ML HR Model',  href: '/hitters/ml-hr' },
      { label: 'Composite',    href: '/hitters/composite' },
    ],
  },
  {
    section: 'Pitchers',
    items: [
      { label: 'Overview', href: '/pitchers' },
      { label: 'Strikeout', href: '/pitchers/strikeout' },
    ],
  },
];

export default function Layout({ children, title = 'Dashboard' }) {
  const router = useRouter();

  const pageTitle = title === 'Dashboard'
    ? 'Chalk Line Labs — MLB Predictions'
    : `${title} · Chalk Line Labs`;

  return (
    <>
      <Head>
        <title>{pageTitle}</title>
        <meta name="description" content="Data-driven MLB predictions from Chalk Line Labs — game outcomes, hitter performance, and pitcher projections." />
        <link rel="icon" href="/images/logo-blue.png" />
      </Head>

      <div style={{ display: 'flex', minHeight: '100vh' }}>

        {/* ── Sidebar ──────────────────────────────────────────────────────── */}
        <aside style={{
          width:         'var(--sidebar-w)',
          background:    'var(--navy-mid)',
          borderRight:   '1px solid var(--navy-border)',
          position:      'fixed',
          top: 0, left: 0, bottom: 0,
          display:       'flex',
          flexDirection: 'column',
          overflowY:     'auto',
          zIndex:        100,
        }}>

          {/* ── Logo / wordmark ── */}
          <Link href="/">
            <a
              style={{
                padding:     '20px 16px',
                borderBottom:'1px solid var(--navy-border)',
                display:     'flex',
                alignItems:  'center',
                gap:         12,
                textDecoration: 'none',
                transition:  'background 0.15s',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--accent-glow)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              {/* Gradient CL icon box */}
              <div style={{
                width:          40,
                height:         40,
                borderRadius:   8,
                background:     'linear-gradient(135deg, #00D9FF, #0066FF)',
                display:        'flex',
                alignItems:     'center',
                justifyContent: 'center',
                flexShrink:     0,
              }}>
                <span style={{
                  fontFamily: "'Sora', sans-serif",
                  fontWeight: 700,
                  fontSize:   14,
                  color:      '#0F1419',
                  letterSpacing: 0.5,
                }}>
                  CL
                </span>
              </div>

              {/* Wordmark */}
              <div>
                <div style={{
                  fontFamily:    "'Sora', sans-serif",
                  fontWeight:    700,
                  fontSize:      13,
                  color:         'var(--white)',
                  letterSpacing: 0.5,
                  lineHeight:    1.2,
                }}>
                  CHALK LINE
                </div>
                <div style={{
                  fontFamily:    "'Sora', sans-serif",
                  fontWeight:    700,
                  fontSize:      11,
                  color:         'var(--accent)',
                  letterSpacing: 1.5,
                }}>
                  LABS
                </div>
              </div>
            </a>
          </Link>

          {/* ── Navigation ── */}
          <nav style={{ flex: 1, padding: '12px 0' }}>
            {NAV.map(({ section, items }) => (
              <div key={section} style={{ marginBottom: 4 }}>

                {/* Section label */}
                <div style={{
                  padding:       '8px 18px 4px',
                  fontSize:      11,
                  fontWeight:    700,
                  letterSpacing: 2,
                  color:         'var(--yellow)',
                  textTransform: 'uppercase',
                  fontFamily:    "'Inter', sans-serif",
                }}>
                  {section}
                </div>

                {/* Nav items */}
                {items.map(({ label, href }) => {
                  const active = router.pathname === href;
                  return (
                    <Link key={href} href={href}>
                      <a
                        style={{
                          display:        'flex',
                          alignItems:     'center',
                          justifyContent: 'space-between',
                          padding:        '9px 18px',
                          fontSize:       13.5,
                          fontWeight:     active ? 600 : 400,
                          color:          active ? 'var(--white)' : 'var(--silver)',
                          background:     active ? 'var(--accent-glow)' : 'transparent',
                          textDecoration: 'none',
                          transition:     'all 0.12s',
                          position:       'relative',
                          fontFamily:     "'Inter', sans-serif",
                        }}
                        onMouseEnter={e => {
                          if (!active) {
                            e.currentTarget.style.color      = 'var(--white)';
                            e.currentTarget.style.background = 'rgba(255,255,255,0.04)';
                          }
                        }}
                        onMouseLeave={e => {
                          if (!active) {
                            e.currentTarget.style.color      = 'var(--silver)';
                            e.currentTarget.style.background = 'transparent';
                          }
                        }}
                      >
                        <span>{label}</span>

                        {/* Active indicator — right-side cyan bar */}
                        {active && (
                          <div style={{
                            position:     'absolute',
                            right:        0,
                            top:          '20%',
                            height:       '60%',
                            width:        3,
                            background:   'var(--accent)',
                            borderRadius: '3px 0 0 3px',
                            boxShadow:    '0 0 8px var(--accent)',
                          }} />
                        )}
                      </a>
                    </Link>
                  );
                })}
              </div>
            ))}
          </nav>

          {/* ── Sidebar footer ── */}
          <div style={{
            padding:    '14px 18px',
            borderTop:  '1px solid var(--navy-border)',
            fontSize:   11,
            color:      'var(--silver-dim)',
            fontFamily: "'Inter', sans-serif",
            lineHeight: 1.6,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
              <div style={{
                width:        6,
                height:       6,
                borderRadius: '50%',
                background:   'var(--accent)',
                boxShadow:    '0 0 4px var(--accent)',
              }} />
              <span>Updated daily</span>
            </div>
            <span style={{ paddingLeft: 12, color: 'var(--navy-border)', fontSize: 10 }}>
              10:00 AM ET · via GitHub Actions
            </span>
          </div>
        </aside>

        {/* ── Main content area ─────────────────────────────────────────────── */}
        <main style={{
          marginLeft:    'var(--sidebar-w)',
          flex:          1,
          display:       'flex',
          flexDirection: 'column',
          minHeight:     '100vh',
        }}>

          {/* ── Top header bar ── */}
          <header style={{
            height:       'var(--topbar-h)',
            padding:      '0 32px',
            background:   'var(--navy-mid)',
            borderBottom: '1px solid var(--navy-border)',
            display:      'flex',
            alignItems:   'center',
            justifyContent: 'space-between',
            position:     'sticky',
            top:          0,
            zIndex:       50,
          }}>

            <div />

            {/* Refresh button */}
            <button
              onClick={() => window.location.reload()}
              title="Refresh page"
              style={{
                padding:    '6px 8px',
                background: 'transparent',
                border:     'none',
                cursor:     'pointer',
                color:      'var(--silver)',
                borderRadius: 6,
                display:    'flex',
                alignItems: 'center',
                transition: 'color 0.15s, background 0.15s',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.color      = 'var(--accent)';
                e.currentTarget.style.background = 'var(--accent-glow)';
              }}
              onMouseLeave={e => {
                e.currentTarget.style.color      = 'var(--silver)';
                e.currentTarget.style.background = 'transparent';
              }}
            >
              {/* Refresh SVG icon */}
              <svg
                width="18" height="18" viewBox="0 0 24 24"
                fill="none" stroke="currentColor"
                strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
              >
                <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
                <path d="M21 3v5h-5" />
                <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
                <path d="M8 16H3v5" />
              </svg>
            </button>
          </header>

          {/* ── Page content ── */}
          <div style={{
            flex:       1,
            padding:    '32px',
            background: 'var(--navy-dark)',
          }}>
            {children}
          </div>
        </main>
      </div>
    </>
  );
}
