import Layout from '../../components/Layout'
import PredictionTable, { ProbCell, PageHeader } from '../../components/PredictionTable'
import { usePredictions } from '../../components/usePredictions'

/*
 * ─── EXPECTED JSON SHAPE (public/data/hitters-log5-hit.json) ─────────────────
 * {
 *   "updated": "2025-04-20T10:00:00Z",
 *   "predictions": [
 *     {
 *       "batter":        "Freddie Freeman",
 *       "team":          "Los Angeles Dodgers",
 *       "pitcher":       "Logan Webb",
 *       "opp_team":      "San Francisco Giants",
 *       "batter_avg":    0.312,
 *       "pitcher_avg_against": 0.218,
 *       "hit_prob":      0.278,
 *       "game_time":     "7:10 PM ET"
 *     }, ...
 *   ]
 * }
 */

const COLUMNS = [
  { key: 'game_time',           label: 'Time' },
  { key: 'batter',              label: 'Batter' },
  { key: 'team',                label: 'Team' },
  { key: 'pitcher',             label: 'Pitcher' },
  { key: 'batter_avg',          label: 'BA',     render: v => v != null ? v.toFixed(3) : '—' },
  { key: 'pitcher_avg_against', label: 'OBA',    render: v => v != null ? v.toFixed(3) : '—' },
  { key: 'hit_prob',            label: 'Hit Prob', render: v => <ProbCell value={v} /> },
]

export default function Log5Hit() {
  const { data, updated, loading, error } = usePredictions('hitters-log5-hit')
  return (
    <Layout title="Log5 Hit Model">
      <PageHeader tag="Hitters → Log5 Hit" title="LOG5 HIT MODEL"
        subtitle="Calculates hit probability from batter batting average vs. pitcher batting average against, using the Log5 method." />
      <PredictionTable data={data} columns={COLUMNS} updated={updated} loading={loading} error={error} />
    </Layout>
  )
}
