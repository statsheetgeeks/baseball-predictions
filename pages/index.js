import Layout from '../components/Layout'
import { ModelCard, StatBox } from '../components/PredictionTable'

const CATEGORIES = [
  {
    title: 'Game Predictions',
    description: '5 models — Log5, Research-Based, XGBoost, Random Forest, and Composite ensemble.',
    href: '/games',
    tag: 'Win Probability',
  },
  {
    title: 'Hitter Predictions',
    description: '3 models — Log5 hit probability, ML hit model, and home run probability.',
    href: '/hitters',
    tag: 'Batter Performance',
  },
  {
    title: 'Pitcher Predictions',
    description: '1 model — Strikeout projections for starting pitchers.',
    href: '/pitchers',
    tag: 'Pitcher Performance',
  },
]

export default function Home() {
  return (
    <Layout title="Home">

      {/* Hero */}
      <div style={{ marginBottom: '3rem' }}>
        <div className="mono" style={{ fontSize: 11, color: 'var(--red)', letterSpacing: '0.15em',
                                       textTransform: 'uppercase', marginBottom: 16 }}>
          MLB Analytics Platform
        </div>
        <h1 className="display" style={{ fontSize: '3.5rem', color: 'var(--text)', lineHeight: 1.05, marginBottom: 16 }}>
          DATA-DRIVEN<br />
          <span style={{ color: 'var(--red)' }}>BASEBALL</span><br />
          PREDICTIONS
        </h1>
        <p style={{ fontSize: 14, color: 'var(--muted)', maxWidth: 500, lineHeight: 1.7 }}>
          Statistical and machine learning models for MLB game outcomes, individual hitter 
          performance, and pitcher projections — powered by the MLB Statsapi, updated daily.
        </p>
      </div>

      {/* Quick stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                    gap: 12, marginBottom: '3rem' }}>
        <StatBox label="Models" value="9" sub="Prediction models" />
        <StatBox label="Categories" value="3" sub="Games · Hitters · Pitchers" />
        <StatBox label="Data" value="MLB" sub="Official Statsapi" />
        <StatBox label="Updated" value="Daily" sub="Via GitHub Actions" />
      </div>

      {/* Category cards */}
      <div style={{ marginBottom: '1rem' }}>
        <div className="mono" style={{ fontSize: 10, color: 'var(--muted)', letterSpacing: '0.1em',
                                       textTransform: 'uppercase', marginBottom: 16 }}>
          Browse by Category
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
          {CATEGORIES.map(c => <ModelCard key={c.href} {...c} />)}
        </div>
      </div>
    </Layout>
  )
}
