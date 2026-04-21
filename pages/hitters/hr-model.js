import Layout from '../../components/Layout'
import PredictionTable, { ProbCell, PageHeader } from '../../components/PredictionTable'
import { usePredictions } from '../../components/usePredictions'

/*
 * ─── EXPECTED JSON SHAPE (public/data/hitters-hr-model.json) ─────────────────
 * {
 *   "updated": "2025-04-20T10:00:00Z",
 *   "predictions": [
 *     {
 *       "batter":       "Aaron Judge",
 *       "team":         "New York Yankees",
 *       "pitcher":      "Gerrit Cole",
 *       "opp_team":     "Houston Astros",
 *       "barrel_pct":   18.4,
 *       "pull_pct":     44.1,
 *       "fb_pct":       52.3,
 *       "pitcher_hr9":  1.21,
 *       "park_factor":  1.05,
 *       "hr_prob":      0.087,
 *       "game_time":    "7:05 PM ET"
 *     }, ...
 *   ]
 * }
 */

const COLUMNS = [
  { key: 'game_time',   label: 'Time' },
  { key: 'batter',      label: 'Batter' },
  { key: 'team',        label: 'Team' },
  { key: 'pitcher',     label: 'Pitcher' },
  { key: 'barrel_pct',  label: 'Barrel%',     render: v => v != null ? `${v.toFixed(1)}%` : '—' },
  { key: 'pull_pct',    label: 'Pull%',        render: v => v != null ? `${v.toFixed(1)}%` : '—' },
  { key: 'fb_pct',      label: 'FB%',          render: v => v != null ? `${v.toFixed(1)}%` : '—' },
  { key: 'pitcher_hr9', label: 'P HR/9',       render: v => v != null ? v.toFixed(2) : '—' },
  { key: 'park_factor', label: 'Park Factor',  render: v => v != null ? v.toFixed(2) : '—' },
  { key: 'hr_prob',     label: 'HR Prob',      render: v => <ProbCell value={v} /> },
]

export default function HRModel() {
  const { data, updated, loading, error } = usePredictions('hitters-hr-model')
  return (
    <Layout title="HR Model">
      <PageHeader
        tag="Hitters → HR Model"
        title="HOME RUN MODEL"
        subtitle="Predicts HR probability using barrel rate, pull%, fly ball rate, pitcher HR/9, and ballpark factors from the MLB API."
      />
      <PredictionTable data={data} columns={COLUMNS} updated={updated} loading={loading} error={error} />
    </Layout>
  )
}
