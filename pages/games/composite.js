import { useState, useEffect } from 'react'
import Layout from '../../components/Layout'
import { PageHeader } from '../../components/PredictionTable'

// ── Data hook ─────────────────────────────────────────────────────────────────
function useCompositeData() {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  useEffect(() => {
    fetch('/data/games-composite.json')
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
    'Log5 Pick','Log5 Conf',
    'Research Pick','Research Conf',
    'XGBoost Pick','XGBoost Conf',
    'RF Pick','RF Conf',
    'Composite Pick','Composite Conf','Votes',
  ]
  const rows = predictions.map(p => [
    dateStr,
    p.away_team,
    p.home_team,
    p.log5?.pick          ?? '',
    p.log5          ? (p.log5.confidence          * 100).toFixed(1) + '%' : '',
    p.research?.pick      ?? '',
    p.research      ? (p.research.confidence      * 100).toFixed(1) + '%' : '',
    p.xgboost?.pick       ?? '',
    p.xgboost       ? (p.xgboost.confidence       * 100).toFixed(1) + '%' : '',
    p.random_forest?.pick ?? '',
    p.random_forest ? (p.random_forest.confidence * 100).toFixed(1) + '%' : '',
    p.composite_pick,
    p.composite_confidence != null ? (p.composite_confidence * 100).toFixed(1) + '%' : '',
    `${p.vote_count}/${p.total_votes}`,
  ])
  const csv  = [headers, ...rows].map(r => r.map(v => `"${v}"`).join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `composite_picks_${dateStr.replace(/-/g, '')}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 100)
}

// ── Shared styling helpers ────────────────────────────────────────────────────
function confColor(pct) {
  if (pct >= 80) return '#4ade80'
  if (pct >= 70) return '#60a5fa'
  if (pct >= 60) return '#fbbf24'
  return '#fb923c'
}

function ConfText({ confidence, size = 'sm' }) {
  if (confidence == null) return <span style={{ color: 'var(--silver)' }}>—</span>
  const pct = confidence * 100
  return (
    <span style={{
      color:      confColor(pct),
      fontWeight: 700,
      fontSize:   size === 'lg' ? 18 : size === 'md' ? 14 : 12,
      fontFamily: "'Barlow Condensed', sans-serif",
    }}>
      {pct.toFixed(1)}%
    </span>
  )
}

// ── Top 3 picks cards ─────────────────────────────────────────────────────────
function TopPicksRow({ predictions }) {
  if (!predictions?.length) return null
  const top3   = predictions.slice(0, 3)
  const labels = ['TOP PICK', '2ND PICK', '3RD PICK']

  return (
    <div style={{ display: 'flex', gap: 16, marginBottom: 28, flexWrap: 'wrap' }}>
      {top3.map((p, i) => {
        const pct     = p.composite_confidence * 100
        const matchup = `${p.away_team} @ ${p.home_team}`
        return (
          <div key={i} style={{
            background:   'var(--navy-mid)',
            border:       `1px solid ${confColor(pct)}40`,
            borderTop:    `3px solid ${confColor(pct)}`,
            borderRadius: 8,
            padding:      '16px 20px',
            flex:         1,
            minWidth:     200,
          }}>
            <div style={{
              fontFamily:    "'Barlow Condensed', sans-serif",
              fontSize:      11, fontWeight: 700, letterSpacing: 2,
              textTransform: 'uppercase', color: confColor(pct), marginBottom: 8,
            }}>
              {labels[i]}
            </div>
            <div style={{
              fontFamily: "'Barlow Condensed', sans-serif",
              fontSize: 20, fontWeight: 900, color: 'var(--white)', lineHeight: 1.1, marginBottom: 6,
            }}>
              {p.composite_pick}
            </div>
            <div style={{ marginBottom: 8 }}>
              <ConfText confidence={p.composite_confidence} size="lg" />
            </div>
            <div style={{ fontSize: 11, color: 'var(--silver)', lineHeight: 1.5 }}>
              <div>{matchup}</div>
              <div>{p.game_time}</div>
            </div>
            <div style={{
              marginTop: 8, fontSize: 10, color: 'var(--silver)',
              fontFamily: "'Barlow Condensed', sans-serif", letterSpacing: 0.5,
            }}>
              {p.vote_count}/{p.total_votes} models agree
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Small model cell for the table ────────────────────────────────────────────
function ModelCell({ modelData, away }) {
  const tdBase = {
    padding: '8px 6px', borderBottom: '1px solid var(--navy-border)',
    textAlign: 'center', verticalAlign: 'middle',
  }
  if (!modelData) {
    return <td style={{ ...tdBase, color: 'var(--silver)', fontSize: 11 }}>—</td>
  }
  const isAway   = modelData.pick === away
  const lastName = modelData.pick.split(' ').slice(-1)[0]
  return (
    <td style={tdBase}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--white)', marginBottom: 2, whiteSpace: 'nowrap' }}>
        {isAway ? '↑' : '↓'} {lastName}
      </div>
      <ConfText confidence={modelData.confidence} size="sm" />
    </td>
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

// ── Confidence band table ─────────────────────────────────────────────────────
function BandTable({ bands }) {
  if (!bands || bands.every(b => b.total === 0)) {
    return <p style={{ color: 'var(--silver)', fontSize: 13, marginTop: 8 }}>No graded picks yet.</p>
  }
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 10 }}>
      <thead>
        <tr>
          {['Confidence','W','L','Win%'].map(h => (
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
              <td style={{ textAlign: 'right', fontSize: 13, color: 'var(--white)', fontWeight: 700 }}>{pct != null ? `${pct}%` : '—'}</td>
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

// ── Model standings card ──────────────────────────────────────────────────────
function StandingsCard({ standings }) {
  if (!standings?.length) return null
  return (
    <div style={{
      background: 'var(--navy-mid)', border: '1px solid var(--navy-border)',
      borderRadius: 8, padding: '20px 24px', flex: 1, minWidth: 0,
    }}>
      <div style={{
        fontFamily: "'Barlow Condensed', sans-serif", fontWeight: 700,
        fontSize: 13, letterSpacing: 2, textTransform: 'uppercase',
        color: 'var(--accent)', marginBottom: 12,
      }}>Model Standings</div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            {['Model','W','L','Win%'].map(h => (
              <th key={h} style={{
                textAlign: h === 'Model' ? 'left' : 'right',
                fontSize: 11, fontWeight: 600, letterSpacing: 1,
                textTransform: 'uppercase', color: 'var(--silver)',
                paddingBottom: 6, borderBottom: '1px solid var(--navy-border)',
              }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {standings.map((s, i) => {
            const pct = s.total > 0 ? (s.pct * 100).toFixed(1) + '%' : '—'
            return (
              <tr key={s.model} style={{ borderBottom: '1px solid var(--navy-border)' }}>
                <td style={{ padding: '6px 0', fontSize: 13, color: 'var(--white)', fontWeight: i === 0 ? 700 : 400 }}>
                  {i === 0 ? '🥇 ' : i === 1 ? '🥈 ' : i === 2 ? '🥉 ' : '    '}{s.model}
                </td>
                <td style={{ textAlign: 'right', fontSize: 13, color: '#4ade80', fontWeight: 700 }}>{s.total > 0 ? s.wins : '—'}</td>
                <td style={{ textAlign: 'right', fontSize: 13, color: '#fb923c', fontWeight: 700 }}>{s.total > 0 ? s.losses : '—'}</td>
                <td style={{ textAlign: 'right', fontSize: 13, color: 'var(--white)', fontWeight: 700 }}>{pct}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Main predictions table ────────────────────────────────────────────────────
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
    textAlign: 'center', fontSize: 10, fontWeight: 600, letterSpacing: 1,
    textTransform: 'uppercase', color: 'var(--silver)',
    padding: '8px 6px', borderBottom: '2px solid var(--navy-border)', whiteSpace: 'nowrap',
  }
  const tdStyle = {
    padding: '8px 6px', borderBottom: '1px solid var(--navy-border)',
    fontSize: 12, verticalAlign: 'middle',
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
          All Games — {dateStr}
        </div>
        <button
          onClick={onDownload}
          style={{
            background: 'transparent', border: '1px solid var(--accent)',
            borderRadius: 4, color: 'var(--accent)', fontSize: 11, fontWeight: 700,
            fontFamily: "'Barlow Condensed', sans-serif", letterSpacing: 1,
            textTransform: 'uppercase', padding: '5px 12px', cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 6,
            transition: 'background 0.15s, color 0.15s',
          }}
          onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent)'; e.currentTarget.style.color = '#000' }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--accent)' }}
        >
          ↓ Download CSV
        </button>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 820 }}>
          <thead>
            <tr>
              <th style={{ ...thStyle, textAlign: 'left' }}>Time</th>
              <th style={{ ...thStyle, textAlign: 'left' }}>Away</th>
              <th style={{ ...thStyle, textAlign: 'left' }}>Home</th>
              <th style={thStyle}>Log5</th>
              <th style={thStyle}>Research</th>
              <th style={thStyle}>XGBoost</th>
              <th style={thStyle}>Rand. Forest</th>
              <th style={{ ...thStyle, textAlign: 'left' }}>Composite Pick</th>
              <th style={thStyle}>Conf</th>
              <th style={thStyle}>Votes</th>
            </tr>
          </thead>
          <tbody>
            {predictions.map((p, i) => {
              const isAway = p.composite_pick === p.away_team
              return (
                <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)' }}>
                  <td style={{ ...tdStyle, color: 'var(--silver)', whiteSpace: 'nowrap' }}>{p.game_time}</td>
                  <td style={{ ...tdStyle, color: isAway ? 'var(--white)' : 'var(--silver)', fontWeight: isAway ? 700 : 400 }}>
                    {p.away_team}
                  </td>
                  <td style={{ ...tdStyle, color: !isAway ? 'var(--white)' : 'var(--silver)', fontWeight: !isAway ? 700 : 400 }}>
                    {p.home_team}
                  </td>
                  <ModelCell modelData={p.log5}          away={p.away_team} />
                  <ModelCell modelData={p.research}      away={p.away_team} />
                  <ModelCell modelData={p.xgboost}       away={p.away_team} />
                  <ModelCell modelData={p.random_forest} away={p.away_team} />
                  <td style={{ ...tdStyle, color: 'var(--white)', fontWeight: 700 }}>
                    {p.composite_pick}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'center' }}>
                    <ConfText confidence={p.composite_confidence} size="md" />
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'center', color: 'var(--silver)', fontSize: 11 }}>
                    {p.vote_count}/{p.total_votes}
                  </td>
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
        ↑ = away team pick &nbsp;|&nbsp; ↓ = home team pick &nbsp;|&nbsp;
        Table sorted by composite confidence — highest at top
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function CompositePage() {
  const { data, loading, error } = useCompositeData()

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
    <Layout title="Composite Model">
      <PageHeader
        tag="Games → Composite"
        title="COMPOSITE MODEL"
        subtitle="Majority-vote ensemble of Log5, Research, XGBoost, and Random Forest — composite confidence weighted by each model's implied support for the winning pick."
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
          <TopPicksRow predictions={data.predictions} />

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
              subtitle="Since composite tracking began"
              stats={data.alltime}
            />
            <StandingsCard standings={data.model_standings} />
          </div>

          <div style={{
            marginTop: 28, background: 'var(--navy-mid)', border: '1px solid var(--navy-border)',
            borderRadius: 8, padding: '16px 20px', fontSize: 12, color: 'var(--silver)', lineHeight: 1.7,
          }}>
            <span style={{ fontWeight: 700, color: 'var(--white)' }}>About this model — </span>
            Each game receives a vote from all four models. The majority winner (3+ votes) becomes
            the composite pick; on a 2-2 tie the team with higher average implied confidence wins.
            Composite confidence is the average of each model's support for the composite winner —
            models that agreed contribute their confidence directly, while dissenting models
            contribute their implied probability for the composite winner (1 minus their confidence).
            The three games at the top represent today's highest-confidence composite picks.
          </div>
        </>
      )}
    </Layout>
  )
}
