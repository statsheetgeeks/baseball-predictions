import Layout from '../../components/Layout'
import { ModelCard, PageHeader } from '../../components/PredictionTable'

const MODELS = [
  {
    title: 'Log5 Hit Model',
    description: 'Hit probability from batter batting average vs. pitcher opponent batting average using Bill James\' Log5 formula.',
    href: '/hitters/log5-hit',
    tag: 'Formula-Based',
  },
  {
    title: 'ML Hit Model',
    description: 'Multi-layer perceptron hit probability model using exit velocity, launch angle, and contact rate from Statcast.',
    href: '/hitters/ml-hit',
    tag: 'ML · Neural Net',
  },
  {
    title: 'HR Model',
    description: 'Deterministic home run score (0–100) using barrel rate, pull%, fly ball rate, park factors, and pitcher vulnerability.',
    href: '/hitters/hr-model',
    tag: 'HR Prediction',
  },
  {
    title: 'ML HR Model',
    description: 'Poisson XGBoost model predicting expected home run rate (λ) trained on Statcast, weather, park, and handedness features.',
    href: '/hitters/ml-hr',
    tag: 'ML · XGBoost',
  },
  {
    title: 'Composite Model',
    description: 'Spotlight hitters appearing in 2+ of the four top-25 lists, ranked across Log5 Hit, ML Hit, HR Model, and ML HR.',
    href: '/hitters/composite',
    tag: 'Ensemble',
  },
]

export default function HittersHub() {
  return (
    <Layout title="Hitter Predictions">
      <PageHeader
        tag="Hitters"
        title="HITTER PREDICTIONS"
        subtitle="Five models for projecting individual batter performance for today's games. Click a model to see its full prediction table."
      />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
        {MODELS.map(m => <ModelCard key={m.href} {...m} />)}
      </div>
    </Layout>
  )
}
