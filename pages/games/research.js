import { useState, useEffect } from 'react'
import Layout from '../../components/Layout'
import { PageHeader } from '../../components/PredictionTable'

// ── Data hook ─────────────────────────────────────────────────────────────────
function useResearchData() {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  useEffect(() => {
    fetch('/data/games-research.json')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(data => setState({ data, loading: false, error: null }))
      .catch(err  => setState({ data: null, loading: false, error: err.message }))
  }, [])
  return state
}

// ── CSV download ──────────────────────────────────────────────────────────────
function downloadCSV(predictions, dateStr) {
  const headers = [
    'Date','Away Team','Home Team',
    'Away Prob','Home Prob',
    'LogR (Home)','XGB (Home)','MLP (Home)',
    'Pick','Confidence'
  ]
  const rows = predictions.map(p => [
    dateStr,
    p.away_team,
    p.home_team,
    p.away_prob != null ? (p.away_prob * 100).toFixed(1) + '%' : '',
    p.home_prob != null ? (p.home_prob * 100).toFixed(1) + '%' : '',
    p.base_logr_home != null ? (p.base_logr_home * 100).toFixed(1) + '%' : '',
    p.base_xgb_home  != null ? (p.base_xgb_home  * 100).toFixed(1) + '%' : '',
    p.base_mlp_home  != null ? (p.base_mlp_home  * 100).toFixed(1) + '%' : '',
    p.pick,
    p.confidence != null ? (p.confidence * 100).toFixed(1) + '%' : '',
  ])
  const csv  = [headers, ...rows].map(r => r.map(v => `"${v}"`).join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `research_picks_${dateStr.replace(/-/g, '')}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 100)
}

// ── Confidence colored text ───────────────────────────────────────────────────
function ConfText({ confidence }) {
  if (confidence == null) return null
  const pct = confidence * 100
  let color
  if      (pct >= 80) color = '#4ade80'
  else if (pct >= 70) color = '#60a5fa'
  else if (pct >= 60) color = '#fbbf24'
  else                color = '#fb923c'
  return (
    <span style={{ color, fontWeight: 700, fontSize: 13,
                   fontFamily: "'Barlow Condensed', sans-serif" }}>
      {pct.toFixed(1)}%
    </span>
  )
}

// ── Small base-model probability ──────────────────────────────────────────────
function BaseProb({ value }) {
  if (value == null) return <span style={{ color: 'var(--silver)', fontSize: 11 }}>—</span>
  const pct = value * 100
  return (
    <span style={{ color: 'var(--silver)', fontSize: 11, fontFamily: 'monospace' }}>
      {pct.toFixed(1)}%
    </span>
  )
}

// ── Record display ────────────────────────────────────────────────────────────
function Record({ wins, losses, total, size = 'normal' }) {
  if (total === 0) return <span style={{ color: 'var(--silver)', fontSize: 12 }}>—</span>
  const pct = (wins / total * 100).toFixed(1)
  const big = size === 'big'
  return (
    <span style={{ fontFamily: "'Barlow Condensed', sans-serif", fontWeight: 700 }}>
      <span style={{ color: 'var(--white)', fontSize: big ? 20 : 14 }}>{wins}–{losses}</span>
      <span style={{ color: 'var(--silver)', fontSize: big ? 14 : 12, marginLeft: 6 }}>({pct}%)</span>
    </span>
  )
}

// ── Confidence band results table ─────────────────────────────────────────────
function BandTable({ bands }) {
  if (!bands || bands.every(b => b.total === 0)) {
    return <p style={{ color: 'var(--silver)', fontSize: 13, marginTop: 8 }}>No graded picks yet.</p>
  }
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 10 }}>
      <thead>
        <tr>
          {['Confidence', 'W', 'L', 'Win%'].map(h => (
            <th key={h} style={{
              textAlign: h === 'Confidence' ? 'left' : 'right',
              fontSize: 11, fontWeight: 600, letterSpacing: 1,
              textTransform: 'uppercase', color: 'var(--silver)',
              paddingBottom: 6, borderBottom: '1px solid var(--navy-border)',
            }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {bands.map(b => {
          const pct = b.total > 0 ? (b.wins / b.total * 100).toFixed(1) : null
          return (
            <tr key={b.band} style={{ borderBottom: '1px solid var(--navy-border)' }}>
              <td style={{ padding: '6px 0', fontSize: 13, color: 'var(--silver)' }}>{b.band}</td>
              <td style={{ textAlign: 'right', fontSize: 13, color: '#4ade80', fontWeight: 700 }}>{b.total > 0 ? b.wins : '—'}</td>
              <td style={{ textAlign: 'right', fontSize: 13, color: '#fb923c', fontWeight: 700 }}>{b.total > 0 ? b.losses : '—'}</td>
              <td style={{ textAlign: 'right', fontSize: 13, color: 'var(--white)', fontWeight: 700 }}>
                {pct != null ? `${pct}%` : '—'}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// ── Results card ──────────────────────────────────────────────────────────────
function ResultsCard({ title, subtitle, stats }) {
  if (!stats || !stats.total) return null
  const { total, by_confidence } = stats
  return (
    <div style={{
      background: 'var(--navy-mid)', border: '1px solid var(--navy-border)',
      borderRadius: 8, padding: '20px 24px', flex: 1, minWidth: 0,
    }}>
      <div style={{
        fontFamily: "'Barlow Condensed', sans-serif", fontWeight: 700,
        fontSize: 13, letterSpacing: 2, textTransform: 'uppercase',
        color: 'var(--accent)', marginBottom: 4,
      }}>{title}</div>
      {subtitle && <div style={{ color: 'var(--silver)', fontSize: 12, marginBottom: 12 }}>{subtitle}</div>}
      <div style={{ marginBottom: 14 }}>
        <div style={{ color: 'var(--silver)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Overall</div>
        <Record wins={total.wins} losses={total.losses} total={total.total} size="big" />
      </div>
      <BandTable bands={by_confidence} />
    </div>
  )
}

// ── Predictions table ─────────────────────────────────────────────────────────
function PredTable({ predictions, date: dateStr, onDownload }) {
  if (!predictions?.length) {
    return (
      <div style={{
        background: 'var(--navy-mid)', border: '1px solid var(--navy-border)',
        borderRadius: 8, padding: '32px 24px', textAlign: 'center', color: 'var(--silver)',
      }}>
        No games scheduled for today.
      </div>
    )
  }

  const thStyle = {
    textAlign: 'left', fontSize: 11, fontWeight: 600, letterSpacing: 1,
    textTransform: 'uppercase', color: 'var(--silver)',
    padding: '8px 10px', borderBottom: '2px solid var(--navy-border)', whiteSpace: 'nowrap',
  }
  const tdStyle = {
    padding: '10px 10px', borderBottom: '1px solid var(--navy-border)',
    fontSize: 13, verticalAlign: 'middle',
  }

  return (
    <div style={{
      background: 'var(--navy-mid)', border: '1px solid var(--navy-border)',
      borderRadius: 8, overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '14px 18px', borderBottom: '1px solid var(--navy-border)',
      }}>
        <div style={{
          fontFamily: "'Barlow Condensed', sans-serif", fontWeight: 700,
          fontSize: 13, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--accent)',
        }}>
          Today's Picks — {dateStr}
        </div>
        <button
          onClick={onDownload}
          style={{
            background: 'transparent', border: '1px solid var(--accent)',
            borderRadius: 4, color: 'var(--accent)', fontSize: 11, fontWeight: 700,
            fontFamily: "'Barlow Condensed', sans-serif", letterSpacing: 1,
            textTransform: 'uppercase', padding: '5px 12px', cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 6, transition: 'background 0.15s, color 0.15s',
          }}
          onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent)'; e.currentTarget.style.color = '#000' }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--accent)' }}
        >
          ↓ Download CSV
        </button>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 780 }}>
          <thead>
            <tr>
              <th style={thStyle}>Time</th>
              <th style={thStyle}>Away Team</th>
              <th style={thStyle}>Home Team</th>
              <th style={{ ...thStyle, textAlign: 'center' }}>Away %</th>
              <th style={{ ...thStyle, textAlign: 'center' }}>Home %</th>
              <th style={{ ...thStyle, textAlign: 'center' }}>LogR</th>
              <th style={{ ...thStyle, textAlign: 'center' }}>XGB</th>
              <th style={{ ...thStyle, textAlign: 'center' }}>MLP</th>
              <th style={thStyle}>Pick</th>
              <th style={{ ...thStyle, textAlign: 'center' }}>Confidence</th>
            </tr>
            <tr>
              {['','','','','','home','home','home','',''].map((lbl, i) => (
                <th key={i} style={{
                  fontSize: 9, color: 'var(--silver)', textAlign: 'center',
                  paddingBottom: 4, fontStyle: 'italic', opacity: 0.6,
                  borderBottom: '1px solid var(--navy-border)', fontWeight: 400,
                }}>
                  {lbl}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {predictions.map((p, i) => {
              const isAway = p.pick === p.away_team
              return (
                <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)' }}>
                  <td style={{ ...tdStyle, color: 'var(--silver)', whiteSpace: 'nowrap' }}>{p.game_time}</td>
                  <td style={{ ...tdStyle, color: isAway ? 'var(--white)' : 'var(--silver)', fontWeight: isAway ? 700 : 400 }}>
                    {p.away_team}
                  </td>
                  <td style={{ ...tdStyle, color: !isAway ? 'var(--white)' : 'var(--silver)', fontWeight: !isAway ? 700 : 400 }}>
                    {p.home_team}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'center', color: isAway ? 'var(--white)' : 'var(--silver)', fontFamily: 'monospace' }}>
                    {p.away_prob != null ? (p.away_prob * 100).toFixed(1) + '%' : '—'}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'center', color: !isAway ? 'var(--white)' : 'var(--silver)', fontFamily: 'monospace' }}>
                    {p.home_prob != null ? (p.home_prob * 100).toFixed(1) + '%' : '—'}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'center' }}><BaseProb value={p.base_logr_home} /></td>
                  <td style={{ ...tdStyle, textAlign: 'center' }}><BaseProb value={p.base_xgb_home}  /></td>
                  <td style={{ ...tdStyle, textAlign: 'center' }}><BaseProb value={p.base_mlp_home}  /></td>
                  <td style={{ ...tdStyle, color: 'var(--white)', fontWeight: 700 }}>{p.pick}</td>
                  <td style={{ ...tdStyle, textAlign: 'center' }}><ConfText confidence={p.confidence} /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div style={{
        padding: '8px 18px', borderTop: '1px solid var(--navy-border)',
        fontSize: 11, color: 'var(--silver)', opacity: 0.7,
      }}>
        LogR / XGB / MLP = base model home-win probability before meta-learner blending
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function ResearchGame() {
  const { data, loading, error } = useResearchData()

  const handleDownload = () => {
    if (data?.predictions) downloadCSV(data.predictions, data.date ?? 'today')
  }

  const updatedLabel = data?.updated
    ? new Date(data.updated).toLocaleString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
      })
    : null

  return (
    <Layout title="Research-Based Model">
      <PageHeader
        tag="Games → Research-Based"
        title="RESEARCH-BASED MODEL"
        subtitle="Stacked ensemble extending Allen & Savala (2025) — Logistic Regression, XGBoost, and MLP Neural Network base models combined via a learned meta-learner, with isotonic calibration for reliable win probabilities."
      />

      {updatedLabel && (
        <div style={{ color: 'var(--silver)', fontSize: 12, marginBottom: 20 }}>
          Last updated: {updatedLabel}
        </div>
      )}

      {loading && (
        <div style={{
          background: 'var(--navy-mid)', border: '1px solid var(--navy-border)',
          borderRadius: 8, padding: '40px 24px', textAlign: 'center', color: 'var(--silver)',
        }}>
          Loading predictions…
        </div>
      )}

      {error && (
        <div style={{
          background: '#1a0000', border: '1px solid #ff4444', borderRadius: 8,
          padding: '20px 24px', color: '#ff8888', marginBottom: 24,
        }}>
          Failed to load predictions: {error}
        </div>
      )}

      {data && (
        <>
          <PredTable
            predictions={data.predictions}
            date={data.date}
            onDownload={handleDownload}
          />

          <div style={{ display: 'flex', gap: 20, marginTop: 28, flexWrap: 'wrap' }}>
            <ResultsCard
              title="Yesterday's Results"
              subtitle={data.yesterday?.date
                ? new Date(data.yesterday.date + 'T12:00:00').toLocaleDateString('en-US',
                    { weekday: 'long', month: 'long', day: 'numeric' })
                : null}
              stats={data.yesterday}
            />
            <ResultsCard
              title="All-Time Results"
              subtitle="Since model tracking began"
              stats={data.alltime}
            />
          </div>

          <div style={{
            marginTop: 28, background: 'var(--navy-mid)', border: '1px solid var(--navy-border)',
            borderRadius: 8, padding: '16px 20px', fontSize: 12, color: 'var(--silver)', lineHeight: 1.7,
          }}>
            <span style={{ fontWeight: 700, color: 'var(--white)' }}>About this model — </span>
            Three base models (Logistic Regression, XGBoost, MLP Neural Network) are each trained on 2015–2020 MLB game logs.
            Their probability outputs are stacked and fed into a meta-learner trained on 2021–2022 seasons,
            which learns the optimal blend. Isotonic regression then maps predictions to true win frequencies.
            Features include season-to-date averages, exponentially-decayed recency weights,
            and 7- and 15-game rolling windows for both hitting and pitching stats.
          </div>
        </>
      )}
    </Layout>
  )
}
