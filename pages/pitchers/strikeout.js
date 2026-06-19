import { useState, useEffect } from 'react'
import Layout from '../../components/Layout'

/*
 * ─── EXPECTED JSON SHAPE (public/data/pitchers-strikeout.json) ───────────────
 * Produced by models/pitchers_strikeout.py
 * {
 *   "updated": "2026-06-18T14:00:00Z",
 *   "date": "2026-06-18",
 *   "predictions": [
 *     {
 *       "pitcher_id": 543037, "pitcher_name": "Gerrit Cole",
 *       "team": "NYY", "opponent": "BOS", "game_time": "7:05 PM ET",
 *       "lineup_source": "posted",     ← "posted" | "expected" | "none"
 *       "lineup_posted": true,
 *       "calculated_projected_ks": 6.42,   ← Calculation Engine
 *       "knn_projected_ks": 6.10,          ← KNN
 *       "gbm_projected_ks": 6.80,          ← XGBoost ("Gradient Boosting")
 *       "expected_tbf": 24.5
 *     }, ...
 *   ]
 * }
 *
 * Three models always run, even when the lineup isn't posted yet — in that
 * case lineup_source is "expected" and the projections are based on each
 * team's most recent completed games rather than today's confirmed lineup.
 */

// ── Colour / label helpers ──────────────────────────────────────────────────
const ksColor = (v) =>
  v >= 7 ? 'var(--yellow)' : v >= 5 ? 'var(--accent)' : 'var(--silver-dim)'

const LINEUP_BADGE = {
  posted:   { label: 'CONFIRMED', color: 'var(--yellow)',      bg: 'rgba(212,168,67,0.10)',  border: 'var(--yellow)' },
  expected: { label: 'PROJECTED', color: 'var(--accent)',      bg: 'rgba(74,144,217,0.10)',  border: 'var(--accent)' },
  none:     { label: 'NO DATA',   color: 'var(--silver-dim)', bg: 'transparent',            border: 'var(--navy-border)' },
}

const rankColor = (i) =>
  i === 0 ? '#FFD700' : i === 1 ? '#C0C0C0' : i === 2 ? '#CD7F32' : 'var(--silver-dim)'

// ── Small reusable components ────────────────────────────────────────────────
function LineupBadge({ source }) {
  const s = LINEUP_BADGE[source] || LINEUP_BADGE.none
  return (
    <span style={{
      border: `1px solid ${s.border}`, color: s.color, background: s.bg,
      fontSize: 10, fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase',
      padding: '2px 7px', display: 'inline-block', fontFamily: "'DM Mono', monospace",
      borderRadius: 2,
    }}>
      {s.label}
    </span>
  )
}

function KsCell({ value, isPrimary }) {
  if (value == null) {
    return <span style={{ color: 'var(--silver-dim)', fontFamily: "'DM Mono', monospace", fontSize: 13 }}>—</span>
  }
  return (
    <span style={{
      fontFamily: "'DM Mono', monospace",
      fontSize: isPrimary ? 16 : 13,
      fontWeight: isPrimary ? 700 : 500,
      color: ksColor(value),
    }}>
      {value.toFixed(2)}
    </span>
  )
}

function ModelSpread({ calc, knn, gbm }) {
  // Quick visual: how much the three models agree/disagree
  const vals = [calc, knn, gbm].filter(v => v != null)
  if (vals.length < 2) return null
  const spread = Math.max(...vals) - Math.min(...vals)
  const tight = spread <= 0.75
  return (
    <span style={{
      fontSize: 9, fontFamily: "'DM Mono', monospace", letterSpacing: '1px',
      color: tight ? 'var(--green)' : 'var(--silver-dim)', textTransform: 'uppercase',
    }}>
      {tight ? 'AGREE' : `±${spread.toFixed(1)}`}
    </span>
  )
}

function StatRow({ label, value }) {
  if (value == null) return null
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5, fontSize: 12 }}>
      <span style={{ color: 'var(--silver-dim)' }}>{label}</span>
      <span style={{ color: 'var(--white)', fontFamily: "'DM Mono', monospace" }}>{value}</span>
    </div>
  )
}

function SummaryPanel({ title, n_graded, calc_mae, knn_mae, gbm_mae }) {
  return (
    <div style={{
      background: 'var(--navy)', border: '1px solid var(--navy-border)',
      borderRadius: 6, padding: '14px 18px', flex: '1 1 220px',
    }}>
      <div style={{
        fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)',
        letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 10,
      }}>{title}</div>
      {n_graded != null && <StatRow label="Pitchers Graded" value={n_graded} />}
      <StatRow label="Calc Engine MAE" value={calc_mae != null ? calc_mae.toFixed(2) : null} />
      <StatRow label="KNN MAE"         value={knn_mae  != null ? knn_mae.toFixed(2)  : null} />
      <StatRow label="Gradient Boosting MAE" value={gbm_mae != null ? gbm_mae.toFixed(2) : null} />
      {n_graded == null && calc_mae == null && (
        <div style={{ fontSize: 11, color: 'var(--silver-dim)', fontStyle: 'italic' }}>No graded games yet</div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function StrikeoutModel() {
  const [fullData, setFullData] = useState(null)
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState(null)
  const [expanded, setExpanded] = useState(null)
  const [sortCol,  setSortCol]  = useState('calculated_projected_ks')
  const [sortAsc,  setSortAsc]  = useState(false)
  const [lineupFilter, setLineupFilter] = useState('all')   // all | posted | expected

  useEffect(() => {
    fetch('/data/pitchers-strikeout.json')
      .then(r => {
        if (!r.ok) throw new Error(`Could not load pitchers-strikeout.json (${r.status})`)
        return r.json()
      })
      .then(json => { setFullData(json); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  const preds   = fullData?.predictions ?? []
  const updated = fullData?.updated ?? null
  const history = fullData?.history_summary ?? {}   // optional, if you wire up grading display

  const filtered = [...preds]
    .filter(p => lineupFilter === 'all' || p.lineup_source === lineupFilter)
    .sort((a, b) => {
      let av = a[sortCol], bv = b[sortCol]
      av = av == null ? -Infinity : av
      bv = bv == null ? -Infinity : bv
      if (typeof av === 'string') { av = av.toLowerCase(); bv = (bv ?? '').toLowerCase() }
      if (av === bv) return 0
      return sortAsc ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1)
    })

  const handleSort = col => {
    if (sortCol === col) setSortAsc(a => !a)
    else { setSortCol(col); setSortAsc(false) }
  }

  const updatedStr = updated
    ? new Date(updated).toLocaleString('en-US', {
        month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
        timeZone: 'America/Chicago',
      }) + ' CT'
    : null

  const nPosted   = preds.filter(p => p.lineup_source === 'posted').length
  const nExpected = preds.filter(p => p.lineup_source === 'expected').length

  const Th = ({ col, label, align }) => (
    <th onClick={() => handleSort(col)} style={{
      padding: '9px 14px', textAlign: align || 'left',
      fontFamily: "'DM Mono', monospace", fontSize: 9,
      letterSpacing: '2px', textTransform: 'uppercase',
      color: sortCol === col ? 'var(--yellow)' : 'var(--silver-dim)',
      cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap',
      background: 'var(--navy)', borderBottom: '1px solid var(--navy-border)',
    }}>
      {label}{sortCol === col ? (sortAsc ? ' ↑' : ' ↓') : ''}
    </th>
  )

  const FilterBtn = ({ value, label, count }) => (
    <button
      onClick={() => setLineupFilter(value)}
      style={{
        padding: '6px 14px', fontSize: 11, fontFamily: "'DM Mono', monospace",
        letterSpacing: '1px', textTransform: 'uppercase', cursor: 'pointer',
        border: `1px solid ${lineupFilter === value ? 'var(--yellow)' : 'var(--navy-border)'}`,
        color: lineupFilter === value ? 'var(--yellow)' : 'var(--silver-dim)',
        background: lineupFilter === value ? 'rgba(212,168,67,0.08)' : 'transparent',
        borderRadius: 4,
      }}
    >
      {label} {count != null && <span style={{ opacity: 0.7 }}>({count})</span>}
    </button>
  )

  return (
    <Layout title="Strikeout Model">

      {/* ── Page header ──────────────────────────────────────────────────── */}
      <div style={{ marginBottom: '2rem', borderLeft: '3px solid var(--yellow)', paddingLeft: '1.25rem' }}>
        <div style={{
          fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--yellow)',
          letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 8,
        }}>Pitchers → Strikeout Model</div>
        <h1 style={{
          fontFamily: "'Barlow Condensed', sans-serif", fontWeight: 900,
          fontSize: '2.4rem', color: 'var(--white)', lineHeight: 1.1, marginBottom: 8,
        }}>STRIKEOUT PREDICTIONS</h1>
        <p style={{ fontSize: 13.5, color: 'var(--silver)', maxWidth: 640, lineHeight: 1.65 }}>
          Three approaches projected side by side for every probable starter:{' '}
          <span style={{ color: 'var(--white)' }}>Calculation Engine</span> (deterministic batter-vs-pitch-type matchup math),{' '}
          <span style={{ color: 'var(--white)' }}>KNN</span>, and{' '}
          <span style={{ color: 'var(--white)' }}>Gradient Boosting</span> (XGBoost) —
          built on full Statcast pitch-level data (whiff%, CSW%, pitch-type splits).
          When today's lineup isn't posted yet, projections fall back to each team's{' '}
          <span style={{ color: 'var(--accent)' }}>expected lineup</span>, built from
          its last several completed games, so every pitcher gets a full projection all day long.
          Updated daily.
        </p>
        {updatedStr && (
          <div style={{ marginTop: 10, fontSize: 11, color: 'var(--silver-dim)', fontFamily: "'DM Mono', monospace" }}>
            Last updated {updatedStr}
          </div>
        )}
      </div>

      {loading && <div style={{ color: 'var(--silver-dim)', padding: '2rem 0' }}>Loading predictions…</div>}
      {error && (
        <div style={{
          color: 'var(--red, #e05252)', background: 'rgba(224,82,82,0.08)',
          border: '1px solid rgba(224,82,82,0.3)', borderRadius: 6,
          padding: '12px 16px', fontSize: 13, marginBottom: 20,
        }}>
          {error}
        </div>
      )}

      {!loading && !error && (
        <>
          {/* ── Filter bar ──────────────────────────────────────────────── */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
            <FilterBtn value="all"      label="All Starters"    count={preds.length} />
            <FilterBtn value="posted"   label="Confirmed"       count={nPosted} />
            <FilterBtn value="expected" label="Projected"       count={nExpected} />
          </div>

          {filtered.length === 0 ? (
            <div style={{ color: 'var(--silver-dim)', padding: '2rem 0' }}>
              No probable starters found for today's slate yet.
            </div>
          ) : (
            <div style={{ overflowX: 'auto', border: '1px solid var(--navy-border)', borderRadius: 6 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th style={{
                      padding: '9px 14px', fontFamily: "'DM Mono', monospace", fontSize: 9,
                      letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--silver-dim)',
                      background: 'var(--navy)', borderBottom: '1px solid var(--navy-border)',
                    }}>#</th>
                    <Th col="pitcher_name" label="Pitcher" />
                    <Th col="team" label="Matchup" />
                    <Th col="lineup_source" label="Lineup" />
                    <Th col="calculated_projected_ks" label="Calc Engine" align="right" />
                    <Th col="knn_projected_ks" label="KNN" align="right" />
                    <Th col="gbm_projected_ks" label="Grad. Boosting" align="right" />
                    <th style={{
                      padding: '9px 14px', fontFamily: "'DM Mono', monospace", fontSize: 9,
                      letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--silver-dim)',
                      background: 'var(--navy)', borderBottom: '1px solid var(--navy-border)',
                    }}>Agreement</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((p, i) => {
                    const isExp = expanded === p.pitcher_id
                    return [
                      <tr
                        key={p.pitcher_id}
                        onClick={() => setExpanded(isExp ? null : p.pitcher_id)}
                        style={{ cursor: 'pointer', background: isExp ? 'var(--navy-hover)' : 'transparent' }}
                      >
                        <td style={{
                          padding: '11px 14px', borderBottom: '1px solid var(--navy-border)',
                          textAlign: 'center', fontFamily: "'Barlow Condensed', sans-serif",
                          fontSize: 16, fontWeight: 700, color: rankColor(i),
                        }}>
                          {i + 1}
                        </td>
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <div style={{ fontWeight: 600, color: 'var(--white)', fontSize: 14 }}>{p.pitcher_name}</div>
                          <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', letterSpacing: '2px', textTransform: 'uppercase', marginTop: 2 }}>
                            {p.team}
                          </div>
                        </td>
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)', minWidth: 130 }}>
                          <div style={{ fontSize: 12, color: 'var(--silver)' }}>vs {p.opponent}</div>
                          <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', marginTop: 2 }}>
                            {p.game_time}
                          </div>
                        </td>
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <LineupBadge source={p.lineup_source} />
                        </td>
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)', textAlign: 'right' }}>
                          <KsCell value={p.calculated_projected_ks} isPrimary />
                        </td>
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)', textAlign: 'right' }}>
                          <KsCell value={p.knn_projected_ks} />
                        </td>
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)', textAlign: 'right' }}>
                          <KsCell value={p.gbm_projected_ks} />
                        </td>
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <ModelSpread calc={p.calculated_projected_ks} knn={p.knn_projected_ks} gbm={p.gbm_projected_ks} />
                        </td>
                      </tr>,

                      isExp && (
                        <tr key={`e${p.pitcher_id}`}>
                          <td colSpan={8} style={{ background: 'var(--navy)', borderBottom: '1px solid var(--navy-border)', padding: '16px 20px' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 24 }}>
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--yellow)', marginBottom: 8 }}>Game Context</div>
                                <StatRow label="Opponent" value={p.opponent} />
                                <StatRow label="Game Time" value={p.game_time} />
                                <StatRow label="Expected TBF" value={p.expected_tbf} />
                                <StatRow label="Lineup Source" value={p.lineup_source === 'posted' ? 'Confirmed (posted)' : p.lineup_source === 'expected' ? 'Projected (recent games)' : 'Unavailable'} />
                              </div>
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--yellow)', marginBottom: 8 }}>Model Projections</div>
                                <StatRow label="Calculation Engine" value={p.calculated_projected_ks?.toFixed(2) ?? '—'} />
                                <StatRow label="KNN" value={p.knn_projected_ks?.toFixed(2) ?? '—'} />
                                <StatRow label="Gradient Boosting" value={p.gbm_projected_ks?.toFixed(2) ?? '—'} />
                                {p.actual_ks != null && (
                                  <div style={{ marginTop: 8, paddingTop: 6, borderTop: '1px solid var(--navy-border)' }}>
                                    <StatRow label="Actual K's" value={p.actual_ks} />
                                  </div>
                                )}
                              </div>
                            </div>
                          </td>
                        </tr>
                      ),
                    ]
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* ── Tracking panel (populated once history grading has data) ── */}
          {history?.calc_mae != null && (
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 24 }}>
              <SummaryPanel
                title="Yesterday's Accuracy"
                n_graded={history.n_graded}
                calc_mae={history.calc_mae}
                knn_mae={history.knn_mae}
                gbm_mae={history.gbm_mae}
              />
            </div>
          )}
        </>
      )}
    </Layout>
  )
}
