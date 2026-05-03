import Image from 'next/image';
import Link from 'next/link';
import Layout from '../components/Layout';

const CARDS = [
  {
    href:    '/games',
    tag:     'Win Probability',
    title:   'Game Predictions',
    desc:    'Five models predicting today\'s MLB game outcomes. Log5, Research-Based, XGBoost, Random Forest, and Composite ensemble.',
    models:  ['Log5', 'Research-Based', 'XGBoost', 'Random Forest', 'Composite'],
    count:   5,
  },
  {
    href:    '/hitters',
    tag:     'Batter Performance',
    title:   'Hitter Predictions',
    desc:    'Five models projecting hit probability, home run likelihood, and Spotlight hitters for everyone in today\'s lineups.',
    models:  ['Log5 Hit', 'ML Hit Model', 'HR Model', 'ML HR Model', 'Composite'],
    count:   5,
  },
  {
    href:    '/pitchers',
    tag:     'Pitcher Performance',
    title:   'Pitcher Predictions',
    desc:    'Projected strikeout totals for every starting pitcher on today\'s slate.',
    models:  ['Strikeout Model'],
    count:   1,
  },
];

const STATS = [
  { value: '11',    label: 'Prediction Models' },
  { value: '3',     label: 'Categories' },
  { value: 'MLB',   label: 'Official StatsAPI' },
  { value: 'Daily', label: 'Via GitHub Actions' },
];

export default function Home() {
  return (
    <Layout title="Dashboard">

      {/* ── Hero ──────────────────────────────────────────────────────────── */}
      <div style={{
        display:       'flex',
        alignItems:    'center',
        gap:           36,
        marginBottom:  44,
        paddingBottom: 36,
        borderBottom:  '1px solid var(--navy-border)',
        flexWrap:      'wrap',
      }}>
        <Image
          src="/images/logo-blue.png"
          alt="Chalk Line Labs"
          width={120}
          height={120}
          style={{ objectFit: 'contain', flexShrink: 0 }}
          priority
        />
        <div>
          <div style={{
            fontFamily:    "'Barlow Condensed', sans-serif",
            fontWeight:    900,
            fontSize:      48,
            letterSpacing: 1,
            lineHeight:    1,
            color:         'var(--white)',
            marginBottom:  8,
          }}>
            CHALK LINE LABS
          </div>
          <div style={{
            fontFamily:    "'Barlow Condensed', sans-serif",
            fontWeight:    600,
            fontSize:      16,
            letterSpacing: 3,
            textTransform: 'uppercase',
            color:         'var(--accent)',
            marginBottom:  14,
          }}>
            MLB Prediction Dashboard
          </div>
          <p style={{
            color:      'var(--silver)',
            fontSize:   14.5,
            maxWidth:   520,
            lineHeight: 1.65,
          }}>
            Statistical and machine-learning models for MLB game outcomes, individual
            hitter performance, and pitcher projections — powered by the MLB StatsAPI,
            updated daily.
          </p>
        </div>
      </div>

      {/* ── Stats bar ────────────────────────────────────────────────────── */}
      <div style={{
        display:       'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
        gap:           1,
        background:    'var(--navy-border)',
        border:        '1px solid var(--navy-border)',
        borderRadius:  10,
        overflow:      'hidden',
        marginBottom:  40,
      }}>
        {STATS.map(s => (
          <div key={s.label} style={{
            background:  'var(--navy)',
            padding:     '18px 20px',
            textAlign:   'center',
          }}>
            <div style={{
              fontFamily:    "'Barlow Condensed', sans-serif",
              fontWeight:    800,
              fontSize:      28,
              color:         'var(--white)',
              lineHeight:    1,
              marginBottom:  4,
            }}>
              {s.value}
            </div>
            <div style={{
              fontSize:   11,
              color:      'var(--silver-dim)',
              fontFamily: "'DM Mono', monospace",
              letterSpacing: 0.5,
            }}>
              {s.label}
            </div>
          </div>
        ))}
      </div>

      {/* ── Section label ────────────────────────────────────────────────── */}
      <div style={{
        fontFamily:    "'Barlow Condensed', sans-serif",
        fontWeight:    700,
        fontSize:      12,
        letterSpacing: 2.5,
        textTransform: 'uppercase',
        color:         'var(--silver-dim)',
        marginBottom:  16,
      }}>
        Browse by Category
      </div>

      {/* ── Category cards ───────────────────────────────────────────────── */}
      <div style={{
        display:             'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))',
        gap:                 20,
      }}>
        {CARDS.map(card => (
          <Link key={card.href} href={card.href}>
            <div style={{
              background:   'var(--navy)',
              border:       '1px solid var(--navy-border)',
              borderRadius: 10,
              padding:      '26px 24px',
              cursor:       'pointer',
              height:       '100%',
              transition:   'border-color 0.15s, box-shadow 0.15s, transform 0.15s',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.borderColor = 'var(--accent)';
              e.currentTarget.style.boxShadow   = '0 8px 32px rgba(74,144,217,0.12)';
              e.currentTarget.style.transform   = 'translateY(-2px)';
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = 'var(--navy-border)';
              e.currentTarget.style.boxShadow   = 'none';
              e.currentTarget.style.transform   = 'none';
            }}
            >
              {/* Tag */}
              <div style={{
                display:       'inline-block',
                padding:       '3px 9px',
                borderRadius:  4,
                background:    'var(--accent-glow)',
                border:        '1px solid rgba(74,144,217,0.3)',
                color:         'var(--accent)',
                fontSize:      11,
                fontFamily:    "'DM Mono', monospace",
                fontWeight:    500,
                marginBottom:  14,
                letterSpacing: 0.3,
              }}>
                {card.tag}
              </div>

              {/* Title */}
              <div style={{
                fontFamily:    "'Barlow Condensed', sans-serif",
                fontWeight:    700,
                fontSize:      24,
                color:         'var(--white)',
                marginBottom:  10,
              }}>
                {card.title}
              </div>

              {/* Description */}
              <p style={{
                color:        'var(--silver)',
                fontSize:     13.5,
                lineHeight:   1.6,
                marginBottom: 20,
              }}>
                {card.desc}
              </p>

              {/* Model chips */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 20 }}>
                {card.models.map(m => (
                  <span key={m} style={{
                    padding:       '3px 9px',
                    borderRadius:  4,
                    background:    'rgba(184,197,211,0.07)',
                    border:        '1px solid var(--navy-border)',
                    color:         'var(--silver)',
                    fontSize:      11,
                    fontFamily:    "'DM Mono', monospace",
                  }}>
                    {m}
                  </span>
                ))}
              </div>

              {/* CTA */}
              <div style={{
                display:     'flex',
                alignItems:  'center',
                gap:         6,
                color:       'var(--accent)',
                fontSize:    13,
                fontFamily:  "'Barlow Condensed', sans-serif",
                fontWeight:  700,
                letterSpacing: 1,
              }}>
                VIEW PREDICTIONS
                <span style={{ fontSize: 16 }}>→</span>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </Layout>
  );
}
