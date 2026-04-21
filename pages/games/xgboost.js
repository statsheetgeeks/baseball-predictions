// ─── XGBoost ──────────────────────────────────────────────────────────────────
import Layout from '../../components/Layout'
import PredictionTable, { ProbCell, FavoriteCell, PageHeader } from '../../components/PredictionTable'
import { usePredictions } from '../../components/usePredictions'

/*
 * ─── EXPECTED JSON SHAPE (public/data/games-xgboost.json) ────────────────────
 * {
 *   "updated": "2025-04-20T10:00:00Z",
 *   "predictions": [
 *     {
 *       "home_team":    "Los Angeles Dodgers",
 *       "away_team":    "San Francisco Giants",
 *       "home_prob":    0.634,
 *       "away_prob":    0.366,
 *       "confidence":  "HIGH",      ← optional
 *       "game_time":   "7:10 PM ET"
 *     }, ...
 *   ]
 * }
 */

const XGBOOST_COLS = [
  { key: 'game_time', label: 'Time' },
  { key: 'home_team', label: 'Home' },
  { key: 'away_team', label: 'Away' },
  { key: 'home_prob', label: 'Home Prob', render: v => <ProbCell value={v} /> },
  { key: 'away_prob', label: 'Away Prob', render: v => <ProbCell value={v} /> },
  { key: 'confidence', label: 'Confidence', render: v => v
      ? <span className={`tag ${v === 'HIGH' ? 'tag-green' : 'tag-muted'}`}>{v}</span>
      : '—' },
  { key: 'home_prob', label: 'Pick', render: (v) => <FavoriteCell value={v} /> },
]

export default function XGBoostGame() {
  const { data, updated, loading, error } = usePredictions('games-xgboost')
  return (
    <Layout title="XGBoost Game Model">
      <PageHeader tag="Games → XGBoost" title="XGBOOST GAME MODEL"
        subtitle="Gradient boosted decision trees trained on Statcast features: barrel rate, exit velocity, WHIP, and bullpen metrics." />
      <PredictionTable data={data} columns={XGBOOST_COLS} updated={updated} loading={loading} error={error} />
    </Layout>
  )
}
