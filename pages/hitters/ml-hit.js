import { useState, useEffect } from 'react'
import Layout from '../../components/Layout'

/*
 * ─── EXPECTED JSON SHAPE (public/data/hitters-ml-hit.json) ──────────────────
 * {
 *   "updated": "2026-04-23T09:00:00Z",
 *   "date": "2026-04-23",
 *   "predictions": [
 *     {
 *       "rank": 1, "player": "Freddie Freeman", "position": "1B",
 *       "team": "LAD", "game": "SF @ LAD", "game_time": "7:10 PM ET",
 *       "opposing_team": "SF", "opp_sp": "Logan Webb",
 *       "p_mlp": 0.823, "p_lr": 0.791, "p_rf": 0.804, "p_ens": 0.806,
 *       "roll7_ba": 0.348, "roll7_ops": 0.981,
 *       "roll30_ba": 0.312, "roll30_ops": 0.921,
 *       "sp_era": 2.89, "sp_whip": 1.05, "is_home": 1,
 *       "actual_hits": null, "correct": null
 *     }, ...
 *   ],
 *   "yesterday": { "date": "...", "total": 25, "hit_count": 19,
 *                  "hit_rate_pct": 76.0, "by_bucket": {...} },
 *   "alltime":   { "total": 200, "hit_count": 152, "hit_rate_pct": 76.0,
 *                  "by_bucket": {...} }
 * }
 */

// ── Colour helpers ─────────────────────────────────────────────────────────────
const probColor = (p) => {
  if (p >= 0.75) return 'var(--green)'
  if (p >= 0.65) return 'var(--accent)'
  if (p >= 0.55) return 'var(--yellow)'
  return 'var(--silver-dim)'
}

const rankColor = (i) =>
  i === 0 ? '#FFD700' : i === 1 ? '#C0C0C0' : i === 2 ? '#CD7F32' : 'var(--silver-dim)'

// ── CSV download ──────────────────────────────────────────────────────────────
function downloadCSV(rows, dateStr) {
  const headers = [
    'Rank','Player','Position','Team','Game','Time','Opp Team','Opp SP',
    'MLP%','LR%','RF%','Ensemble%',
    '7G BA','7G OPS','30G BA','30G OPS',
    'SP ERA','SP WHIP','Home',
  ]
  const escape = v => {
    const s = v == null ? '' : String(v)
    return s.includes(',') || s.includes('"') || s.includes('\n')
      ? `"${s.replace(/"/g, '""')}"` : s
  }
  const fmt = v => v != null ? (v * 100).toFixed(1) + '%' : ''
  const csvRows = [
    headers.join(','),
    ...rows.map(p => [
      p.rank, p.player, p.position, p.team, p.game, p.game_time,
      p.opposing_team, p.opp_sp,
      fmt(p.p_mlp), fmt(p.p_lr), fmt(p.p_rf), fmt(p.p_ens),
      p.roll7_ba, p.roll7_ops, p.roll30_ba, p.roll30_ops,
      p.sp_era, p.sp_whip, p.is_home ? 'Yes' : 'No',
    ].map(escape).join(',')),
  ]
  const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `ml_hit_picks_${(dateStr ?? 'today').replace(/-/g, '')}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 100)
}

// ── Probability bar ────────────────────────────────────────────────────────────
function ProbBar({ value, label }) {
  if (value == null) return <span style={{ color: 'var(--silver-dim)' }}>—</span>
  const pct   = (value * 100).toFixed(1)
  const color = probColor(value)
  const width = Math.min(value / 0.90 * 100, 100).toFixed(1)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 80 }}>
      {label && (
        <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 8, color: 'var(--silver-dim)', letterSpacing: '1.5px', textTransform: 'uppercase' }}>
          {label}
        </span>
      )}
      <span style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 17, fontWeight: 700, color, lineHeight: 1 }}>
        {pct}%
      </span>
      <div style={{ height: 3, background: 'var(--navy-border)', borderRadius: 2 }}>
        <div style={{ height: '100%', width: `${width}%`, background: color, borderRadius: 2, transition: 'width 0.4s ease' }} />
      </div>
    </div>
  )
}

// ── Small model probability pill ──────────────────────────────────────────────
function ModelPill({ label, value }) {
  if (value == null) return null
  const color = probColor(value)
  return (
    <div style={{ textAlign: 'center', minWidth: 44 }}>
      <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 8, color: 'var(--silver-dim)', letterSpacing: '1px', textTransform: 'uppercase', marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color, fontWeight: 600 }}>
        {(value * 100).toFixed(1)}%
      </div>
    </div>
  )
}

// ── Stat row for expanded panel ───────────────────────────────────────────────
function StatRow({ label, value }) {
  if (value == null || value === '—') return null
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 3 }}>
      <span style={{ color: 'var(--silver-dim)', fontSize: 11 }}>{label}</span>
      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: 'var(--white)' }}>{value}</span>
    </div>
  )
}

// ── Mini bar ─────────────────────────────────────────────────────────────────
function MiniBar({ value, max = 1, color }) {
  const pct = Math.min((value ?? 0) / max * 100, 100)
  return (
    <div style={{ flex: 1, height: 3, background: 'var(--navy-border)', borderRadius: 2 }}>
      <div style={{ height: '100%', width: `${pct}%`, background: color || probColor(value ?? 0), borderRadius: 2 }} />
    </div>
  )
}

// ── Yesterday / all-time panel ────────────────────────────────────────────────
function SummaryPanel({ title, total, hit_count, hit_rate_pct, by_bucket }) {
  const hasData = total > 0
  return (
    <div style={{
      background: 'var(--navy)', border: '1px solid var(--navy-border)',
      borderRadius: 6, padding: '14px 18px', flex: '1 1 200px',
    }}>
      <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 8 }}>
        {title}
      </div>
      {hasData ? (
        <>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 10 }}>
            <span style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 28, fontWeight: 700, color: 'var(--green)' }}>{hit_count}</span>
            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: 'var(--silver-dim)' }}>/ {total} got a hit</span>
            <span style={{ marginLeft: 'auto', fontFamily: "'DM Mono', monospace", fontSize: 13, color: 'var(--accent)' }}>{hit_rate_pct}%</span>
          </div>
          {by_bucket && Object.entries(by_bucket).map(([bucket, s]) => (
            <div key={bucket} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', minWidth: 44 }}>{bucket}</span>
              <MiniBar value={s.rate_pct} max={100} color="var(--green)" />
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
export default function MlHit() {
  const [fullData,   setFullData]   = useState(null)
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(null)
  const [expanded,   setExpanded]   = useState(null)
  const [sortCol,    setSortCol]    = useState('p_mlp')
  const [sortAsc,    setSortAsc]    = useState(false)
  const [gameFilter, setGameFilter] = useState('all')
  const [minProb,    setMinProb]    = useState(0)

  useEffect(() => {
    fetch('/data/hitters-ml-hit.json')
      .then(r => {
        if (!r.ok) throw new Error(`Could not load hitters-ml-hit.json (${r.status})`)
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
    .filter(p => (p.p_mlp ?? 0) >= minProb)
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
      color: sortCol === col ? 'var(--green)' : 'var(--silver-dim)',
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
    <Layout title="ML Hit Model">

      {/* ── Page header ──────────────────────────────────────────────────── */}
      <div style={{ marginBottom: '2rem', borderLeft: '3px solid var(--green)', paddingLeft: '1.25rem' }}>
        <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--green)', letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 8 }}>
          Hitters → ML Hit Model
        </div>
        <h1 style={{ fontFamily: "'Barlow Condensed', sans-serif", fontWeight: 900, fontSize: '2.4rem', color: 'var(--white)', lineHeight: 1.1, marginBottom: 8 }}>
          ML HIT MODEL
        </h1>
        <p style={{ fontSize: 13.5, color: 'var(--silver)', maxWidth: 640, lineHeight: 1.65 }}>
          Ensemble of <span style={{ color: 'var(--white)' }}>MLP</span>,{' '}
          <span style={{ color: 'var(--white)' }}>Logistic Regression</span>, and{' '}
          <span style={{ color: 'var(--white)' }}>Random Forest</span> trained on 2022–2024 box scores,
          based on Alceo &amp; Henriques (2020). Features include 7-game and 30-game rolling batting stats
          vs opposing starter ERA/WHIP. Sorted by MLP probability — the paper's best model.
          Updated daily at 9 AM ET.
        </p>
        {updatedStr && (
          <div style={{ marginTop: 10, fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--silver-dim)' }}>
            Last updated: {updatedStr}{gameDate && ` · Slate: ${gameDate}`}
          </div>
        )}
      </div>

      {/* ── Loading / error ──────────────────────────────────────────────── */}
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
              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--silver-dim)' }}>
                Min MLP%
              </span>
              <select value={minProb} onChange={e => setMinProb(+e.target.value)} style={{
                fontFamily: "'DM Mono', monospace", fontSize: 12,
                background: 'var(--navy)', color: 'var(--white)',
                border: '1px solid var(--navy-border)', padding: '5px 9px',
                cursor: 'pointer', borderRadius: 3,
              }}>
                {[['0','Any'],['0.55','55%+'],['0.65','65%+'],['0.75','75%+']].map(([v,l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </select>
            </div>

            {allGames.length > 1 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--silver-dim)' }}>
                  Game
                </span>
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
                  background: 'transparent', border: '1px solid var(--green)',
                  borderRadius: 4, color: 'var(--green)', fontSize: 11, fontWeight: 700,
                  fontFamily: "'Barlow Condensed', sans-serif", letterSpacing: 1,
                  textTransform: 'uppercase', padding: '5px 12px',
                  cursor: filtered.length === 0 ? 'not-allowed' : 'pointer',
                  opacity: filtered.length === 0 ? 0.4 : 1,
                  transition: 'background 0.15s, color 0.15s',
                }}
                onMouseEnter={e => { if (filtered.length > 0) { e.currentTarget.style.background = 'var(--green)'; e.currentTarget.style.color = '#000' }}}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--green)' }}
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
                    <Th col="player"   label="Batter"    />
                    <Th col="game"     label="Matchup"   />
                    <Th col="opp_sp"   label="Opp SP"    />
                    {fixedTh('Rolling Stats')}
                    <Th col="p_mlp"    label="MLP%"      />
                    {fixedTh('All Models')}
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
                        {/* Rolling stats */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <div style={{ display: 'flex', gap: 12 }}>
                            <div style={{ textAlign: 'center' }}>
                              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 8, color: 'var(--silver-dim)', letterSpacing: '1px', textTransform: 'uppercase', marginBottom: 2 }}>7G BA</div>
                              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>
                                {p.roll7_ba != null ? p.roll7_ba.toFixed(3) : '—'}
                              </div>
                            </div>
                            <div style={{ textAlign: 'center' }}>
                              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 8, color: 'var(--silver-dim)', letterSpacing: '1px', textTransform: 'uppercase', marginBottom: 2 }}>30G OPS</div>
                              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: 'var(--silver)', fontWeight: 600 }}>
                                {p.roll30_ops != null ? p.roll30_ops.toFixed(3) : '—'}
                              </div>
                            </div>
                          </div>
                        </td>
                        {/* MLP probability */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <ProbBar value={p.p_mlp} />
                        </td>
                        {/* All three models */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <div style={{ display: 'flex', gap: 10 }}>
                            <ModelPill label="LR"  value={p.p_lr} />
                            <ModelPill label="RF"  value={p.p_rf} />
                            <ModelPill label="Ens" value={p.p_ens} />
                          </div>
                        </td>
                      </tr>,

                      /* ── Expanded detail row ── */
                      isExp && (
                        <tr key={`e${i}`}>
                          <td colSpan={7} style={{ background: 'var(--navy)', borderBottom: '1px solid var(--navy-border)', padding: '16px 20px' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 16 }}>

                              {/* Model probabilities */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--green)', marginBottom: 8 }}>Model Probabilities</div>
                                {[
                                  { label: 'MLP (primary)',   val: p.p_mlp },
                                  { label: 'Logistic Reg.',   val: p.p_lr  },
                                  { label: 'Random Forest',   val: p.p_rf  },
                                  { label: 'Ensemble (avg)',  val: p.p_ens },
                                ].map(f => (
                                  <div key={f.label} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', minWidth: 100 }}>{f.label}</span>
                                    <MiniBar value={f.val} max={1} color={probColor(f.val ?? 0)} />
                                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: probColor(f.val ?? 0), minWidth: 40, textAlign: 'right' }}>
                                      {f.val != null ? (f.val * 100).toFixed(1) + '%' : '—'}
                                    </span>
                                  </div>
                                ))}
                              </div>

                              {/* Batter rolling stats */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--green)', marginBottom: 8 }}>Rolling Stats</div>
                                <StatRow label="7G BA"   value={p.roll7_ba  != null ? p.roll7_ba.toFixed(3)  : null} />
                                <StatRow label="7G OPS"  value={p.roll7_ops != null ? p.roll7_ops.toFixed(3) : null} />
                                <StatRow label="30G BA"  value={p.roll30_ba  != null ? p.roll30_ba.toFixed(3)  : null} />
                                <StatRow label="30G OPS" value={p.roll30_ops != null ? p.roll30_ops.toFixed(3) : null} />
                                <StatRow label="Home/Away" value={p.is_home ? 'Home' : 'Away'} />
                              </div>

                              {/* Opposing pitcher */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--green)', marginBottom: 8 }}>Opposing Starter</div>
                                <div style={{ fontWeight: 600, color: 'var(--white)', marginBottom: 6 }}>
                                  {p.opp_sp && p.opp_sp !== 'TBD'
                                    ? p.opp_sp
                                    : <span style={{ color: 'var(--silver-dim)', fontStyle: 'italic' }}>TBD — league avg used</span>
                                  }
                                </div>
                                <StatRow label="ERA"   value={p.sp_era  != null ? p.sp_era.toFixed(2)  : null} />
                                <StatRow label="WHIP"  value={p.sp_whip != null ? p.sp_whip.toFixed(2) : null} />
                                <StatRow label="Team"  value={p.opposing_team} />
                              </div>

                              {/* Model notes */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--green)', marginBottom: 8 }}>Model Notes</div>
                                <div style={{ padding: '8px 10px', background: 'var(--navy-dark)', borderRadius: 3, fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', lineHeight: 1.7 }}>
                                  Train: 2022–2024 box scores<br/>
                                  Test: 2025 full season<br/>
                                  Features: 7G + 30G rolling BA/<br/>
                                  OBP/SLG/OPS + SP ERA/WHIP<br/>
                                  Balance: random under-sampling<br/>
                                  Min PA: 50 · Sort: MLP prob
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
              hit_count={yesterday.hit_count || 0}
              hit_rate_pct={yesterday.hit_rate_pct || 0}
              by_bucket={yesterday.by_bucket}
            />
            <SummaryPanel
              title="All-Time"
              total={alltime.total || 0}
              hit_count={alltime.hit_count || 0}
              hit_rate_pct={alltime.hit_rate_pct || 0}
              by_bucket={alltime.by_bucket}
            />
            {/* Model reference */}
            <div style={{ background: 'var(--navy)', border: '1px solid var(--navy-border)', borderRadius: 6, padding: '14px 18px', flex: '1 1 200px' }}>
              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 10 }}>Model Reference</div>
              {[
                { label: 'Primary sort',  val: 'MLP probability' },
                { label: 'Ensemble',      val: 'Avg(MLP, LR, RF)' },
                { label: 'Train seasons', val: '2022 · 2023 · 2024' },
                { label: 'Hold-out',      val: '2025 full season' },
                { label: 'Min PA',        val: '50 plate appearances' },
                { label: 'Balance',       val: 'Random under-sampling' },
                { label: 'Reference',     val: 'Alceo & Henriques 2020' },
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
