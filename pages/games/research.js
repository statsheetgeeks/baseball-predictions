import Layout from '../../components/Layout'
import PredictionTable, { ProbCell, FavoriteCell, PageHeader } from '../../components/PredictionTable'
import { usePredictions } from '../../components/usePredictions'

/*
 * ─── EXPECTED JSON SHAPE (public/data/games-research.json) ───────────────────
 * {
 *   "updated": "2025-04-20T10:00:00Z",
 *   "predictions": [
 *     {
 *       "home_team":      "Los Angeles Dodgers",
 *       "away_team":      "San Francisco Giants",
 *       "home_prob":      0.589,
 *       "away_prob":      0.411,
 *       "home_starter":   "Yoshinobu Yamamoto",
 *       "away_starter":   "Logan Webb",
 *       "home_era":       3.21,
 *       "away_era":       2.98,
 *       "run_diff_home":  +24,
 *       "game_time":      "7:10 PM ET"
 *     },
 *     ...
 *   ]
 * }
 */

const COLUMNS = [
  { key: 'game_time',     label: 'Time' },
  { key: 'home_team',     label: 'Home' },
  { key: 'away_team',     label: 'Away' },
  { key: 'home_starter',  label: 'Home SP' },
  { key: 'away_starter',  label: 'Away SP' },
  { key: 'home_era',      label: 'Home ERA', render: v => v != null ? v.toFixed(2) : '—' },
  { key: 'away_era',      label: 'Away ERA', render: v => v != null ? v.toFixed(2) : '—' },
  { key: 'run_diff_home', label: 'Run Diff', render: v => v != null ? (v > 0 ? `+${v}` : v) : '—' },
  { key: 'home_prob',     label: 'Home Prob', render: v => <ProbCell value={v} /> },
  { key: 'home_prob',     label: 'Pick',      render: (v, row) => <FavoriteCell value={v} /> },
]

export default function ResearchGame() {
  const { data, updated, loading, error } = usePredictions('games-research')

  return (
    <Layout title="Research-Based Model">
      <PageHeader
        tag="Games → Research"
        title="RESEARCH-BASED MODEL"
        subtitle="Incorporates Pythagorean expectation, run differential, starting pitcher ERA, and home field advantage."
      />
      <PredictionTable
        data={data} columns={COLUMNS} updated={updated} loading={loading} error={error}
      />
    </Layout>
  )
}
