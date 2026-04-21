import Layout from '../../components/Layout'
import PredictionTable, { ProbCell, FavoriteCell, PageHeader } from '../../components/PredictionTable'
import { usePredictions } from '../../components/usePredictions'

/*
 * ─── EXPECTED JSON SHAPE (public/data/games-log5.json) ───────────────────────
 * {
 *   "updated": "2025-04-20T10:00:00Z",
 *   "predictions": [
 *     {
 *       "home_team":    "Los Angeles Dodgers",
 *       "away_team":    "San Francisco Giants",
 *       "home_win_pct": 0.617,
 *       "away_win_pct": 0.512,
 *       "home_prob":    0.621,
 *       "away_prob":    0.379,
 *       "game_time":    "7:10 PM ET"
 *     },
 *     ...
 *   ]
 * }
 */

const COLUMNS = [
  { key: 'game_time',    label: 'Time' },
  { key: 'home_team',    label: 'Home Team' },
  { key: 'away_team',    label: 'Away Team' },
  { key: 'home_win_pct', label: 'Home Win%', render: v => v != null ? v.toFixed(3) : '—' },
  { key: 'away_win_pct', label: 'Away Win%', render: v => v != null ? v.toFixed(3) : '—' },
  { key: 'home_prob',    label: 'Home Prob',  render: v => <ProbCell value={v} /> },
  { key: 'away_prob',    label: 'Away Prob',  render: v => <ProbCell value={v} /> },
  { key: 'home_prob',    label: 'Pick',       render: (v, row) => <FavoriteCell value={v} /> },
]

export default function Log5Game() {
  const { data, updated, loading, error } = usePredictions('games-log5')

  return (
    <Layout title="Log5 Game Model">
      <PageHeader
        tag="Games → Log5"
        title="LOG5 GAME MODEL"
        subtitle="Win probability derived from each team's season winning percentage using Bill James' Log5 formula: P(A beats B) = (A − AB) / (A + B − 2AB)"
      />
      <PredictionTable
        data={data}
        columns={COLUMNS}
        updated={updated}
        loading={loading}
        error={error}
      />
    </Layout>
  )
}
