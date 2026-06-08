import { useState, useEffect } from 'react'
import Layout from '../../components/Layout'
import { PageHeader } from '../../components/PredictionTable'

// ── Data hook ──────────────────────────────────────────────────────────────────
function useTeamMetrics() {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  useEffect(() => {
    fetch('/data/research-team-metrics.json')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(data => setState({ data, loading: false, error: null }))
      .catch(err  => setState({ data: null, loading: false, error: err.message }))
  }, [])
  return state
}

// ── Shared table styles ────────────────────────────────────────────────────────
const thBase = {
  fontSize:      11,
  fontWeight:    600,
  letterSpacing: 1,
  textTransform: 'uppercase',
  color:         'var(--silver)',
  padding:       '10px 12px',
  borderBottom:  '2px solid var(--navy-border)',
  whiteSpace:    'nowrap',
}

const tdBase = {
  padding:       '8px 12px',
  borderBottom:  '1px solid var(--navy-border)',
  fontSize:      13,
  verticalAlign: 'middle',
}

// ── Diff badge ─────────────────────────────────────────────────────────────────
function DiffBadge({ value }) {
  if (value === null || value === undefined) return <span style={{ color: 'var(--muted)', fontSize: 11 }}>—</span>
  if (value === 0) return <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: 'var(--silver)' }}>0</span>
  const pos   = value > 0
  const color = pos ? 'var(--green)' : 'var(--red)'
  return (
    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color, fontWeight: 600 }}>
      {pos ? '+' : ''}{value}
    </span>
  )
}

// ── Win-percentage mini bar ────────────────────────────────────────────────────
function WpBar({ value, color = 'var(--accent)' }) {
  if (value === null || value === undefined) return <span style={{ color: 'var(--muted)', fontSize: 11 }}>—</span>
  const pct = (value * 100).toFixed(1)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, width: 38, flexShrink: 0 }}>
        {pct}%
      </span>
      <div style={{
        width: 44, height: 4, background: 'var(--navy-border)',
        borderRadius: 2, overflow: 'hidden', flexShrink: 0,
      }}>
        <div style={{
          width:        `${Math.min(pct, 100)}%`,
          height:       '100%',
          background:   color,
          borderRadius: 2,
          transition:   'width 0.3s ease',
        }} />
      </div>
    </div>
  )
}

// ── Column group header ────────────────────────────────────────────────────────
function GroupHeader({ label, color, colSpan }) {
  return (
    <th
      colSpan={colSpan}
      style={{
        textAlign:     'center',
        fontSize:      10,
        fontWeight:    700,
        letterSpacing: 2,
        textTransform: 'uppercase',
        color,
        padding:       '8px 12px 6px',
        borderBottom:  `2px solid ${color}`,
        borderRight:   '1px solid var(--navy-border)',
        background:    'rgba(255,255,255,0.02)',
      }}
    >
      {label}
    </th>
  )
}

// ── Last group header (no right border) ───────────────────────────────────────
function LastGroupHeader({ label, color, colSpan }) {
  return (
    <th
      colSpan={colSpan}
      style={{
        textAlign:     'center',
        fontSize:      10,
        fontWeight:    700,
        letterSpacing: 2,
        textTransform: 'uppercase',
        color,
        padding:       '8px 12px 6px',
        borderBottom:  `2px solid ${color}`,
        background:    'rgba(255,255,255,0.02)',
      }}
    >
      {label}
    </th>
  )
}

// ── Mono number cell ───────────────────────────────────────────────────────────
function Num({ children, bold = false, color = 'var(--silver)' }) {
  if (children === null || children === undefined) return <span style={{ color: 'var(--muted)', fontSize: 11 }}>—</span>
  return (
    <span style={{
      fontFamily: "'DM Mono', monospace",
      fontSize:   12,
      color,
      fontWeight: bold ? 600 : 400,
    }}>
      {children}
    </span>
  )
}

// ── Main teams table ──────────────────────────────────────────────────────────
function TeamsTable({ teams }) {
  const [sortKey, setSortKey] = useState('formula_wp')
  const [sortDir, setSortDir] = useState('desc')

  const toggleSort = (key) => {
    if (sortKey === key) {
      setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const sorted = [...teams].sort((a, b) => {
    const va = a[sortKey] ?? -Infinity
    const vb = b[sortKey] ?? -Infinity
    if (typeof va === 'string') return sortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va)
    return sortDir === 'asc' ? va - vb : vb - va
  })

  const SortTh = ({ label, field, align = 'right' }) => {
    const active = sortKey === field
    const arrow  = active ? (sortDir === 'desc' ? ' ↓' : ' ↑') : ''
    return (
      <th
        onClick={() => toggleSort(field)}
        style={{
          ...thBase,
          textAlign:  align,
          cursor:     'pointer',
          color:      active ? 'var(--accent)' : 'var(--silver)',
          userSelect: 'none',
        }}
      >
        {label}{arrow}
      </th>
    )
  }

  const sepTd = { borderRight: '1px solid var(--navy-border)' }

  return (
    <div style={{
      background:   'var(--navy-mid)',
      border:       '1px solid var(--navy-border)',
      borderRadius: 8,
      overflow:     'hidden',
      marginBottom: 28,
    }}>
      <div style={{
        padding:        '14px 18px',
        borderBottom:   '1px solid var(--navy-border)',
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'space-between',
      }}>
        <span style={{
          fontFamily:    "'Barlow Condensed', sans-serif",
          fontWeight:    700,
          fontSize:      13,
          letterSpacing: 2,
          textTransform: 'uppercase',
          color:         'var(--accent)',
        }}>
          2026 Season Team Metrics
        </span>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>
          Click column headers to sort
        </span>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 1060 }}>
          <thead>
            {/* Group header row */}
            <tr>
              <th colSpan={2} style={{ ...thBase, borderBottom: '2px solid transparent', borderRight: '1px solid var(--navy-border)' }} />
              <GroupHeader     label="Actual Record"      color="var(--silver)"  colSpan={4} />
              <GroupHeader     label="Formula Model"      color="#7ecfff"        colSpan={4} />
              <GroupHeader     label="Pythagorean Model"  color="#b08fff"        colSpan={4} />
              <LastGroupHeader label="Elo Model"          color="#ffd27a"        colSpan={4} />
            </tr>
            {/* Column header row */}
            <tr>
              <th style={{ ...thBase, textAlign: 'center', width: 36 }}>#</th>
              <SortTh label="Team"  field="team"          align="left" />

              {/* Actual */}
              <SortTh label="GP"    field="games" />
              <SortTh label="W"     field="actual_wins" />
              <SortTh label="L"     field="actual_losses" />
              <th style={{ ...thBase, textAlign: 'right', ...sepTd }}>Win%</th>

              {/* Formula */}
              <SortTh label="W"     field="formula_wins" />
              <SortTh label="L"     field="formula_losses" />
              <SortTh label="Δ"     field="formula_diff" />
              <th style={{ ...thBase, textAlign: 'right', ...sepTd }}>Win%</th>

              {/* Pythagorean */}
              <SortTh label="W"     field="pythag_wins" />
              <SortTh label="L"     field="pythag_losses" />
              <SortTh label="Δ"     field="pythag_diff" />
              <th style={{ ...thBase, textAlign: 'right', ...sepTd }}>Win%</th>

              {/* Elo */}
              <SortTh label="W"     field="elo_wins" />
              <SortTh label="L"     field="elo_losses" />
              <SortTh label="Δ"     field="elo_diff" />
              <th style={{ ...thBase, textAlign: 'right' }}>Win%</th>
            </tr>
          </thead>

          <tbody>
            {sorted.map((row, i) => {
              const stripe = i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.018)'
              return (
                <tr key={row.team} style={{ background: stripe }}>
                  {/* Rank */}
                  <td style={{ ...tdBase, textAlign: 'center', color: 'var(--muted)', fontFamily: "'DM Mono', monospace", fontSize: 11 }}>
                    {i + 1}
                  </td>

                  {/* Team */}
                  <td style={{ ...tdBase, whiteSpace: 'nowrap' }}>
                    <span style={{ color: 'var(--white)', fontSize: 13 }}>{row.team}</span>
                  </td>

                  {/* Actual */}
                  <td style={{ ...tdBase, textAlign: 'right' }}><Num color="var(--white)">{row.games}</Num></td>
                  <td style={{ ...tdBase, textAlign: 'right' }}><Num bold color="var(--green)">{row.actual_wins}</Num></td>
                  <td style={{ ...tdBase, textAlign: 'right' }}><Num color="var(--red)">{row.actual_losses}</Num></td>
                  <td style={{ ...tdBase, textAlign: 'right', ...sepTd }}><WpBar value={row.actual_wp} color="var(--silver)" /></td>

                  {/* Formula */}
                  <td style={{ ...tdBase, textAlign: 'right' }}><Num bold color="#7ecfff">{row.formula_wins}</Num></td>
                  <td style={{ ...tdBase, textAlign: 'right' }}><Num color="#5aabdd">{row.formula_losses}</Num></td>
                  <td style={{ ...tdBase, textAlign: 'right' }}><DiffBadge value={row.formula_diff} /></td>
                  <td style={{ ...tdBase, textAlign: 'right', ...sepTd }}><WpBar value={row.formula_wp} color="#7ecfff" /></td>

                  {/* Pythagorean */}
                  <td style={{ ...tdBase, textAlign: 'right' }}><Num bold color="#b08fff">{row.pythag_wins}</Num></td>
                  <td style={{ ...tdBase, textAlign: 'right' }}><Num color="#8b6fd4">{row.pythag_losses}</Num></td>
                  <td style={{ ...tdBase, textAlign: 'right' }}><DiffBadge value={row.pythag_diff} /></td>
                  <td style={{ ...tdBase, textAlign: 'right', ...sepTd }}><WpBar value={row.pythag_wp} color="#b08fff" /></td>

                  {/* Elo */}
                  <td style={{ ...tdBase, textAlign: 'right' }}><Num bold color="#ffd27a">{row.elo_wins}</Num></td>
                  <td style={{ ...tdBase, textAlign: 'right' }}><Num color="#c9a24f">{row.elo_losses}</Num></td>
                  <td style={{ ...tdBase, textAlign: 'right' }}><DiffBadge value={row.elo_diff} /></td>
                  <td style={{ ...tdBase, textAlign: 'right' }}><WpBar value={row.elo_wp} color="#ffd27a" /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Accuracy card shared styles ────────────────────────────────────────────────
const cardStyle = {
  background:   'var(--navy-mid)',
  border:       '1px solid var(--navy-border)',
  borderRadius: 8,
  overflow:     'hidden',
  flex:         '1 1 320px',
}

const cardHeaderStyle = {
  padding:       '13px 18px',
  borderBottom:  '1px solid var(--navy-border)',
  fontFamily:    "'Barlow Condensed', sans-serif",
  fontWeight:    700,
  fontSize:      13,
  letterSpacing: 2,
  textTransform: 'uppercase',
  color:         'var(--accent)',
}

// ── Legend row shared by both cards ───────────────────────────────────────────
function CardLegend() {
  return (
    <div style={{
      display:      'grid',
      gridTemplateColumns: '110px 1fr 1fr 1fr',
      padding:      '8px 18px',
      borderBottom: '1px solid var(--navy-border)',
      gap:          8,
    }}>
      <span />
      <span style={{ fontSize: 11, color: '#7ecfff', fontFamily: "'DM Mono', monospace" }}>Formula</span>
      <span style={{ fontSize: 11, color: '#b08fff', fontFamily: "'DM Mono', monospace" }}>Pythagorean</span>
      <span style={{ fontSize: 11, color: '#ffd27a', fontFamily: "'DM Mono', monospace" }}>Elo</span>
    </div>
  )
}

// ── Single metric row ──────────────────────────────────────────────────────────
function MetricRow({ label, formulaVal, pythagoreanVal, eloVal, format = v => v.toFixed(4), higherBetter = true }) {
  const vals     = [formulaVal, pythagoreanVal, eloVal]
  const bestVal  = higherBetter ? Math.max(...vals) : Math.min(...vals)
  const isBest   = v => v === bestVal

  const dot = (color) => (
    <span style={{
      display: 'inline-block', width: 8, height: 8,
      borderRadius: '50%', background: color, flexShrink: 0,
    }} />
  )

  const cell = (val, color) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
      {dot(color)}
      <span style={{
        fontFamily: "'DM Mono', monospace",
        fontSize:   14,
        fontWeight: isBest(val) ? 700 : 400,
        color:      isBest(val) ? 'var(--white)' : 'var(--silver)',
      }}>
        {format(val)}
      </span>
      {isBest(val) && (
        <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: 1, color, textTransform: 'uppercase', marginLeft: 2 }}>
          ▲
        </span>
      )}
    </div>
  )

  return (
    <div style={{
      display:      'grid',
      gridTemplateColumns: '110px 1fr 1fr 1fr',
      alignItems:   'center',
      padding:      '11px 18px',
      borderBottom: '1px solid var(--navy-border)',
      gap:          8,
    }}>
      <span style={{
        fontSize: 11, fontWeight: 600, letterSpacing: 1,
        textTransform: 'uppercase', color: 'var(--muted)',
      }}>
        {label}
      </span>
      {cell(formulaVal,     '#7ecfff')}
      {cell(pythagoreanVal, '#b08fff')}
      {cell(eloVal,         '#ffd27a')}
    </div>
  )
}

// ── Correlation card ───────────────────────────────────────────────────────────
function CorrelationCard({ accuracy }) {
  return (
    <div style={cardStyle}>
      <div style={cardHeaderStyle}>Correlation with Actual Win%</div>
      <CardLegend />
      <MetricRow
        label="Pearson r"
        formulaVal={accuracy.correlation.formula}
        pythagoreanVal={accuracy.correlation.pythag}
        eloVal={accuracy.correlation.elo}
        format={v => v.toFixed(4)}
        higherBetter={true}
      />
      <div style={{ padding: '10px 18px' }}>
        <p style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.6, margin: 0 }}>
          Pearson r measures linear agreement with actual win percentage. A value of 1.0 is perfect. Higher is better.
        </p>
      </div>
    </div>
  )
}

// ── Error metrics card ─────────────────────────────────────────────────────────
function ErrorCard({ accuracy }) {
  return (
    <div style={cardStyle}>
      <div style={cardHeaderStyle}>Prediction Error vs Actual Win%</div>
      <CardLegend />
      <MetricRow
        label="MAE"
        formulaVal={accuracy.mae.formula}
        pythagoreanVal={accuracy.mae.pythag}
        eloVal={accuracy.mae.elo}
        format={v => v.toFixed(4)}
        higherBetter={false}
      />
      <MetricRow
        label="RMSE"
        formulaVal={accuracy.rmse.formula}
        pythagoreanVal={accuracy.rmse.pythag}
        eloVal={accuracy.rmse.elo}
        format={v => v.toFixed(4)}
        higherBetter={false}
      />
      <div style={{ padding: '10px 18px' }}>
        <p style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.6, margin: 0 }}>
          MAE and RMSE measure average deviation from actual win percentage. Lower is better. RMSE penalizes large misses more heavily.
        </p>
      </div>
    </div>
  )
}

// ── Methodology legend ─────────────────────────────────────────────────────────
function MethodologyBar({ exponent }) {
  const pills = [
    { label: 'Formula',       desc: 'Predicted RS/RA from hitting & pitching rate stats → Pythagorean Win%',       color: '#7ecfff' },
    { label: 'Pythagorean',   desc: `Actual RS/RA → Pythagorean Win%  (exponent ${exponent})`,                    color: '#b08fff' },
    { label: 'Elo',           desc: 'Implied win% from Elo rating vs. league-average opponent on neutral field',   color: '#ffd27a' },
    { label: 'Δ Convention',  desc: 'Positive = model projects more wins than actual ("lucky"); Negative = fewer ("unlucky")', color: 'var(--silver)' },
  ]
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 24 }}>
      {pills.map(p => (
        <div key={p.label} style={{
          background:   'var(--navy-mid)',
          border:       '1px solid var(--navy-border)',
          borderLeft:   `3px solid ${p.color}`,
          borderRadius: 6,
          padding:      '8px 14px',
          display:      'flex',
          gap:          10,
          alignItems:   'baseline',
          flexShrink:   0,
        }}>
          <span style={{
            fontFamily: "'Barlow Condensed', sans-serif", fontWeight: 700,
            fontSize: 11, letterSpacing: 1.5, textTransform: 'uppercase',
            color: p.color, whiteSpace: 'nowrap',
          }}>
            {p.label}
          </span>
          <span style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.4 }}>
            {p.desc}
          </span>
        </div>
      ))}
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────
export default function TeamMetrics() {
  const { data, loading, error } = useTeamMetrics()

  const updatedLabel = data?.updated
    ? new Date(data.updated).toLocaleString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
      })
    : null

  return (
    <Layout title="Team Metrics">
      <PageHeader
        tag="Research → Team Metrics"
        title="TEAM METRICS"
        subtitle="Side-by-side comparison of three win-expectancy models — a proprietary formula, Pythagorean expectation, and Elo ratings — benchmarked against each team's real record."
      />

      {updatedLabel && (
        <div style={{ color: 'var(--silver)', fontSize: 12, marginBottom: 24 }}>
          Last updated: {updatedLabel}
        </div>
      )}

      {loading && (
        <div style={{
          background: 'var(--navy-mid)', border: '1px solid var(--navy-border)',
          borderRadius: 8, padding: '40px 24px', textAlign: 'center', color: 'var(--silver)',
        }}>
          Loading team metrics…
        </div>
      )}

      {error && (
        <div style={{
          background: '#1a0000', border: '1px solid #ff4444', borderRadius: 8,
          padding: '20px 24px', color: '#ff8888', marginBottom: 24,
        }}>
          Failed to load data: {error}
        </div>
      )}

      {data && (
        <>
          <MethodologyBar exponent={data.exponent} />
          <TeamsTable teams={data.teams} />
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
            <CorrelationCard accuracy={data.accuracy} />
            <ErrorCard       accuracy={data.accuracy} />
          </div>
        </>
      )}
    </Layout>
  )
}
