import { useState, useEffect } from 'react'
import Layout from '../../components/Layout'

/*
 * ─── EXPECTED JSON SHAPE (public/data/hitters-ml-hr.json) ───────────────────
 * {
 *   "updated": "2026-04-23T09:00:00Z",
 *   "date": "2026-04-23",
 *   "avg_lambda": 0.04821,
 *   "predictions": [
 *     {
 *       "rank": 1, "player": "Aaron Judge", "position": "RF",
 *       "team": "NYY", "game": "BOS @ NYY", "game_time": "7:05 PM ET",
 *       "opp_abbr": "BOS", "opp_sp": "Nick Pivetta",
 *       "park": "Yankee Stadium", "park_abbr": "NYY",
 *       "park_hr_factor": 1.20, "park_altitude_ft": 16,
 *       "lambda_poisson": 0.1142, "prob_binary": 0.118,
 *       "roll15_hr_pa": 0.0621, "roll60_hr_pa": 0.0554,
 *       "roll15_slg": 0.712,    "roll60_slg": 0.645,
 *       "roll60_hr_count": 11,
 *       "sc_barrel_pct": 22.4, "sc_exit_velo": 96.2, "sc_xslg": 0.740,
 *       "sp_era": 4.25, "sp_whip": 1.31,
 *       "is_home": 1, "bat_hand": "R", "platoon_adv": 0,
 *       "weather_temp_f": 68.0, "weather_wind_mph": 8.0,
 *       "weather_wind_out": 5.2,
 *       "actual_hr": null, "correct": null
 *     }, ...
 *   ],
 *   "yesterday": {...}, "alltime": {...}
 * }
 */

// ── Colour helpers ─────────────────────────────────────────────────────────────
// λ thresholds — ~2× and 3× today's league avg (~0.048)
const lambdaColor = (λ) => {
  if (λ >= 0.10) return 'var(--yellow)'
  if (λ >= 0.07) return 'var(--accent)'
  if (λ >= 0.05) return 'var(--green)'
  return 'var(--silver-dim)'
}

const rankColor = (i) =>
  i === 0 ? '#FFD700' : i === 1 ? '#C0C0C0' : i === 2 ? '#CD7F32' : 'var(--silver-dim)'

// ── CSV download ──────────────────────────────────────────────────────────────
function downloadCSV(rows, dateStr) {
  const headers = [
    'Rank','Player','Pos','Team','Game','Time','Opp Team','Opp SP',
    'Park','Park HR Factor','Altitude (ft)',
    'λ Poisson','P(HR) Binary',
    '15G HR/PA','60G HR/PA','15G SLG','60G SLG','60G HR Count',
    'Barrel%','Exit Velo','xSLG',
    'SP ERA','SP WHIP',
    'Home','Bat Hand','Platoon Adv','Temp (°F)','Wind (mph)','Wind Out',
  ]
  const escape = v => {
    const s = v == null ? '' : String(v)
    return s.includes(',') || s.includes('"') || s.includes('\n')
      ? `"${s.replace(/"/g, '""')}"` : s
  }
  const csvRows = [
    headers.join(','),
    ...rows.map(p => [
      p.rank, p.player, p.position, p.team, p.game, p.game_time,
      p.opp_abbr, p.opp_sp, p.park, p.park_hr_factor, p.park_altitude_ft,
      p.lambda_poisson, p.prob_binary,
      p.roll15_hr_pa, p.roll60_hr_pa, p.roll15_slg, p.roll60_slg, p.roll60_hr_count,
      p.sc_barrel_pct, p.sc_exit_velo, p.sc_xslg,
      p.sp_era, p.sp_whip,
      p.is_home ? 'Yes' : 'No', p.bat_hand, p.platoon_adv ? 'Yes' : 'No',
      p.weather_temp_f, p.weather_wind_mph, p.weather_wind_out,
    ].map(escape).join(',')),
  ]
  const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `ml_hr_picks_${(dateStr ?? 'today').replace(/-/g, '')}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 100)
}

// ── Lambda bar (primary metric display) ───────────────────────────────────────
function LambdaBar({ value, avgLambda }) {
  if (value == null) return <span style={{ color: 'var(--silver-dim)' }}>—</span>
  const color = lambdaColor(value)
  // Scale bar so 3× avg = full width
  const max   = Math.max((avgLambda ?? 0.048) * 3, value * 1.1)
  const width = Math.min((value / max) * 100, 100).toFixed(1)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 90 }}>
      <span style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 18, fontWeight: 700, color, lineHeight: 1 }}>
        {value.toFixed(4)}
      </span>
      <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 8, color: 'var(--silver-dim)' }}>λ Poisson</div>
      <div style={{ height: 3, background: 'var(--navy-border)', borderRadius: 2 }}>
        <div style={{ height: '100%', width: `${width}%`, background: color, borderRadius: 2, transition: 'width 0.4s ease' }} />
      </div>
    </div>
  )
}

// ── Mini stat chip ─────────────────────────────────────────────────────────────
function StatChip({ label, value, color }) {
  return (
    <div style={{ textAlign: 'center', minWidth: 46 }}>
      <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 8, color: 'var(--silver-dim)', letterSpacing: '1px', textTransform: 'uppercase', marginBottom: 2 }}>{label}</div>
      <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: color || 'var(--white)', fontWeight: 600 }}>
        {value != null ? value : '—'}
      </div>
    </div>
  )
}

function StatRow({ label, value }) {
  if (value == null || value === '—') return null
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 3 }}>
      <span style={{ color: 'var(--silver-dim)', fontSize: 11 }}>{label}</span>
      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: 'var(--white)' }}>{value}</span>
    </div>
  )
}

function MiniBar({ value, max = 1, color }) {
  const pct = Math.min((value ?? 0) / max * 100, 100)
  return (
    <div style={{ flex: 1, height: 3, background: 'var(--navy-border)', borderRadius: 2 }}>
      <div style={{ height: '100%', width: `${pct}%`, background: color || lambdaColor(value ?? 0), borderRadius: 2 }} />
    </div>
  )
}

// ── Wind indicator ────────────────────────────────────────────────────────────
function WindBadge({ windOut }) {
  if (windOut == null) return null
  if (Math.abs(windOut) < 2) return <span style={{ color: 'var(--silver-dim)', fontSize: 10 }}>calm</span>
  const out   = windOut > 0
  const color = out ? 'var(--green)' : 'var(--red, #e05454)'
  const arrow = out ? '↑ out' : '↓ in'
  return (
    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color, fontWeight: 600 }}>
      {arrow} {Math.abs(windOut).toFixed(1)} mph
    </span>
  )
}

// ── Summary panel ─────────────────────────────────────────────────────────────
function SummaryPanel({ title, total, hr_count, hit_rate_pct, by_bucket }) {
  const hasData = total > 0
  return (
    <div style={{ background: 'var(--navy)', border: '1px solid var(--navy-border)', borderRadius: 6, padding: '14px 18px', flex: '1 1 200px' }}>
      <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 8 }}>{title}</div>
      {hasData ? (
        <>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 10 }}>
            <span style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 28, fontWeight: 700, color: 'var(--yellow)' }}>{hr_count}</span>
            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: 'var(--silver-dim)' }}>/ {total} hit HRs</span>
            <span style={{ marginLeft: 'auto', fontFamily: "'DM Mono', monospace", fontSize: 13, color: 'var(--accent)' }}>{hit_rate_pct}%</span>
          </div>
          {by_bucket && Object.entries(by_bucket).map(([bucket, s]) => (
            <div key={bucket} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 8, color: 'var(--silver-dim)', minWidth: 70 }}>{bucket}</span>
              <MiniBar value={s.rate_pct} max={100} color="var(--yellow)" />
              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', minWidth: 32, textAlign: 'right' }}>{s.rate_pct}%</span>
            </div>
          ))}
        </>
      ) : (
        <div style={{ color: 'var(--silver-dim)', fontSize: 12, paddingTop: 4 }}>No graded picks yet</div>
      )}
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function MlHr() {
  const [fullData,   setFullData]   = useState(null)
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(null)
  const [expanded,   setExpanded]   = useState(null)
  const [sortCol,    setSortCol]    = useState('lambda_poisson')
  const [sortAsc,    setSortAsc]    = useState(false)
  const [gameFilter, setGameFilter] = useState('all')
  const [minLambda,  setMinLambda]  = useState(0)

  useEffect(() => {
    fetch('/data/hitters-ml-hr.json')
      .then(r => {
        if (!r.ok) throw new Error(`Could not load hitters-ml-hr.json (${r.status})`)
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
  const avgLambda = fullData?.avg_lambda  ?? null

  const allGames = [...new Set(preds.map(p => p.game))].sort()

  const filtered = [...preds]
    .filter(p => (p.lambda_poisson ?? 0) >= minLambda)
    .filter(p => gameFilter === 'all' || p.game === gameFilter)
    .sort((a, b) => {
      let av = a[sortCol] ?? '', bv = b[sortCol] ?? ''
      if (typeof av === 'string') { av = av.toLowerCase(); bv = bv.toLowerCase() }
      if (av === bv) return (a.rank ?? 0) - (b.rank ?? 0)
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

  const fixedTh = label => (
    <th style={{
      padding: '9px 14px', fontFamily: "'DM Mono', monospace", fontSize: 9,
      letterSpacing: '2px', textTransform: 'uppercase',
      color: 'var(--silver-dim)', background: 'var(--navy)',
      borderBottom: '1px solid var(--navy-border)',
    }}>{label}</th>
  )

  return (
    <Layout title="ML HR Model">

      {/* ── Page header ──────────────────────────────────────────────────── */}
      <div style={{ marginBottom: '2rem', borderLeft: '3px solid var(--yellow)', paddingLeft: '1.25rem' }}>
        <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--yellow)', letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 8 }}>
          Hitters → ML HR Model
        </div>
        <h1 style={{ fontFamily: "'Barlow Condensed', sans-serif", fontWeight: 900, fontSize: '2.4rem', color: 'var(--white)', lineHeight: 1.1, marginBottom: 8 }}>
          ML HOME RUN MODEL
        </h1>
        <p style={{ fontSize: 13.5, color: 'var(--silver)', maxWidth: 660, lineHeight: 1.65 }}>
          <span style={{ color: 'var(--white)' }}>Poisson XGBoost</span> trained on 2017–2023 box scores,
          evaluated on the 2024 hold-out season. Ranked by Poisson{' '}
          <span style={{ color: 'var(--white)' }}>λ (expected HR rate)</span> — statistically principled
          for rare count outcomes at ~4–6% base rate. Features: rolling 15G &amp; 60G HR power metrics,
          Statcast barrel%/exit velo, opposing SP stats, park altitude and HR factor, and weather.
          Updated daily at 9 AM ET.
        </p>
        {(updatedStr || avgLambda) && (
          <div style={{ marginTop: 10, display: 'flex', gap: 16, flexWrap: 'wrap', fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--silver-dim)' }}>
            {updatedStr && <span>Last updated: {updatedStr}{gameDate && ` · Slate: ${gameDate}`}</span>}
            {avgLambda && <span style={{ color: 'var(--silver)' }}>Today avg λ: {avgLambda.toFixed(5)}</span>}
          </div>
        )}
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: '80px 20px', color: 'var(--silver-dim)', fontFamily: "'DM Mono', monospace", fontSize: 12 }}>
          Loading predictions…
        </div>
      )}
      {error && (
        <div style={{ padding: '16px 20px', background: 'rgba(224,84,84,0.08)', border: '1px solid var(--red)', borderRadius: 6, color: 'var(--red)', fontSize: 13, marginBottom: 24 }}>
          ⚠ {error}
        </div>
      )}

      {!loading && !error && fullData && (
        <>
          {/* ── Filter bar ───────────────────────────────────────────────── */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--silver-dim)' }}>Min λ</span>
              <select value={minLambda} onChange={e => setMinLambda(+e.target.value)} style={{
                fontFamily: "'DM Mono', monospace", fontSize: 12,
                background: 'var(--navy)', color: 'var(--white)',
                border: '1px solid var(--navy-border)', padding: '5px 9px',
                cursor: 'pointer', borderRadius: 3,
              }}>
                {[['0','Any'],['0.05','0.05+'],['0.07','0.07+'],['0.10','0.10+']].map(([v,l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </select>
            </div>

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
                {filtered.length} batters · click row to expand
              </span>
              <button
                onClick={() => downloadCSV(filtered, gameDate)}
                disabled={filtered.length === 0}
                style={{
                  background: 'transparent', border: '1px solid var(--yellow)',
                  borderRadius: 4, color: 'var(--yellow)', fontSize: 11, fontWeight: 700,
                  fontFamily: "'Barlow Condensed', sans-serif", letterSpacing: 1,
                  textTransform: 'uppercase', padding: '5px 12px',
                  cursor: filtered.length === 0 ? 'not-allowed' : 'pointer',
                  opacity: filtered.length === 0 ? 0.4 : 1,
                  transition: 'background 0.15s, color 0.15s',
                }}
                onMouseEnter={e => { if (filtered.length > 0) { e.currentTarget.style.background = 'var(--yellow)'; e.currentTarget.style.color = '#000' }}}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--yellow)' }}
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
                    <th style={{ padding: '9px 14px', width: 36, textAlign: 'center', fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--silver-dim)', background: 'var(--navy)', borderBottom: '1px solid var(--navy-border)' }}>#</th>
                    <Th col="player"          label="Batter"         />
                    <Th col="game"            label="Matchup"        />
                    <Th col="opp_sp"          label="Opp SP"         />
                    {fixedTh('Power')}
                    {fixedTh('Park / Weather')}
                    <Th col="lambda_poisson"  label="λ Poisson"      />
                    <Th col="prob_binary"     label="P(HR) Binary"   />
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((p, i) => {
                    const isExp = expanded === i
                    return [
                      <tr
                        key={`r${i}`}
                        onClick={() => setExpanded(isExp ? null : i)}
                        style={{ cursor: 'pointer', background: isExp ? 'var(--navy-hover)' : 'transparent', transition: 'background 0.1s' }}
                        onMouseEnter={e => { if (!isExp) e.currentTarget.style.background = 'var(--navy)' }}
                        onMouseLeave={e => { e.currentTarget.style.background = isExp ? 'var(--navy-hover)' : 'transparent' }}
                      >
                        {/* Rank */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)', textAlign: 'center', fontFamily: "'Barlow Condensed', sans-serif", fontSize: 16, fontWeight: 700, color: rankColor(i) }}>
                          {p.rank ?? i + 1}
                        </td>
                        {/* Batter */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <div style={{ fontWeight: 600, color: 'var(--white)', fontSize: 14 }}>{p.player}</div>
                          <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', letterSpacing: '2px', textTransform: 'uppercase', marginTop: 2 }}>
                            {p.team} · {p.position} · {p.is_home ? 'HOME' : 'AWAY'}
                            {p.platoon_adv ? <span style={{ color: 'var(--green)', marginLeft: 4 }}>PLATOON</span> : null}
                          </div>
                        </td>
                        {/* Matchup */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)', minWidth: 110 }}>
                          <div style={{ fontSize: 12, color: 'var(--silver)' }}>{p.game}</div>
                          <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', marginTop: 2 }}>{p.game_time}</div>
                        </td>
                        {/* Opp SP */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)', minWidth: 120 }}>
                          <div style={{ fontSize: 12, color: p.opp_sp === 'TBD' ? 'var(--silver-dim)' : 'var(--white)', fontStyle: p.opp_sp === 'TBD' ? 'italic' : 'normal' }}>
                            {p.opp_sp || 'TBD'}
                          </div>
                          {p.sp_era != null && (
                            <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', marginTop: 2 }}>
                              ERA {p.sp_era?.toFixed(2)} · WHIP {p.sp_whip?.toFixed(2)}
                            </div>
                          )}
                        </td>
                        {/* Power stats */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <div style={{ display: 'flex', gap: 10 }}>
                            <StatChip label="60G HR/PA" value={p.roll60_hr_pa != null ? p.roll60_hr_pa.toFixed(4) : null} color="var(--yellow)" />
                            <StatChip label="60G SLG"   value={p.roll60_slg   != null ? p.roll60_slg.toFixed(3)   : null} color="var(--accent)" />
                            {p.sc_barrel_pct != null && (
                              <StatChip label="Brl%" value={`${p.sc_barrel_pct}%`} color="var(--silver)" />
                            )}
                          </div>
                        </td>
                        {/* Park / weather */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: 'var(--white)' }}>
                            {p.park_abbr}
                            <span style={{ color: lambdaColor(p.park_hr_factor > 1.10 ? 0.10 : p.park_hr_factor > 1.0 ? 0.07 : 0.03), marginLeft: 5 }}>
                              ×{p.park_hr_factor?.toFixed(2)}
                            </span>
                          </div>
                          <div style={{ marginTop: 2 }}>
                            <WindBadge windOut={p.weather_wind_out} />
                            {p.weather_temp_f != null && (
                              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', marginLeft: 6 }}>
                                {p.weather_temp_f}°F
                              </span>
                            )}
                          </div>
                        </td>
                        {/* Lambda */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <LambdaBar value={p.lambda_poisson} avgLambda={avgLambda} />
                        </td>
                        {/* Binary prob */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 13, color: lambdaColor(p.prob_binary ?? 0), fontWeight: 600 }}>
                            {p.prob_binary != null ? (p.prob_binary * 100).toFixed(1) + '%' : '—'}
                          </div>
                        </td>
                      </tr>,

                      /* ── Expanded detail ── */
                      isExp && (
                        <tr key={`e${i}`}>
                          <td colSpan={8} style={{ background: 'var(--navy)', borderBottom: '1px solid var(--navy-border)', padding: '16px 20px' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16 }}>

                              {/* Models */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--yellow)', marginBottom: 8 }}>Model Output</div>
                                {[
                                  { label: 'λ Poisson (primary)', val: p.lambda_poisson, fmt: v => v.toFixed(5) },
                                  { label: 'P(HR) Binary',        val: p.prob_binary,    fmt: v => (v*100).toFixed(2) + '%' },
                                ].map(f => (
                                  <div key={f.label} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', minWidth: 110 }}>{f.label}</span>
                                    <MiniBar value={f.val} max={Math.max((avgLambda ?? 0.05) * 3, 0.15)} color={lambdaColor(f.val ?? 0)} />
                                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: lambdaColor(f.val ?? 0), minWidth: 50, textAlign: 'right' }}>
                                      {f.val != null ? f.fmt(f.val) : '—'}
                                    </span>
                                  </div>
                                ))}
                                {avgLambda && (
                                  <div style={{ marginTop: 6, fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)' }}>
                                    Today avg λ: {avgLambda.toFixed(5)} &nbsp;·&nbsp;
                                    {p.lambda_poisson ? `${(p.lambda_poisson / avgLambda).toFixed(1)}× avg` : ''}
                                  </div>
                                )}
                              </div>

                              {/* Rolling power */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--yellow)', marginBottom: 8 }}>Rolling Power</div>
                                <StatRow label="15G HR/PA"    value={p.roll15_hr_pa != null ? p.roll15_hr_pa.toFixed(4) : null} />
                                <StatRow label="60G HR/PA"    value={p.roll60_hr_pa != null ? p.roll60_hr_pa.toFixed(4) : null} />
                                <StatRow label="15G SLG"      value={p.roll15_slg   != null ? p.roll15_slg.toFixed(3)   : null} />
                                <StatRow label="60G SLG"      value={p.roll60_slg   != null ? p.roll60_slg.toFixed(3)   : null} />
                                <StatRow label="60G HR count" value={p.roll60_hr_count} />
                              </div>

                              {/* Statcast */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--yellow)', marginBottom: 8 }}>Statcast</div>
                                <StatRow label="Barrel%"   value={p.sc_barrel_pct != null ? `${p.sc_barrel_pct}%` : null} />
                                <StatRow label="Exit Velo" value={p.sc_exit_velo  != null ? `${p.sc_exit_velo} mph` : null} />
                                <StatRow label="xSLG"      value={p.sc_xslg       != null ? p.sc_xslg.toFixed(3) : null} />
                                <div style={{ marginTop: 8, fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)' }}>
                                  Season averages from Baseball Savant
                                </div>
                              </div>

                              {/* Pitcher */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--yellow)', marginBottom: 8 }}>Opposing Starter</div>
                                <div style={{ fontWeight: 600, color: 'var(--white)', marginBottom: 6, fontSize: 13 }}>
                                  {p.opp_sp && p.opp_sp !== 'TBD'
                                    ? p.opp_sp
                                    : <span style={{ color: 'var(--silver-dim)', fontStyle: 'italic' }}>TBD — league avg used</span>}
                                </div>
                                <StatRow label="ERA"   value={p.sp_era  != null ? p.sp_era.toFixed(2)  : null} />
                                <StatRow label="WHIP"  value={p.sp_whip != null ? p.sp_whip.toFixed(2) : null} />
                                <StatRow label="Team"  value={p.opp_abbr} />
                              </div>

                              {/* Park & weather */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--yellow)', marginBottom: 8 }}>Park & Weather</div>
                                <StatRow label="Park"       value={p.park} />
                                <StatRow label="HR Factor"  value={p.park_hr_factor != null ? `×${p.park_hr_factor.toFixed(2)}` : null} />
                                <StatRow label="Altitude"   value={p.park_altitude_ft != null ? `${p.park_altitude_ft.toLocaleString()} ft` : null} />
                                <StatRow label="Temp"       value={p.weather_temp_f   != null ? `${p.weather_temp_f}°F`    : null} />
                                <StatRow label="Wind"       value={p.weather_wind_mph != null ? `${p.weather_wind_mph} mph` : null} />
                                {p.weather_wind_out != null && (
                                  <div style={{ marginTop: 4 }}>
                                    <WindBadge windOut={p.weather_wind_out} />
                                  </div>
                                )}
                              </div>

                              {/* Context */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--yellow)', marginBottom: 8 }}>Context</div>
                                <StatRow label="Home/Away"   value={p.is_home ? 'Home' : 'Away'} />
                                <StatRow label="Bat hand"    value={p.bat_hand === 'L' ? 'Left' : p.bat_hand === 'R' ? 'Right' : p.bat_hand} />
                                <StatRow label="Platoon adv" value={p.platoon_adv ? 'Yes' : 'No'} />
                                <div style={{ marginTop: 10, padding: '6px 8px', background: 'var(--navy-dark)', borderRadius: 3, fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', lineHeight: 1.65 }}>
                                  Train: 2017–2023<br/>
                                  Hold-out: 2024<br/>
                                  Objective: count:poisson<br/>
                                  MIN_PA: 100
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

          {/* ── Tracking + model notes ────────────────────────────────────── */}
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
            <div style={{ background: 'var(--navy)', border: '1px solid var(--navy-border)', borderRadius: 6, padding: '14px 18px', flex: '1 1 200px' }}>
              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 10 }}>Model Reference</div>
              {[
                { label: 'Primary metric', val: 'Poisson λ (HR rate)' },
                { label: 'Secondary',      val: 'Binary XGBoost P(HR)' },
                { label: 'Train',          val: '2017–2023 box scores' },
                { label: 'Hold-out',       val: '2024 full season' },
                { label: 'Min PA',         val: '100 plate appearances' },
                { label: 'Roll windows',   val: '15G short / 60G long' },
                { label: 'Statcast',       val: 'Barrel%, exit velo, xSLG' },
                { label: 'Park',           val: 'HR factor + altitude' },
                { label: 'Weather',        val: 'Temp + wind-out component' },
              ].map(item => (
                <div key={item.label} style={{ marginBottom: 5, display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', textTransform: 'uppercase', letterSpacing: '1px' }}>{item.label}</span>
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--white)', textAlign: 'right' }}>{item.val}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </Layout>
  )
}
