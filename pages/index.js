import Link from 'next/link';
import Layout from '../components/Layout';

// ── Category cards ────────────────────────────────────────────────────────────
const CARDS = [
  {
    href:   '/games',
    tag:    'Win Probability',
    title:  'Game Predictions',
    desc:   "Five models predicting today's MLB game outcomes. Log5, Research-Based, XGBoost, Random Forest, and Composite ensemble.",
    bars:   [60, 75, 50, 85, 70],
    footer: 'Model Ensemble Performance',
  },
  {
    href:   '/hitters',
    tag:    'Batter Performance',
    title:  'Hitter Predictions',
    desc:   "Five models projecting hit probability, home run likelihood, and Spotlight hitters for everyone in today's lineups.",
    bars:   [65, 72, 58, 80, 68],
    footer: 'Model Accuracy (Last 30 Days)',
  },
  {
    href:   '/pitchers',
    tag:    'Pitcher Performance',
    title:  'Pitcher Predictions',
    desc:   "Projected strikeout totals for every starting pitcher on today's slate. Strikeout model performance insights.",
    bars:   [55, 70, 62, 78, 65],
    footer: 'Strikeout Model Performance',
  },
];

// ── KPI stats ─────────────────────────────────────────────────────────────────
const STATS = [
  { value: '11',    label: 'Prediction Models' },
  { value: '3',     label: 'Categories' },
  { value: 'MLB',   label: 'Data Source' },
  { value: 'Daily', label: 'Updates' },
];

export default function Home() {
  return (
    <Layout title="Dashboard">

      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <div style={{ marginBottom: 48 }}>
        <h1 style={{
          fontFamily:    "'Sora', sans-serif",
          fontWeight:    700,
          fontSize:      'clamp(2rem, 5vw, 3rem)',
          color:         'var(--white)',
          lineHeight:    1,
          marginBottom:  8,
          letterSpacing: 1,
        }}>
          CHALK LINE LABS
        </h1>
        <p style={{
          fontFamily:    "'Sora', sans-serif",
          fontWeight:    600,
          fontSize:      14,
          letterSpacing: 3,
          textTransform: 'uppercase',
          color:         'var(--accent)',
          marginBottom:  16,
        }}>
          MLB Prediction Dashboard
        </p>
        <p style={{
          fontFamily: "'Inter', sans-serif",
          fontSize:   14.5,
          color:      'var(--silver)',
          maxWidth:   540,
          lineHeight: 1.65,
        }}>
          Statistical and machine-learning models for MLB game outcomes, individual
          hitter performance, and pitcher projections — powered by the MLB StatsAPI,
          updated daily.
        </p>
      </div>

      {/* ── KPI stats row ─────────────────────────────────────────────────── */}
      <div style={{
        display:             'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
        gap:                 16,
        marginBottom:        48,
      }}>
        {STATS.map(s => (
          <div key={s.label} className="card-neon" style={{ textAlign: 'center', padding: '1.25rem 1rem' }}>
            <div style={{
              fontFamily:   "'Sora', sans-serif",
              fontWeight:   700,
              fontSize:     28,
              color:        'var(--accent)',
              lineHeight:   1,
              marginBottom: 6,
            }}>
              {s.value}
            </div>
            <div style={{
              fontFamily:    "'Inter', sans-serif",
              fontSize:      11,
              color:         'var(--silver-dim)',
              letterSpacing: 0.5,
            }}>
              {s.label}
            </div>
          </div>
        ))}
      </div>

      {/* ── Browse by Category ────────────────────────────────────────────── */}
      <div style={{
        fontFamily:    "'Sora', sans-serif",
        fontWeight:    700,
        fontSize:      12,
        letterSpacing: 2.5,
        textTransform: 'uppercase',
        color:         'var(--silver-dim)',
        marginBottom:  16,
      }}>
        Browse by Category
      </div>

      <div style={{
        display:             'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
        gap:                 20,
        marginBottom:        48,
      }}>
        {CARDS.map(card => (
          <Link key={card.href} href={card.href}>
            <a className="card-neon" style={{ display: 'block', textDecoration: 'none', cursor: 'pointer' }}>

              {/* Card header */}
              <div style={{ marginBottom: 12 }}>
                <div className="tag" style={{ marginBottom: 8 }}>{card.tag}</div>
                <h3 style={{
                  fontFamily:   "'Sora', sans-serif",
                  fontWeight:   700,
                  fontSize:     '1.15rem',
                  color:        'var(--white)',
                  marginBottom: 4,
                  lineHeight:   1.2,
                }}>
                  {card.title}
                </h3>
              </div>

              {/* Description */}
              <p style={{
                fontFamily:   "'Inter', sans-serif",
                fontSize:     13,
                color:        'var(--silver)',
                lineHeight:   1.6,
                marginBottom: 20,
              }}>
                {card.desc}
              </p>

              {/* Micro bar chart */}
              <div style={{
                height:        40,
                background:    'rgba(0,0,0,0.2)',
                borderRadius:  6,
                display:       'flex',
                alignItems:    'flex-end',
                justifyContent:'space-around',
                padding:       '4px 8px',
                marginBottom:  16,
              }}>
                {card.bars.map((h, i) => (
                  <div key={i} style={{
                    width:        4,
                    height:       `${h}%`,
                    background:   'var(--accent)',
                    borderRadius: 2,
                    opacity:      0.7,
                  }} />
                ))}
              </div>

              {/* Footer row */}
              <div style={{
                display:        'flex',
                alignItems:     'center',
                justifyContent: 'space-between',
              }}>
                <span style={{
                  fontFamily: "'Inter', sans-serif",
                  fontSize:   11,
                  color:      'var(--silver-dim)',
                }}>
                  {card.footer}
                </span>
                <span style={{
                  fontFamily:    "'Inter', sans-serif",
                  fontSize:      12,
                  fontWeight:    600,
                  color:         'var(--accent)',
                  letterSpacing: '0.05em',
                }}>
                  View →
                </span>
              </div>
            </a>
          </Link>
        ))}
      </div>

      {/* ── Bottom info row ───────────────────────────────────────────────── */}
      <div style={{
        display:             'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
        gap:                 20,
        paddingTop:          32,
        borderTop:           '1px solid var(--navy-border)',
      }}>

        {/* Overall performance */}
        <div className="card-neon">
          <h3 style={{
            fontFamily:   "'Sora', sans-serif",
            fontWeight:   700,
            fontSize:     '1rem',
            color:        'var(--white)',
            marginBottom: 16,
          }}>
            Overall Model Performance
          </h3>
          <div style={{ marginBottom: 8 }}>
            <div style={{
              display:        'flex',
              justifyContent: 'space-between',
              alignItems:     'flex-end',
              marginBottom:   4,
            }}>
              <span style={{ fontFamily: "'Inter', sans-serif", fontSize: 12, color: 'var(--silver-dim)' }}>
                Accuracy across all models (Last 30 Days)
              </span>
              <span style={{
                fontFamily: "'Sora', sans-serif",
                fontWeight: 700,
                fontSize:   22,
                color:      'var(--accent)',
              }}>
                66.1%
              </span>
            </div>
            <div style={{ fontFamily: "'Inter', sans-serif", fontSize: 11, color: 'var(--accent)' }}>
              ↑ 4.3% vs. previous 30 days
            </div>
          </div>
        </div>

        {/* Data sources */}
        <div className="card-neon">
          <h3 style={{
            fontFamily:   "'Sora', sans-serif",
            fontWeight:   700,
            fontSize:     '1rem',
            color:        'var(--white)',
            marginBottom: 16,
          }}>
            Data Sources
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {[
              { label: 'MLB StatsAPI',    value: 'Live Data' },
              { label: 'GitHub Actions',  value: 'Automation' },
              { label: 'Daily Refresh',   value: '10:00 AM ET' },
            ].map(row => (
              <div key={row.label} style={{
                display:        'flex',
                justifyContent: 'space-between',
                alignItems:     'center',
              }}>
                <span style={{ fontFamily: "'Inter', sans-serif", fontSize: 13, color: 'var(--silver)' }}>
                  {row.label}
                </span>
                <span style={{
                  fontFamily:    "'Inter', sans-serif",
                  fontSize:      11,
                  fontWeight:    600,
                  color:         'var(--accent)',
                  letterSpacing: '0.05em',
                }}>
                  {row.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Footer ───────────────────────────────────────────────────────── */}
      <div style={{
        marginTop:  32,
        paddingTop: 24,
        borderTop:  '1px solid var(--navy-border)',
        display:    'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap:   'wrap',
        gap:        12,
      }}>
        <p style={{ fontFamily: "'Inter', sans-serif", fontSize: 11, color: 'var(--silver-dim)' }}>
          © {new Date().getFullYear()} Chalk Line Labs. All rights reserved.
        </p>
        <div style={{ display: 'flex', gap: 20 }}>
          {['Documentation', 'API Status', 'Support'].map(link => (
            <a
              key={link}
              href="#"
              style={{
                fontFamily:     "'Inter', sans-serif",
                fontSize:       11,
                color:          'var(--silver-dim)',
                textDecoration: 'none',
                transition:     'color 0.15s',
              }}
              onMouseEnter={e => e.currentTarget.style.color = 'var(--accent)'}
              onMouseLeave={e => e.currentTarget.style.color = 'var(--silver-dim)'}
            >
              {link}
            </a>
          ))}
        </div>
      </div>

    </Layout>
  )
}
