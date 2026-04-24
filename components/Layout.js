import Head from 'next/head';
import Image from 'next/image';
import Link from 'next/link';
import { useRouter } from 'next/router';

// ── Navigation structure ───────────────────────────────────────────────────────
// Add new pages here — they appear in the sidebar automatically.
const NAV = [
  {
    section: 'Games',
    items: [
      { label: 'Overview',      href: '/games' },
      { label: 'Log5',          href: '/games/log5' },
      { label: 'Research-Based',href: '/games/research' },
      { label: 'XGBoost',       href: '/games/xgboost' },
      { label: 'Random Forest', href: '/games/random-forest' },
      { label: 'Composite',     href: '/games/composite' },
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
      { label: 'Overview',        href: '/pitchers' },
      { label: 'Strikeout Model', href: '/pitchers/strikeout' },
    ],
  },
];

export default function Layout({ children, title = 'Dashboard' }) {
  const router = useRouter();

  // Build page title for <head>
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

        {/* ── Sidebar ────────────────────────────────────────────────────────── */}
        <aside style={{
          width:        'var(--sidebar-w)',
          background:   'var(--navy-mid)',
          borderRight:  '1px solid var(--navy-border)',
          position:     'fixed',
          top: 0, left: 0, bottom: 0,
          display:      'flex',
          flexDirection:'column',
          overflowY:    'auto',
          zIndex:       100,
        }}>

          {/* ── Logo / wordmark ── */}
          <Link href="/">
            <div style={{
              padding:       '18px 16px',
              borderBottom:  '1px solid var(--navy-border)',
              cursor:        'pointer',
              display:       'flex',
              alignItems:    'center',
              gap:           12,
              transition:    'background 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'var(--navy-hover)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <Image
                src="/images/logo-blue.png"
                alt="Chalk Line Labs"
                width={44}
                height={44}
                style={{ objectFit: 'contain', flexShrink: 0 }}
              />
              <div>
                <div style={{
                  fontFamily:  "'Barlow Condensed', sans-serif",
                  fontWeight:  800,
                  fontSize:    16,
                  letterSpacing: 0.5,
                  color:       'var(--white)',
                  lineHeight:  1.15,
                }}>
                  CHALK LINE
                </div>
                <div style={{
                  fontFamily:  "'Barlow Condensed', sans-serif",
                  fontWeight:  600,
                  fontSize:    13,
                  letterSpacing: 2,
                  color:       'var(--accent)',
                }}>
                  LABS
                </div>
              </div>
            </div>
          </Link>

          {/* ── Nav sections ── */}
          <nav style={{ flex: 1, padding: '12px 0' }}>
            {NAV.map(({ section, items }) => (
              <div key={section} style={{ marginBottom: 8 }}>

                {/* Section label */}
                <div style={{
                  padding:       '6px 18px 4px',
                  fontSize:      10,
                  fontWeight:    600,
                  letterSpacing: 2,
                  color:         'var(--silver-dim)',
                  textTransform: 'uppercase',
                  fontFamily:    "'DM Mono', monospace",
                }}>
                  {section}
                </div>

                {/* Nav items */}
                {items.map(({ label, href }) => {
                  const active = router.pathname === href;
                  return (
                    <Link key={href} href={href}>
                      <div style={{
                        padding:    '8px 18px',
                        fontSize:   13.5,
                        fontWeight: active ? 600 : 400,
                        color:      active ? 'var(--white)' : 'var(--silver)',
                        background: active ? 'var(--accent-glow)' : 'transparent',
                        borderLeft: active
                          ? '3px solid var(--accent)'
                          : '3px solid transparent',
                        cursor:     'pointer',
                        transition: 'all 0.12s',
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
                        {label}
                      </div>
                    </Link>
                  );
                })}
              </div>
            ))}
          </nav>

          {/* ── Sidebar footer ── */}
          <div style={{
            padding:     '14px 18px',
            borderTop:   '1px solid var(--navy-border)',
            fontSize:    11,
            color:       'var(--silver-dim)',
            fontFamily:  "'DM Mono', monospace",
            lineHeight:  1.6,
          }}>
            Updated daily · 10 AM ET<br />
            <span style={{ color: 'var(--navy-border)' }}>via GitHub Actions</span>
          </div>
        </aside>

        {/* ── Main content area ──────────────────────────────────────────────── */}
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
            background:   'var(--navy)',
            borderBottom: '1px solid var(--navy-border)',
            position:     'sticky',
            top:          0,
            zIndex:       50,
            display:      'flex',
            alignItems:   'center',
            gap:          10,
          }}>
            <span style={{
              fontSize:   12,
              color:      'var(--silver-dim)',
              fontFamily: "'Barlow Condensed', sans-serif",
              fontWeight: 600,
              letterSpacing: 0.5,
            }}>
              Chalk Line Labs
            </span>
            <span style={{ color: 'var(--navy-border)', fontSize: 16 }}>›</span>
            <h1 style={{
              fontFamily:    "'Barlow Condensed', sans-serif",
              fontWeight:    700,
              fontSize:      19,
              letterSpacing: 0.3,
              color:         'var(--white)',
            }}>
              {title}
            </h1>
          </header>

          {/* ── Page content ── */}
          <div style={{ padding: '32px 36px', flex: 1 }}>
            {children}
          </div>

          {/* ── Page footer ── */}
          <footer style={{
            padding:     '18px 36px',
            borderTop:   '1px solid var(--navy-border)',
            fontSize:    12,
            color:       'var(--silver-dim)',
            fontFamily:  "'DM Mono', monospace",
            display:     'flex',
            gap:         16,
            flexWrap:    'wrap',
          }}>
            <span>Chalk Line Labs</span>
            <span style={{ color: 'var(--navy-border)' }}>·</span>
            <span>Data via MLB StatsAPI</span>
            <span style={{ color: 'var(--navy-border)' }}>·</span>
            <span>Predictions updated daily via GitHub Actions</span>
          </footer>
        </main>
      </div>
    </>
  );
}
