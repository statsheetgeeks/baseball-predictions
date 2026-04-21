import Layout from '../../components/Layout'
import PredictionTable, { ProbCell, PageHeader } from '../../components/PredictionTable'
import { usePredictions } from '../../components/usePredictions'

/*
 * ─── EXPECTED JSON SHAPE (public/data/games-composite.json) ──────────────────
 * {
 *   "updated": "2025-04-20T10:00:00Z",
 *   "predictions": [
 *     {
 *       "home_team":        "Los Angeles Dodgers",
 *       "away_team":        "San Francisco Giants",
 *       "game_time":        "7:10 PM ET",
 *       "log5_home":        0.621,
 *       "research_home":    0.589,
 *       "xgboost_home":     0.634,
 *       "rf_home":          0.601,
 *       "composite_home":   0.611,   ← weighted average
 *       "composite_away":   0.389
 *     }, ...
 *   ]
 * }
 */

const COLUMNS = [
  { key: 'game_time',      label: 'Time' },
  { key: 'home_team',      label: 'Home' },
  { key: 'away_team',      label: 'Away' },
  { key: 'log5_home',      label: 'Log5',    render: v => v != null ? `${(v*100).toFixed(1)}%` : '—' },
  { key: 'research_home',  label: 'Research', render: v => v != null ? `${(v*100).toFixed(1)}%` : '—' },
  { key: 'xgboost_home',   label: 'XGBoost',  render: v => v != null ? `${(v*100).toFixed(1)}%` : '—' },
  { key: 'rf_home',        label: 'Rand. Forest', render: v => v != null ? `${(v*100).toFixed(1)}%` : '—' },
  { key: 'composite_home', label: 'COMPOSITE', render: v => <ProbCell value={v} /> },
  {
    key: 'composite_home',
    label: 'Pick',
    render: (v, row) => {
      if (v == null) return '—'
      const fav = v > 0.5 ? row.home_team : row.away_team
      const prob = v > 0.5 ? v : 1 - v
      return (
        <span style={{ fontFamily: 'var(--font-m)', fontSize: 12 }}>
          <span style={{ color: 'var(--green)' }}>{fav}</span>
          {' '}
          <span style={{ color: 'var(--muted)' }}>{(prob * 100).toFixed(1)}%</span>
        </span>
      )
    }
  },
]

export default function CompositeGame() {
  const { data, updated, loading, error } = usePredictions('games-composite')

  return (
    <Layout title="Composite Model">
      <PageHeader tag="Games → Composite" title="COMPOSITE MODEL"
        subtitle="All four game models side-by-side with a weighted ensemble composite. Scroll right to see all columns." />
      <PredictionTable data={data} columns={COLUMNS} updated={updated} loading={loading} error={error} />
    </Layout>
  )
}
