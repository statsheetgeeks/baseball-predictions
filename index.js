import Image from 'next/image';
import Layout from '../components/Layout';
import Link from 'next/link';

const CARDS = [
  {
    href: '/games',
    icon: '🏟',
    title: 'Games',
    desc: 'Win probability models for every game on today\'s slate.',
    models: ['Log5', 'Research', 'XGBoost', 'Random Forest', 'Composite'],
  },
  {
    href: '/hitters',
    icon: '🏏',
    title: 'Hitters',
    desc: 'At-bat hit probability and home run projections by player.',
    models: ['Log5 Hit', 'ML Hit', 'HR Model'],
  },
  {
    href: '/pitchers',
    icon: '⚡',
    title: 'Pitchers',
    desc: 'Projected strikeout totals for starting and relief arms.',
    models: ['Strikeout Model'],
  },
];

export default function Home() {
  return (
    <Layout title="Dashboard">

      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 36,
        marginBottom: 48,
        paddingBottom: 36,
        borderBottom: '1px solid var(--navy-border)',
      }}>
        <Image
          src="/images/logo-blue.png"
          alt="Chalk Line Labs"
          width={130}
          height={130}
          style={{ objectFit: 'contain', flexShrink: 0 }}
        />
        <div>
          <div style={{
            fontFamily: "'Barlow Condensed', sans-serif",
            fontWeight: 900,
            fontSize: 46,
            letterSpacing: 1,
            lineHeight: 1.05,
            color: 'var(--white)',
            marginBottom: 10,
          }}>
            CHALK LINE LABS
          </div>
          <div style={{
            fontFamily: "'Barlow Condensed', sans-serif",
            fontWeight: 600,
            fontSize: 18,
            color: 'var(--silver)',
            letterSpacing: 2,
            textTransform: 'uppercase',
            marginBottom: 14,
          }}>
            MLB Prediction Dashboard
          </div>
          <p style={{ color: 'var(--silver-dim)', fontSize: 14.5, maxWidth: 480, lineHeight: 1.6 }}>
            Machine-learning models run every morning and publish fresh predictions before first pitch.
            Built on Log5, XGBoost, Random Forest, and blended composites.
          </p>
        </div>
      </div>

      {/* ── Model category cards ─────────────────────────────────────────── */}
      <div style={{
        fontFamily: "'Barlow Condensed', sans-serif",
        fontWeight: 700,
        fontSize: 13,
        letterSpacing: 2,
        textTransform: 'uppercase',
        color: 'var(--silver-dim)',
        marginBottom: 18,
      }}>
        Today's Models
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 18 }}>
        {CARDS.map(card => (
          <Link key={card.href} href={card.href}>
            <div style={{
              background: 'var(--navy)',
              border: '1px solid var(--navy-border)',
              borderRadius: 10,
              padding: '24px 22px',
              cursor: 'pointer',
              transition: 'border-color 0.15s, transform 0.15s, box-shadow 0.15s',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.borderColor = 'var(--accent)';
              e.currentTarget.style.transform = 'translateY(-2px)';
              e.currentTarget.style.boxShadow = '0 8px 32px rgba(74,144,217,0.15)';
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = 'var(--navy-border)';
              e.currentTarget.style.transform = 'none';
              e.currentTarget.style.boxShadow = 'none';
            }}>
              <div style={{ fontSize: 26, marginBottom: 10 }}>{card.icon}</div>
              <div style={{
                fontFamily: "'Barlow Condensed', sans-serif",
                fontWeight: 700,
                fontSize: 22,
                color: 'var(--white)',
                marginBottom: 8,
              }}>
                {card.title}
              </div>
              <p style={{ color: 'var(--silver-dim)', fontSize: 13.5, marginBottom: 18, lineHeight: 1.55 }}>
                {card.desc}
              </p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {card.models.map(m => (
                  <span key={m} style={{
                    padding: '3px 9px',
                    borderRadius: 4,
                    background: 'rgba(74,144,217,0.1)',
                    border: '1px solid var(--accent-dim)',
                    color: 'var(--accent)',
                    fontSize: 11,
                    fontFamily: "'DM Mono', monospace",
                  }}>
                    {m}
                  </span>
                ))}
              </div>
            </div>
          </Link>
        ))}
      </div>
    </Layout>
  );
}
