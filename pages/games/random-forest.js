import Layout from '../../components/Layout'
import PredictionTable, { ProbCell, FavoriteCell, PageHeader } from '../../components/PredictionTable'
import { usePredictions } from '../../components/usePredictions'

/*
 * ─── EXPECTED JSON SHAPE (public/data/games-random-forest.json) ──────────────
 * Same shape as xgboost. Add any extra fields your model outputs.
 */

const COLUMNS = [
  { key: 'game_time', label: 'Time' },
  { key: 'home_team', label: 'Home' },
  { key: 'away_team', label: 'Away' },
  { key: 'home_prob', label: 'Home Prob', render: v => <ProbCell value={v} /> },
  { key: 'away_prob', label: 'Away Prob', render: v => <ProbCell value={v} /> },
  { key: 'home_prob', label: 'Pick',      render: v => <FavoriteCell value={v} /> },
]

export default function RandomForestGame() {
  const { data, updated, loading, error } = usePredictions('games-random-forest')
  return (
    <Layout title="Random Forest Model">
      <PageHeader tag="Games → Random Forest" title="RANDOM FOREST MODEL"
        subtitle="100-tree ensemble using batting stats, pitching metrics, and recent 15-game form from the MLB API." />
      <PredictionTable data={data} columns={COLUMNS} updated={updated} loading={loading} error={error} />
    </Layout>
  )
}
