import Layout from '../../components/Layout'
import PredictionTable, { ProbCell, PageHeader } from '../../components/PredictionTable'
import { usePredictions } from '../../components/usePredictions'

/*
 * ─── EXPECTED JSON SHAPE (public/data/hitters-ml-hit.json) ───────────────────
 * {
 *   "updated": "2025-04-20T10:00:00Z",
 *   "predictions": [
 *     {
 *       "batter":       "Freddie Freeman",
 *       "team":         "Los Angeles Dodgers",
 *       "pitcher":      "Logan Webb",
 *       "opp_team":     "San Francisco Giants",
 *       "hit_prob":     0.301,
 *       "xba":          0.298,
 *       "exit_velo":    91.2,
 *       "game_time":    "7:10 PM ET"
 *     }, ...
 *   ]
 * }
 */

const COLUMNS = [
  { key: 'game_time', label: 'Time' },
  { key: 'batter',    label: 'Batter' },
  { key: 'team',      label: 'Team' },
  { key: 'pitcher',   label: 'Pitcher' },
  { key: 'exit_velo', label: 'Exit Velo', render: v => v != null ? `${v.toFixed(1)} mph` : '—' },
  { key: 'xba',       label: 'xBA',       render: v => v != null ? v.toFixed(3) : '—' },
  { key: 'hit_prob',  label: 'Hit Prob',  render: v => <ProbCell value={v} /> },
]

export default function MLHit() {
  const { data, updated, loading, error } = usePredictions('hitters-ml-hit')
  return (
    <Layout title="ML Hit Model">
      <PageHeader tag="Hitters → ML Hit" title="ML HIT MODEL"
        subtitle="Machine learning model predicting hit probability from Statcast exit velocity, launch angle, and pitcher contact rate." />
      <PredictionTable data={data} columns={COLUMNS} updated={updated} loading={loading} error={error} />
    </Layout>
  )
}
