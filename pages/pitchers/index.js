import Layout from '../../components/Layout'
import { ModelCard, PageHeader } from '../../components/PredictionTable'

const MODELS = [
  {
    title: 'Strikeout Model',
    description: 'Three approaches projected side by side — Calculation Engine, KNN, and Gradient Boosting (XGBoost) — built on Statcast pitch-level data. Falls back to an expected lineup when today\'s isn\'t posted yet.',
    href: '/pitchers/strikeout',
    tag: 'Calc Engine · KNN · XGBoost',
  },
]

export default function PitchersHub() {
  return (
    <Layout title="Pitcher Predictions">
      <PageHeader
        tag="Pitchers"
        title="PITCHER PREDICTIONS"
        subtitle="Models for projecting individual starting-pitcher performance for today's games. Click a model to see its full prediction table."
      />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
        {MODELS.map(m => <ModelCard key={m.href} {...m} />)}
      </div>
    </Layout>
  )
}
