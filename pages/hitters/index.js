import Layout from '../../components/Layout'
import { ModelCard, PageHeader } from '../../components/PredictionTable'

const MODELS = [
  {
    title: 'Log5 Hit Model',
    description: 'Hit probability from batter batting average vs. pitcher opponent batting average.',
    href: '/hitters/log5-hit',
    tag: 'Formula-Based',
  },
  {
    title: 'ML Hit Model',
    description: 'Machine learning model using exit velocity, launch angle, and contact rate.',
    href: '/hitters/ml-hit',
    tag: 'Machine Learning',
  },
  {
    title: 'HR Model',
    description: 'Home run probability using barrel rate, pull%, fly ball rate, and park factors.',
    href: '/hitters/hr-model',
    tag: 'HR Prediction',
  },
]

export default function HittersHub() {
  return (
    <Layout title="Hitter Predictions">
      <PageHeader tag="Hitters" title="HITTER PREDICTIONS"
        subtitle="Three models for projecting individual batter performance for today's games." />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
        {MODELS.map(m => <ModelCard key={m.href} {...m} />)}
      </div>
    </Layout>
  )
}
