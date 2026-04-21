import Layout from '../../components/Layout'
import { ModelCard, PageHeader } from '../../components/PredictionTable'

const MODELS = [
  {
    title: 'Log5 Model',
    description: 'Win probability from team winning percentages using Bill James\' Log5 formula.',
    href: '/games/log5',
    tag: 'Formula-Based',
  },
  {
    title: 'Research-Based Model',
    description: 'Pythagorean expectation, run differential, starting pitcher ERA, and home field advantage.',
    href: '/games/research',
    tag: 'Statistical',
  },
  {
    title: 'XGBoost Model',
    description: 'Gradient boosted trees trained on Statcast and MLB API features.',
    href: '/games/xgboost',
    tag: 'ML · XGBoost',
  },
  {
    title: 'Random Forest Model',
    description: 'Ensemble decision tree model using batting, pitching, and recent form data.',
    href: '/games/random-forest',
    tag: 'ML · Random Forest',
  },
  {
    title: 'Composite Model',
    description: 'Weighted ensemble across all four game prediction models.',
    href: '/games/composite',
    tag: 'Ensemble',
  },
]

export default function GamesHub() {
  return (
    <Layout title="Game Predictions">
      <PageHeader
        tag="Games"
        title="GAME PREDICTIONS"
        subtitle="Five models predicting today's MLB game outcomes. Click a model to see its full prediction table."
      />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
        {MODELS.map(m => <ModelCard key={m.href} {...m} />)}
      </div>
    </Layout>
  )
}
