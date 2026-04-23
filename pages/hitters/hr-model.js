import { useState, useEffect } from 'react'
import Layout from '../../components/Layout'

/*
 * ─── EXPECTED JSON SHAPE (public/data/hitters-hr-model.json) ─────────────────
 * {
 *   "updated": "2026-04-22T09:00:00Z",
 *   "date": "2026-04-22",
 *   "predictions": [
 *     {
 *       "rank": 1, "player": "Aaron Judge", "team": "NYY", "hand": "R",
 *       "game": "NYY @ BOS", "game_time": "7:10 PM ET", "park": "Fenway Park",
 *       "score": 82, "confidence": "high",
 *       "batter_score": 91,
 *       "pitcher_score": 74,     ← combined (65% SP + 35% bullpen)
 *       "sp_score": 78,          ← raw SP vulnerability
 *       "bullpen_score": 65,     ← raw team pitching vulnerability
 *       "park_score": 55, "context_score": 62,
 *       "sp_name": "Nick Pivetta", "sp_era": "4.25", "sp_listed": true,
 *       "hr": 8, "hr_per_ab": 0.065, "iso": 0.285, "slg": 0.620, "ops": 0.990,
 *       "temp_f": 68.0, "wind_mph": 8.2, "wind_hr_adj": 1.04, "hr_factor": 1.04,
 *       "recent_form": "8 HR, HR/AB .065, ISO .285",
 *       "reasoning": "...",
 *       "actual_hr": null, "correct": null
 *     }, ...
 *   ],
 *   "yesterday": { "date": "...", "total": 25, "hr_count": 5, "hit_rate_pct": 20.0,
 *                  "hr_players": [...], "by_bucket": {...} },
 *   "alltime":   { "total": 150, "hr_count": 28, "hit_rate_pct": 18.7, "by_bucket": {...} }
 * }
 */

const TOP_N = 25

// ── Colour helpers ─────────────────────────────────────────────────────────────
const scoreColor = (s) =>
  s >= 70 ? 'var(--yellow)' : s >= 55 ? 'var(--accent)' : 'var(--silver-dim)'

const CONF = {
  high:   { border: 'var(--yellow)',      color: 'var(--yellow)',      bg: 'rgba(212,168,67,0.10)' },
  medium: { border: 'var(--accent)',      color: 'var(--accent)',      bg: 'rgba(74,144,217,0.10)' },
  low:    { border: 'var(--navy-border)', color: 'var(--silver-dim)', bg: 'transparent' },
}

const rankColor = (i) =>
  i === 0 ? '#FFD700' : i === 1 ? '#C0C0C0' : i === 2 ? '#CD7F32' : 'var(--silver-dim)'

// Dot: bright yellow ≥65, faded yellow 45–64, dim <45
const dotColor = (v) =>
  v >= 65 ? 'var(--yellow)' : v >= 45 ? 'rgba(212,168,67,0.4)' : 'var(--navy-border)'

// ── Small reusable components ──────────────────────────────────────────────────
function ConfBadge({ conf }) {
  const s = CONF[conf] || CONF.low
  const label = conf === 'high' ? 'HIGH' : conf === 'medium' ? 'MED' : 'LOW'
  return (
    <span style={{
      border:        `1px solid ${s.border}`,
      color:         s.color,
      background:    s.bg,
      fontSize:      10,
      fontWeight:    700,
      letterSpacing: '1.5px',
      textTransform: 'uppercase',
      padding:       '2px 7px',
      display:       'inline-block',
      fontFamily:    "'DM Mono', monospace",
      borderRadius:  2,
    }}>
      {label}
    </span>
  )
}

function ScoreBar({ score }) {
  const color = scoreColor(score)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 100 }}>
      <div style={{ flex: 1, height: 4, background: 'var(--navy-border)', borderRadius: 2 }}>
        <div style={{
          height: '100%', width: `${score}%`, background: color,
          borderRadius: 2, transition: 'width 0.3s ease',
        }} />
      </div>
      <span style={{
        fontFamily: "'DM Mono', monospace", fontSize: 14, color,
        minWidth: 24, textAlign: 'right', fontWeight: 600,
      }}>{score}</span>
    </div>
  )
}

function MiniBar({ value, color }) {
  return (
    <div style={{ flex: 1, height: 3, background: 'var(--navy-border)', borderRadius: 2 }}>
      <div style={{
        height: '100%', width: `${value ?? 0}%`,
        background: color || scoreColor(value ?? 0), borderRadius: 2,
      }} />
    </div>
  )
}

function FactorDots({ batter_score, pitcher_score, park_score, context_score }) {
  const factors = [
    { label: 'Batter',   v: batter_score  },
    { label: 'Pitcher',  v: pitcher_score },
    { label: 'Park',     v: park_score    },
    { label: 'Context',  v: context_score },
  ]
  return (
    <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
      {factors.map(f => (
        <div key={f.label} title={`${f.label}: ${f.v ?? '—'}`}
          style={{
            width: 9, height: 9, borderRadius: '50%',
            background: dotColor(f.v ?? 0),
            border: `1px solid ${(f.v ?? 0) >= 45 ? 'var(--yellow)' : 'var(--navy-border)'}`,
            cursor: 'help', flexShrink: 0,
          }}
        />
      ))}
    </div>
  )
}

function StatRow({ label, value }) {
  if (value == null || value === '—') return null
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 3 }}>
      <span style={{ color: 'var(--silver-dim)', fontSize: 11 }}>{label}</span>
      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: 'var(--white)' }}>
        {value}
      </span>
    </div>
  )
}

// ── Yesterday / all-time accuracy panel ───────────────────────────────────────
function SummaryPanel({ title, total, hr_count, hit_rate_pct, by_bucket }) {
  const hasData = total > 0
  return (
    <div style={{
      background: 'var(--navy)', border: '1px solid var(--navy-border)',
      borderRadius: 6, padding: '14px 18px', flex: '1 1 200px',
    }}>
      <div style={{
        fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)',
        letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 8,
      }}>{title}</div>

      {hasData ? (
        <>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 10 }}>
            <span style={{
              fontFamily: "'Barlow Condensed', sans-serif",
              fontSize: 28, fontWeight: 700, color: 'var(--yellow)',
            }}>{hr_count}</span>
            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: 'var(--silver-dim)' }}>
              / {total} hit HRs
            </span>
            <span style={{ marginLeft: 'auto', fontFamily: "'DM Mono', monospace", fontSize: 13, color: 'var(--accent)' }}>
              {hit_rate_pct}%
            </span>
          </div>
          {by_bucket && Object.entries(by_bucket).map(([bucket, s]) => (
            <div key={bucket} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', minWidth: 36 }}>
                {bucket}
              </span>
              <MiniBar value={s.rate_pct} color="var(--yellow)" />
              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', minWidth: 32, textAlign: 'right' }}>
                {s.rate_pct}%
              </span>
            </div>
          ))}
        </>
      ) : (
        <div style={{ color: 'var(--silver-dim)', fontSize: 12, paddingTop: 4 }}>
          No graded picks yet
        </div>
      )}
    </div>
  )
}

// ── CSV download ──────────────────────────────────────────────────────────────
function downloadCSV(rows, dateStr) {
  const headers = [
    'Rank', 'Player', 'Team', 'Hand', 'Game', 'Time', 'Park',
    'Score', 'Confidence',
    'Batter Score', 'Pitcher Score', 'SP Score', 'Bullpen Score', 'Park Score', 'Context Score',
    'SP Name', 'SP ERA',
    'HR (Season)', 'HR/AB', 'ISO', 'SLG', 'OPS',
    'Temp (°F)', 'Wind (mph)', 'Wind HR Adj', 'HR Factor',
    'Recent Form',
  ]
  const escape = v => {
    const s = v == null ? '' : String(v)
    return s.includes(',') || s.includes('"') || s.includes('\n')
      ? `"${s.replace(/"/g, '""')}"` : s
  }
  const csvRows = [
    headers.join(','),
    ...rows.map(p => [
      p.rank, p.player, p.team, p.hand, p.game, p.game_time, p.park,
      p.score, p.confidence,
      p.batter_score, p.pitcher_score, p.sp_score, p.bullpen_score, p.park_score, p.context_score,
      p.sp_name, p.sp_era,
      p.hr, p.hr_per_ab, p.iso, p.slg, p.ops,
      p.temp_f, p.wind_mph, p.wind_hr_adj, p.hr_factor,
      p.recent_form,
    ].map(escape).join(',')),
  ]
  const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `hr_picks_${(dateStr ?? 'today').replace(/-/g, '')}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 100)
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function HRModel() {
  const [fullData,   setFullData]   = useState(null)
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(null)
  const [expanded,   setExpanded]   = useState(null)
  const [sortCol,    setSortCol]    = useState('score')
  const [sortAsc,    setSortAsc]    = useState(false)
  const [handFilter, setHandFilter] = useState('all')
  const [gameFilter, setGameFilter] = useState('all')
  const [minScore,   setMinScore]   = useState(0)

  useEffect(() => {
    fetch('/data/hitters-hr-model.json')
      .then(r => {
        if (!r.ok) throw new Error(`Could not load hitters-hr-model.json (${r.status})`)
        return r.json()
      })
      .then(json => { setFullData(json); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  const preds     = fullData?.predictions ?? []
  const yesterday = fullData?.yesterday   ?? {}
  const alltime   = fullData?.alltime     ?? {}
  const updated   = fullData?.updated     ?? null
  const gameDate  = fullData?.date        ?? null

  const allGames = [...new Set(preds.map(p => p.game))].sort()

  const filtered = [...preds]
    .filter(p => (p.score ?? 0) >= minScore)
    .filter(p => handFilter === 'all' || p.hand === handFilter)
    .filter(p => gameFilter === 'all' || p.game === gameFilter)
    .sort((a, b) => {
      let av = a[sortCol] ?? '', bv = b[sortCol] ?? ''
      if (typeof av === 'string') { av = av.toLowerCase(); bv = bv.toLowerCase() }
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

  const Th = ({ col, label }) => (
    <th onClick={() => handleSort(col)} style={{
      padding: '9px 14px', textAlign: 'left',
      fontFamily: "'DM Mono', monospace", fontSize: 9,
      letterSpacing: '2px', textTransform: 'uppercase',
      color: sortCol === col ? 'var(--yellow)' : 'var(--silver-dim)',
      cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap',
      background: 'var(--navy)', borderBottom: '1px solid var(--navy-border)',
    }}>
      {label}{sortCol === col ? (sortAsc ? ' ↑' : ' ↓') : ''}
    </th>
  )

  const fixedTh = (label) => (
    <th style={{
      padding: '9px 14px',
      fontFamily: "'DM Mono', monospace", fontSize: 9,
      letterSpacing: '2px', textTransform: 'uppercase',
      color: 'var(--silver-dim)', background: 'var(--navy)',
      borderBottom: '1px solid var(--navy-border)',
    }}>{label}</th>
  )

  return (
    <Layout title="HR Model">

      {/* ── Page header ──────────────────────────────────────────────────── */}
      <div style={{ marginBottom: '2rem', borderLeft: '3px solid var(--yellow)', paddingLeft: '1.25rem' }}>
        <div style={{
          fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--yellow)',
          letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 8,
        }}>Hitters → HR Model</div>
        <h1 style={{
          fontFamily: "'Barlow Condensed', sans-serif", fontWeight: 900,
          fontSize: '2.4rem', color: 'var(--white)', lineHeight: 1.1, marginBottom: 8,
        }}>HOME RUN PREDICTIONS</h1>
        <p style={{ fontSize: 13.5, color: 'var(--silver)', maxWidth: 600, lineHeight: 1.65 }}>
          Top {TOP_N} HR candidates scored by a four-factor model:{' '}
          <span style={{ color: 'var(--white)' }}>Batter Power (42%)</span>,{' '}
          <span style={{ color: 'var(--white)' }}>Pitcher Vulnerability (35%)</span>{' '}
          <span style={{ color: 'var(--silver-dim)', fontSize: 12 }}>[65% SP + 35% bullpen]</span>,{' '}
          <span style={{ color: 'var(--white)' }}>Park Factor (15%)</span>,{' '}
          <span style={{ color: 'var(--white)' }}>Weather Context (8%)</span>.
          Updated daily at 9 AM ET.
        </p>
        {updatedStr && (
          <div style={{ marginTop: 10, fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--silver-dim)' }}>
            Last updated: {updatedStr}
            {gameDate && <span style={{ marginLeft: 10 }}>· Slate: {gameDate}</span>}
          </div>
        )}
      </div>

      {/* ── Loading / error states ───────────────────────────────────────── */}
      {loading && (
        <div style={{ textAlign: 'center', padding: '80px 20px', color: 'var(--silver-dim)', fontFamily: "'DM Mono', monospace", fontSize: 12 }}>
          Loading predictions…
        </div>
      )}
      {error && (
        <div style={{
          padding: '16px 20px', background: 'rgba(224,84,84,0.08)',
          border: '1px solid var(--red)', borderRadius: 6,
          color: 'var(--red)', fontSize: 13, marginBottom: 24,
        }}>
          ⚠ {error}
        </div>
      )}

      {!loading && !error && fullData && (
        <>
          {/* ── Filter controls ──────────────────────────────────────────── */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
            {[
              { label: 'Min Score', value: minScore,   setter: v => setMinScore(+v),   options: [['0','Any'],['50','50+'],['60','60+'],['70','70+']] },
              { label: 'Hand',      value: handFilter, setter: v => setHandFilter(v),  options: [['all','All'],['L','LHB'],['R','RHB'],['S','Switch']] },
            ].map(ctrl => (
              <div key={ctrl.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--silver-dim)' }}>
                  {ctrl.label}
                </span>
                <select value={ctrl.value} onChange={e => ctrl.setter(e.target.value)} style={{
                  fontFamily: "'DM Mono', monospace", fontSize: 12,
                  background: 'var(--navy)', color: 'var(--white)',
                  border: '1px solid var(--navy-border)', padding: '5px 9px',
                  cursor: 'pointer', borderRadius: 3,
                }}>
                  {ctrl.options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </div>
            ))}

            {allGames.length > 1 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--silver-dim)' }}>Game</span>
                <select value={gameFilter} onChange={e => setGameFilter(e.target.value)} style={{
                  fontFamily: "'DM Mono', monospace", fontSize: 12,
                  background: 'var(--navy)', color: 'var(--white)',
                  border: '1px solid var(--navy-border)', padding: '5px 9px',
                  cursor: 'pointer', borderRadius: 3,
                }}>
                  <option value="all">All Games</option>
                  {allGames.map(g => <option key={g} value={g}>{g}</option>)}
                </select>
              </div>
            )}

            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--silver-dim)' }}>
                {filtered.length} players · click row to expand
              </span>
              <button
                onClick={() => downloadCSV(filtered, gameDate)}
                disabled={filtered.length === 0}
                style={{
                  background: 'transparent', border: '1px solid var(--accent)',
                  borderRadius: 4, color: 'var(--accent)', fontSize: 11, fontWeight: 700,
                  fontFamily: "'Barlow Condensed', sans-serif", letterSpacing: 1,
                  textTransform: 'uppercase', padding: '5px 12px', cursor: filtered.length === 0 ? 'not-allowed' : 'pointer',
                  opacity: filtered.length === 0 ? 0.4 : 1,
                  transition: 'background 0.15s, color 0.15s',
                }}
                onMouseEnter={e => { if (filtered.length > 0) { e.currentTarget.style.background = 'var(--accent)'; e.currentTarget.style.color = '#000' }}}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--accent)' }}
              >
                ↓ Download CSV
              </button>
            </div>
          </div>

          {/* ── Table ────────────────────────────────────────────────────── */}
          {filtered.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--silver-dim)' }}>
              No predictions match the current filters.
            </div>
          ) : (
            <div style={{ overflowX: 'auto', border: '1px solid var(--navy-border)', borderRadius: 4 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr>
                    <th style={{
                      padding: '9px 14px', width: 36, textAlign: 'center',
                      fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px',
                      textTransform: 'uppercase', color: 'var(--silver-dim)',
                      background: 'var(--navy)', borderBottom: '1px solid var(--navy-border)',
                    }}>#</th>
                    <Th col="player"     label="Player"   />
                    <Th col="score"      label="HR Score" />
                    <Th col="game"       label="Matchup"  />
                    {fixedTh('Factors')}
                    <Th col="confidence" label="Conf"     />
                    {fixedTh('Key Stats')}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((p, i) => {
                    const isExp = expanded === i
                    return [
                      <tr
                        key={`r${i}`}
                        onClick={() => setExpanded(isExp ? null : i)}
                        style={{
                          cursor: 'pointer',
                          background: isExp ? 'var(--navy-hover)' : 'transparent',
                          transition: 'background 0.1s',
                        }}
                        onMouseEnter={e => { if (!isExp) e.currentTarget.style.background = 'var(--navy)' }}
                        onMouseLeave={e => { e.currentTarget.style.background = isExp ? 'var(--navy-hover)' : 'transparent' }}
                      >
                        {/* Rank */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)', textAlign: 'center', fontFamily: "'Barlow Condensed', sans-serif", fontSize: 16, fontWeight: 700, color: rankColor(i) }}>
                          {p.rank ?? i + 1}
                        </td>
                        {/* Player */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <div style={{ fontWeight: 600, color: 'var(--white)', fontSize: 14 }}>{p.player}</div>
                          <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', letterSpacing: '2px', textTransform: 'uppercase', marginTop: 2 }}>
                            {p.team} · {p.hand === 'L' ? 'LHB' : p.hand === 'S' ? 'SHB' : 'RHB'}
                          </div>
                        </td>
                        {/* Score */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)', minWidth: 120 }}>
                          <ScoreBar score={p.score ?? 0} />
                        </td>
                        {/* Matchup */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)', minWidth: 130 }}>
                          <div style={{ fontSize: 12, color: 'var(--silver)' }}>{p.game}</div>
                          <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', marginTop: 2 }}>
                            {p.game_time} · {p.park}
                          </div>
                        </td>
                        {/* Factor dots */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <FactorDots
                            batter_score={p.batter_score}
                            pitcher_score={p.pitcher_score}
                            park_score={p.park_score}
                            context_score={p.context_score}
                          />
                        </td>
                        {/* Confidence */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <ConfBadge conf={p.confidence} />
                        </td>
                        {/* Key stats */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)', fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--silver-dim)', maxWidth: 160 }}>
                          {p.recent_form || '—'}
                        </td>
                      </tr>,

                      /* ── Expanded detail row ── */
                      isExp && (
                        <tr key={`e${i}`}>
                          <td colSpan={7} style={{ background: 'var(--navy)', borderBottom: '1px solid var(--navy-border)', padding: '16px 20px' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>

                              {/* Analysis */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--yellow)', marginBottom: 6 }}>Analysis</div>
                                <p style={{ fontSize: 12, color: 'var(--silver)', lineHeight: 1.7 }}>{p.reasoning || '—'}</p>
                              </div>

                              {/* Pitcher breakdown */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--yellow)', marginBottom: 6 }}>
                                  Opposing Pitcher
                                </div>
                                <div style={{ fontWeight: 600, color: 'var(--white)', marginBottom: 6 }}>
                                  {p.sp_listed ? p.sp_name : (
                                    <span>
                                      TBD{' '}
                                      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', fontWeight: 400 }}>
                                        (team pitching used)
                                      </span>
                                    </span>
                                  )}
                                </div>
                                {p.sp_listed && <StatRow label="SP ERA" value={p.sp_era} />}
                                {/* SP vs bullpen split */}
                                <div style={{ marginTop: 8 }}>
                                  {[
                                    { label: `SP vuln (65%)`, val: p.sp_score, show: p.sp_listed },
                                    { label: `Bullpen vuln (35%)`, val: p.bullpen_score, show: true },
                                  ].filter(f => f.show).map(f => (
                                    <div key={f.label} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                                      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', minWidth: 110 }}>{f.label}</span>
                                      <MiniBar value={f.val} />
                                      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: scoreColor(f.val ?? 0), minWidth: 22, textAlign: 'right' }}>{f.val ?? '—'}</span>
                                    </div>
                                  ))}
                                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, paddingTop: 5, borderTop: '1px solid var(--navy-border)' }}>
                                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)' }}>Combined pitcher score</span>
                                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: scoreColor(p.pitcher_score ?? 0), fontWeight: 600 }}>{p.pitcher_score}</span>
                                  </div>
                                </div>
                              </div>

                              {/* Batter stats */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--yellow)', marginBottom: 6 }}>Batter Stats</div>
                                <StatRow label="HR (season)"  value={p.hr} />
                                <StatRow label="HR/AB"        value={p.hr_per_ab != null ? p.hr_per_ab.toFixed(3) : null} />
                                <StatRow label="ISO"          value={p.iso  != null ? p.iso.toFixed(3)  : null} />
                                <StatRow label="SLG"          value={p.slg  != null ? p.slg.toFixed(3)  : null} />
                                <StatRow label="OPS"          value={p.ops  != null ? p.ops.toFixed(3)  : null} />
                              </div>

                              {/* Park & weather */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--yellow)', marginBottom: 6 }}>Park & Weather</div>
                                <StatRow label="Park"        value={p.park} />
                                <StatRow label="HR Factor"   value={p.hr_factor != null ? p.hr_factor.toFixed(2) : null} />
                                {p.temp_f   != null && <StatRow label="Temp"  value={`${p.temp_f}°F`} />}
                                {p.wind_mph != null && p.wind_mph > 0 && <StatRow label="Wind" value={`${p.wind_mph} mph`} />}
                                {p.wind_hr_adj != null && <StatRow label="Wind HR Adj" value={p.wind_hr_adj.toFixed(3)} />}
                              </div>

                              {/* Full score breakdown */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--yellow)', marginBottom: 6 }}>Score Breakdown</div>
                                {[
                                  { label: 'Batter (42%)',  val: p.batter_score  },
                                  { label: 'Pitcher (35%)', val: p.pitcher_score },
                                  { label: 'Park (15%)',    val: p.park_score    },
                                  { label: 'Context (8%)',  val: p.context_score },
                                ].map(f => (
                                  <div key={f.label} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--silver-dim)', minWidth: 92 }}>{f.label}</span>
                                    <MiniBar value={f.val} />
                                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: scoreColor(f.val ?? 0), minWidth: 22, textAlign: 'right' }}>
                                      {f.val ?? '—'}
                                    </span>
                                  </div>
                                ))}
                                <div style={{ marginTop: 8, paddingTop: 6, borderTop: '1px solid var(--navy-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--silver-dim)' }}>Composite</span>
                                  <span style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 22, fontWeight: 700, color: scoreColor(p.score ?? 0) }}>
                                    {p.score}
                                  </span>
                                </div>
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

          {/* ── Tracking panels ──────────────────────────────────────────── */}
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 24 }}>
            <SummaryPanel
              title={`Yesterday (${yesterday.date || '—'})`}
              total={yesterday.total || 0}
              hr_count={yesterday.hr_count || 0}
              hit_rate_pct={yesterday.hit_rate_pct || 0}
              by_bucket={yesterday.by_bucket}
            />
            <SummaryPanel
              title="All-Time"
              total={alltime.total || 0}
              hr_count={alltime.hr_count || 0}
              hit_rate_pct={alltime.hit_rate_pct || 0}
              by_bucket={alltime.by_bucket}
            />
            {/* Factor dots legend */}
            <div style={{
              background: 'var(--navy)', border: '1px solid var(--navy-border)',
              borderRadius: 6, padding: '14px 18px', flex: '1 1 180px',
            }}>
              <div style={{
                fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)',
                letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 10,
              }}>Factor Dots</div>
              {[
                { label: 'Batter Power',  sub: '42% of score — ISO, HR/AB, OPS' },
                { label: 'Pitcher Vuln.', sub: '35% — 65% SP + 35% bullpen' },
                { label: 'Park Factor',   sub: '15% — hand-adjusted HR index' },
                { label: 'Context',       sub: '8% — temperature at game time' },
              ].map(item => (
                <div key={item.label} style={{ marginBottom: 6 }}>
                  <div style={{ fontSize: 11, color: 'var(--white)' }}>
                    <span style={{ color: 'var(--yellow)' }}>⬤ </span>{item.label}
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--silver-dim)', paddingLeft: 14 }}>{item.sub}</div>
                </div>
              ))}
            </div>
          </div>

        </>
      )}
    </Layout>
  )
}
