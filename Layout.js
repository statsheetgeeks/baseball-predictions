import Image from 'next/image';
import Link from 'next/link';
import { useRouter } from 'next/router';

// ── Navigation ────────────────────────────────────────────────────────────────
const NAV = [
  {
    section: 'Games',
    items: [
      { label: 'Overview',       href: '/games' },
      { label: 'Log5',           href: '/games/log5' },
      { label: 'Research',       href: '/games/research' },
      { label: 'XGBoost',        href: '/games/xgboost' },
      { label: 'Random Forest',  href: '/games/random-forest' },
      { label: 'Composite',      href: '/games/composite' },
    ],
  },
  {
    section: 'Hitters',
    items: [
      { label: 'Overview',  href: '/hitters' },
      { label: 'Log5 Hit',  href: '/hitters/log5-hit' },
      { label: 'ML Hit',    href: '/hitters/ml-hit' },
      { label: 'HR Model',  href: '/hitters/hr-model' },
    ],
  },
  {
    section: 'Pitchers',
    items: [
      { label: 'Overview',    href: '/pitchers' },
      { label: 'Strikeouts',  href: '/pitchers/strikeout' },
    ],
  },
];

export default function Layout({ children, title = 'Dashboard' }) {
  const router = useRouter();

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>

      {/* ── Sidebar ──────────────────────────────────────────────────────── */}
      <aside style={{
        width: 'var(--sidebar-w)',
        background: 'var(--navy-mid)',
        borderRight: '1px solid var(--navy-border)',
        position: 'fixed',
        top: 0, left: 0, bottom: 0,
        display: 'flex',
        flexDirection: 'column',
        overflowY: 'auto',
        zIndex: 100,
      }}>

        {/* Logo block */}
        <Link href="/">
          <div style={{
            padding: '20px 16px 18px',
            borderBottom: '1px solid var(--navy-border)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
          }}>
            <Image
              src="/images/logo-blue.png"
              alt="Chalk Line Labs"
              width={48}
              height={48}
              style={{ objectFit: 'contain', flexShrink: 0 }}
            />
            <div>
              <div style={{
                fontFamily: "'Barlow Condensed', sans-serif",
                fontWeight: 800,
                fontSize: 15,
                letterSpacing: 0.5,
                color: 'var(--white)',
                lineHeight: 1.2,
              }}>
                CHALK LINE<br />
                <span style={{ color: 'var(--silver)', fontWeight: 600, fontSize: 13 }}>LABS</span>
              </div>
            </div>
          </div>
        </Link>

        {/* Nav */}
        <nav style={{ flex: 1, padding: '14px 0' }}>
          {NAV.map(({ section, items }) => (
            <div key={section} style={{ marginBottom: 10 }}>
              <div style={{
                padding: '5px 18px',
                fontSize: 10,
                fontWeight: 600,
                letterSpacing: 1.8,
                color: 'var(--silver-dim)',
                textTransform: 'uppercase',
                fontFamily: "'DM Mono', monospace",
              }}>
                {section}
              </div>
              {items.map(({ label, href }) => {
                const active = router.pathname === href;
                return (
                  <Link key={href} href={href}>
                    <div style={{
                      padding: '8px 18px',
                      fontSize: 13.5,
                      fontWeight: active ? 600 : 400,
                      color: active ? 'var(--white)' : 'var(--silver)',
                      background: active ? 'rgba(74,144,217,0.18)' : 'transparent',
                      borderLeft: active ? '3px solid var(--accent)' : '3px solid transparent',
                      cursor: 'pointer',
                      transition: 'all 0.15s',
                    }}
                    onMouseEnter={e => { if (!active) { e.currentTarget.style.color = 'var(--white)'; e.currentTarget.style.background = 'rgba(255,255,255,0.05)'; }}}
                    onMouseLeave={e => { if (!active) { e.currentTarget.style.color = 'var(--silver)'; e.currentTarget.style.background = 'transparent'; }}}
                    >
                      {label}
                    </div>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div style={{
          padding: '14px 18px',
          borderTop: '1px solid var(--navy-border)',
          fontSize: 11,
          color: 'var(--silver-dim)',
          fontFamily: "'DM Mono', monospace",
        }}>
          Updated daily · 10 AM ET
        </div>
      </aside>

      {/* ── Main ─────────────────────────────────────────────────────────── */}
      <main style={{
        marginLeft: 'var(--sidebar-w)',
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        minHeight: '100vh',
      }}>
        {/* Top bar */}
        <header style={{
          padding: '0 32px',
          height: 56,
          borderBottom: '1px solid var(--navy-border)',
          background: 'var(--navy)',
          position: 'sticky',
          top: 0,
          zIndex: 50,
          display: 'flex',
          alignItems: 'center',
          gap: 16,
        }}>
          {/* Breadcrumb-style title */}
          <span style={{ color: 'var(--silver-dim)', fontSize: 13 }}>Chalk Line Labs</span>
          <span style={{ color: 'var(--navy-border)', fontSize: 13 }}>›</span>
          <h1 style={{
            fontFamily: "'Barlow Condensed', sans-serif",
            fontWeight: 700,
            fontSize: 18,
            letterSpacing: 0.4,
            color: 'var(--white)',
          }}>
            {title}
          </h1>
        </header>

        {/* Content */}
        <div style={{ padding: '30px 36px', flex: 1 }}>
          {children}
        </div>
      </main>
    </div>
  );
}
