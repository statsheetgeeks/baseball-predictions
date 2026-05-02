import Layout from '../../components/Layout'
import { ModelCard, PageHeader } from '../../components/PredictionTable'

const MODELS = [
  {
    title: 'Strikeout Model',
    description: 'Projects strikeout totals for starting pitchers using chase rate, whiff rate, and batter handedness splits from the MLB API.',
    href: '/pitchers/strikeout',
    tag: 'Pitcher Performance',
  },
]

export default function PitchersHub() {
  return (
    <Layout title="Pitcher Predictions">
      <PageHeader
        tag="Pitchers"
        title="PITCHER PREDICTIONS"
        subtitle="Projection models for starting pitcher performance in today's games."
      />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
        {MODELS.map(m => <ModelCard key={m.href} {...m} />)}
      </div>
    </Layout>
  )
}
