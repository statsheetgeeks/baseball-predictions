import Layout from '../../components/Layout'
import PredictionTable, { PageHeader } from '../../components/PredictionTable'
import { usePredictions } from '../../components/usePredictions'

/*
 * ─── EXPECTED JSON SHAPE (public/data/pitchers-strikeout.json) ───────────────
 * {
 *   "updated": "2025-04-20T10:00:00Z",
 *   "predictions": [
 *     {
 *       "pitcher":        "Gerrit Cole",
 *       "team":           "New York Yankees",
 *       "opp_team":       "Houston Astros",
 *       "game_time":      "7:05 PM ET",
 *       "k_per_9":        11.4,
 *       "whiff_pct":      31.2,
 *       "chase_pct":      28.7,
 *       "opp_k_pct":      23.1,
 *       "projected_k":    7.5,
 *       "k_line":         6.5,        ← over/under line if you have it
 *       "over_prob":      0.68        ← probability of going over the line
 *     }, ...
 *   ]
 * }
 */

function KCell({ value }) {
  if (value == null) return <>—</>
  return (
    <span style={{
      fontFamily: 'var(--font-m)', fontSize: 15, fontWeight: 600,
      color: value >= 7 ? 'var(--green)' : 'var(--text)',
    }}>
      {value.toFixed(1)}
    </span>
  )
}

function OverUnderCell({ prob, line }) {
  if (prob == null) return <>—</>
  const over = prob > 0.5
  return (
    <div style={{ fontFamily: 'var(--font-m)', fontSize: 12 }}>
      <span className={`tag ${over ? 'tag-green' : 'tag-muted'}`}>
        {over ? 'OVER' : 'UNDER'} {line ?? ''}
      </span>
      <span style={{ marginLeft: 6, color: 'var(--muted)' }}>
        {(Math.max(prob, 1 - prob) * 100).toFixed(0)}%
      </span>
    </div>
  )
}

const COLUMNS = [
  { key: 'game_time',   label: 'Time' },
  { key: 'pitcher',     label: 'Pitcher' },
  { key: 'team',        label: 'Team' },
  { key: 'opp_team',    label: 'Opponent' },
  { key: 'k_per_9',     label: 'K/9',       render: v => v != null ? v.toFixed(1) : '—' },
  { key: 'whiff_pct',   label: 'Whiff%',    render: v => v != null ? `${v.toFixed(1)}%` : '—' },
  { key: 'chase_pct',   label: 'Chase%',    render: v => v != null ? `${v.toFixed(1)}%` : '—' },
  { key: 'opp_k_pct',   label: 'Opp K%',    render: v => v != null ? `${v.toFixed(1)}%` : '—' },
  { key: 'projected_k', label: 'Proj. K',   render: v => <KCell value={v} /> },
  { key: 'over_prob',   label: 'O/U',       render: (v, row) => <OverUnderCell prob={v} line={row.k_line} /> },
]

export default function StrikeoutModel() {
  const { data, updated, loading, error } = usePredictions('pitchers-strikeout')
  return (
    <Layout title="Strikeout Model">
      <PageHeader
        tag="Pitchers → Strikeout"
        title="STRIKEOUT MODEL"
        subtitle="Projects strikeout totals for today's starters using K/9, whiff rate, chase rate, and opponent strikeout percentage."
      />
      <PredictionTable data={data} columns={COLUMNS} updated={updated} loading={loading} error={error} />
    </Layout>
  )
}
