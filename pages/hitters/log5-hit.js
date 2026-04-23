import { useState, useEffect } from 'react'
import Layout from '../../components/Layout'

/*
 * ─── EXPECTED JSON SHAPE (public/data/hitters-log5-hit.json) ─────────────────
 * {
 *   "updated": "2026-04-23T09:00:00Z",
 *   "date": "2026-04-23",
 *   "league_avg_xba": 0.2534,
 *   "predictions": [
 *     {
 *       "rank": 1,
 *       "player": "Freddie Freeman",
 *       "team": "LAD",
 *       "game": "SF @ LAD",
 *       "game_time": "7:10 PM ET",
 *       "opposing_team": "SF",
 *       "opposing_sp_name": "Logan Webb",
 *       "sp_xbaa_source": "sp",          ← "sp" | "team_overall"
 *       "batter_xba": 0.312,
 *       "sp_xbaa": 0.218,
 *       "bullpen_xbaa": 0.245,
 *       "vs_sp_log5": 0.298,
 *       "vs_bullpen_log5": 0.271,
 *       "hit_probability": 0.678,
 *       "games_played": 18,
 *       "team_games": 20,
 *       "at_bats": 70,
 *       "ab_per_game": 3.89,
 *       "sp_abs": 2.0,
 *       "bp_abs": 1.89,
 *       "league_avg_xba": 0.2534,
 *       "actual_hits": null,
 *       "correct": null
 *     }, ...
 *   ],
 *   "yesterday": { "date": "...", "total": 25, "hit_count": 18,
 *                  "hit_rate_pct": 72.0, "by_bucket": {...} },
 *   "alltime":   { "total": 200, "hit_count": 144, "hit_rate_pct": 72.0, "by_bucket": {...} }
 * }
 */

// ── Colour helpers ─────────────────────────────────────────────────────────────
const probColor = (p) => {
  if (p >= 0.70) return 'var(--green)'
  if (p >= 0.55) return 'var(--accent)'
  if (p >= 0.40) return 'var(--yellow)'
  return 'var(--silver-dim)'
}

const rankColor = (i) =>
  i === 0 ? '#FFD700' : i === 1 ? '#C0C0C0' : i === 2 ? '#CD7F32' : 'var(--silver-dim)'

// ── CSV download ──────────────────────────────────────────────────────────────
function downloadCSV(rows, dateStr, leagueAvg) {
  const headers = [
    'Rank', 'Player', 'Team', 'Game', 'Time', 'Opposing Team', 'Opposing SP',
    'SP Source', 'Batter xBA', 'SP xBAA', 'Bullpen xBAA',
    'vs SP Log5', 'vs Bullpen Log5',
    'Hit Probability', 'SP ABs', 'Bullpen ABs', 'AB/Game',
    'Games Played', 'Team Games', 'League Avg xBA',
  ]
  const escape = v => {
    const s = v == null ? '' : String(v)
    return s.includes(',') || s.includes('"') || s.includes('\n')
      ? `"${s.replace(/"/g, '""')}"` : s
  }
  const csvRows = [
    headers.join(','),
    ...rows.map(p => [
      p.rank, p.player, p.team, p.game, p.game_time,
      p.opposing_team, p.opposing_sp_name, p.sp_xbaa_source,
      p.batter_xba, p.sp_xbaa, p.bullpen_xbaa,
      p.vs_sp_log5, p.vs_bullpen_log5,
      p.hit_probability, p.sp_abs, p.bp_abs, p.ab_per_game,
      p.games_played, p.team_games, leagueAvg,
    ].map(escape).join(',')),
  ]
  const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `log5_hit_picks_${(dateStr ?? 'today').replace(/-/g, '')}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 100)
}

// ── Probability bar cell ───────────────────────────────────────────────────────
function ProbBar({ value }) {
  if (value == null) return <span style={{ color: 'var(--silver-dim)' }}>—</span>
  const pct   = (value * 100).toFixed(1)
  const color = probColor(value)
  const width = Math.min(value / 0.85 * 100, 100).toFixed(1)  // 85% = full bar
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 80 }}>
      <span style={{
        fontFamily: "'Barlow Condensed', sans-serif",
        fontSize: 17, fontWeight: 700, color, lineHeight: 1,
      }}>{pct}%</span>
      <div style={{ height: 3, background: 'var(--navy-border)', borderRadius: 2 }}>
        <div style={{
          height: '100%', width: `${width}%`,
          background: color, borderRadius: 2,
          transition: 'width 0.4s ease',
        }} />
      </div>
    </div>
  )
}

// ── xBA stat chip ──────────────────────────────────────────────────────────────
function XbaStat({ label, value, color }) {
  return (
    <div style={{ textAlign: 'center', minWidth: 52 }}>
      <div style={{
        fontFamily: "'DM Mono', monospace", fontSize: 8,
        color: 'var(--silver-dim)', letterSpacing: '1.5px',
        textTransform: 'uppercase', marginBottom: 2,
      }}>{label}</div>
      <div style={{
        fontFamily: "'DM Mono', monospace", fontSize: 12,
        color: color || 'var(--white)', fontWeight: 600,
      }}>
        {value != null ? value.toFixed(3) : '—'}
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
      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: 'var(--white)' }}>
        {value}
      </span>
    </div>
  )
}

// ── Mini bar (for expanded breakdown) ────────────────────────────────────────
function MiniBar({ value, max = 1, color }) {
  const pct = Math.min((value ?? 0) / max * 100, 100)
  return (
    <div style={{ flex: 1, height: 3, background: 'var(--navy-border)', borderRadius: 2 }}>
      <div style={{
        height: '100%', width: `${pct}%`,
        background: color || probColor(value ?? 0), borderRadius: 2,
      }} />
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
      <div style={{
        fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)',
        letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 8,
      }}>{title}</div>
      {hasData ? (
        <>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 10 }}>
            <span style={{
              fontFamily: "'Barlow Condensed', sans-serif",
              fontSize: 28, fontWeight: 700, color: 'var(--green)',
            }}>{hit_count}</span>
            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: 'var(--silver-dim)' }}>
              / {total} got a hit
            </span>
            <span style={{ marginLeft: 'auto', fontFamily: "'DM Mono', monospace", fontSize: 13, color: 'var(--accent)' }}>
              {hit_rate_pct}%
            </span>
          </div>
          {by_bucket && Object.entries(by_bucket).map(([bucket, s]) => (
            <div key={bucket} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', minWidth: 40 }}>
                {bucket}
              </span>
              <MiniBar value={s.rate_pct} max={100} color="var(--green)" />
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

// ── Main page ──────────────────────────────────────────────────────────────────
export default function Log5Hit() {
  const [fullData,   setFullData]   = useState(null)
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(null)
  const [expanded,   setExpanded]   = useState(null)
  const [sortCol,    setSortCol]    = useState('hit_probability')
  const [sortAsc,    setSortAsc]    = useState(false)
  const [gameFilter, setGameFilter] = useState('all')
  const [minProb,    setMinProb]    = useState(0)

  useEffect(() => {
    fetch('/data/hitters-log5-hit.json')
      .then(r => {
        if (!r.ok) throw new Error(`Could not load hitters-log5-hit.json (${r.status})`)
        return r.json()
      })
      .then(json => { setFullData(json); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  const preds      = fullData?.predictions  ?? []
  const yesterday  = fullData?.yesterday    ?? {}
  const alltime    = fullData?.alltime      ?? {}
  const updated    = fullData?.updated      ?? null
  const gameDate   = fullData?.date         ?? null
  const leagueAvg  = fullData?.league_avg_xba ?? null

  const allGames = [...new Set(preds.map(p => p.game))].sort()

  const filtered = [...preds]
    .filter(p => (p.hit_probability ?? 0) >= minProb)
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
      color: sortCol === col ? 'var(--accent)' : 'var(--silver-dim)',
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
    <Layout title="Log5 Hit Model">

      {/* ── Page header ──────────────────────────────────────────────────── */}
      <div style={{ marginBottom: '2rem', borderLeft: '3px solid var(--accent)', paddingLeft: '1.25rem' }}>
        <div style={{
          fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--accent)',
          letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 8,
        }}>Hitters → Log5 Hit</div>
        <h1 style={{
          fontFamily: "'Barlow Condensed', sans-serif", fontWeight: 900,
          fontSize: '2.4rem', color: 'var(--white)', lineHeight: 1.1, marginBottom: 8,
        }}>LOG5 HIT MODEL</h1>
        <p style={{ fontSize: 13.5, color: 'var(--silver)', maxWidth: 620, lineHeight: 1.65 }}>
          P(≥1 hit today) using the Bill James Log5 formula applied to Statcast{' '}
          <span style={{ color: 'var(--white)' }}>expected batting average (xBA)</span>.
          First 2 expected ABs are scored vs the opposing starter's xBAA;
          remaining ABs use the opposing bullpen's xBAA.
          League average xBA is computed live each day from all qualified batters.
        </p>
        {(updatedStr || leagueAvg) && (
          <div style={{ marginTop: 10, display: 'flex', gap: 16, flexWrap: 'wrap', fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--silver-dim)' }}>
            {updatedStr && <span>Last updated: {updatedStr}{gameDate && ` · Slate: ${gameDate}`}</span>}
            {leagueAvg && (
              <span style={{ color: 'var(--accent)' }}>
                League avg xBA today: {leagueAvg.toFixed(4)}
              </span>
            )}
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
        <div style={{
          padding: '16px 20px', background: 'rgba(224,84,84,0.08)',
          border: '1px solid var(--red)', borderRadius: 6,
          color: 'var(--red)', fontSize: 13, marginBottom: 24,
        }}>⚠ {error}</div>
      )}

      {!loading && !error && fullData && (
        <>
          {/* ── Filter bar ───────────────────────────────────────────────── */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
            {[
              {
                label: 'Min Prob', value: minProb, setter: v => setMinProb(+v),
                options: [['0','Any'],['0.5','50%+'],['0.6','60%+'],['0.7','70%+']],
              },
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
                {filtered.length} batters · click row to expand
              </span>
              <button
                onClick={() => downloadCSV(filtered, gameDate, leagueAvg)}
                disabled={filtered.length === 0}
                style={{
                  background: 'transparent', border: '1px solid var(--accent)',
                  borderRadius: 4, color: 'var(--accent)', fontSize: 11, fontWeight: 700,
                  fontFamily: "'Barlow Condensed', sans-serif", letterSpacing: 1,
                  textTransform: 'uppercase', padding: '5px 12px',
                  cursor: filtered.length === 0 ? 'not-allowed' : 'pointer',
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
                    <Th col="player"          label="Batter"    />
                    <Th col="game"            label="Matchup"   />
                    <Th col="opposing_sp_name" label="Opp SP"   />
                    {fixedTh('xBA / xBAA')}
                    <Th col="hit_probability" label="Hit Prob"  />
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
                        <td style={{
                          padding: '11px 14px', borderBottom: '1px solid var(--navy-border)',
                          textAlign: 'center',
                          fontFamily: "'Barlow Condensed', sans-serif", fontSize: 16, fontWeight: 700,
                          color: rankColor(i),
                        }}>
                          {p.rank ?? i + 1}
                        </td>

                        {/* Batter */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <div style={{ fontWeight: 600, color: 'var(--white)', fontSize: 14 }}>{p.player}</div>
                          <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', letterSpacing: '2px', textTransform: 'uppercase', marginTop: 2 }}>
                            {p.team}
                          </div>
                        </td>

                        {/* Matchup */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)', minWidth: 120 }}>
                          <div style={{ fontSize: 12, color: 'var(--silver)' }}>{p.game}</div>
                          <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', marginTop: 2 }}>
                            {p.game_time}
                          </div>
                        </td>

                        {/* Opposing SP */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)', minWidth: 130 }}>
                          <div style={{ fontSize: 12, color: p.opposing_sp_name === 'TBD' ? 'var(--silver-dim)' : 'var(--white)', fontStyle: p.opposing_sp_name === 'TBD' ? 'italic' : 'normal' }}>
                            {p.opposing_sp_name || 'TBD'}
                          </div>
                          {p.sp_xbaa_source === 'team_overall' && (
                            <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 8, color: 'var(--yellow)', marginTop: 2, letterSpacing: '1px' }}>
                              TEAM AVG USED
                            </div>
                          )}
                        </td>

                        {/* xBA / xBAA stats */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                            <XbaStat label="Bat xBA" value={p.batter_xba} color="var(--accent)" />
                            <XbaStat label="SP xBAA" value={p.sp_xbaa}    color="var(--silver)" />
                            <XbaStat label="BP xBAA" value={p.bullpen_xbaa} color="var(--silver-dim)" />
                          </div>
                        </td>

                        {/* Hit probability */}
                        <td style={{ padding: '11px 14px', borderBottom: '1px solid var(--navy-border)' }}>
                          <ProbBar value={p.hit_probability} />
                        </td>
                      </tr>,

                      /* ── Expanded detail row ── */
                      isExp && (
                        <tr key={`e${i}`}>
                          <td colSpan={6} style={{ background: 'var(--navy)', borderBottom: '1px solid var(--navy-border)', padding: '16px 20px' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16 }}>

                              {/* Log5 matchup */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: 8 }}>
                                  Log5 Results
                                </div>
                                {[
                                  { label: 'vs SP (log5)',      val: p.vs_sp_log5 },
                                  { label: 'vs Bullpen (log5)', val: p.vs_bullpen_log5 },
                                ].map(f => (
                                  <div key={f.label} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', minWidth: 110 }}>{f.label}</span>
                                    <MiniBar value={f.val} max={0.5} color={probColor(f.val ?? 0)} />
                                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: probColor(f.val ?? 0), minWidth: 36, textAlign: 'right' }}>
                                      {f.val != null ? f.val.toFixed(3) : '—'}
                                    </span>
                                  </div>
                                ))}
                                <div style={{ marginTop: 8, paddingTop: 6, borderTop: '1px solid var(--navy-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)' }}>P(≥1 hit)</span>
                                  <span style={{
                                    fontFamily: "'Barlow Condensed', sans-serif", fontSize: 22, fontWeight: 700,
                                    color: probColor(p.hit_probability ?? 0),
                                  }}>
                                    {p.hit_probability != null ? (p.hit_probability * 100).toFixed(1) + '%' : '—'}
                                  </span>
                                </div>
                              </div>

                              {/* AB breakdown */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: 8 }}>
                                  At-Bat Breakdown
                                </div>
                                <StatRow label="AB / game"     value={p.ab_per_game?.toFixed(2)} />
                                <StatRow label="vs SP (ABs)"   value={p.sp_abs?.toFixed(2)} />
                                <StatRow label="vs Bullpen (ABs)" value={p.bp_abs?.toFixed(2)} />
                                <StatRow label="Games played"  value={p.team_games ? `${p.games_played} / ${p.team_games}` : p.games_played} />
                                <StatRow label="Season AB"     value={p.at_bats} />
                              </div>

                              {/* Pitcher info */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: 8 }}>
                                  Opposing Pitching
                                </div>
                                <div style={{ fontWeight: 600, color: 'var(--white)', marginBottom: 6 }}>
                                  {p.opposing_sp_name && p.opposing_sp_name !== 'TBD'
                                    ? p.opposing_sp_name
                                    : <span style={{ color: 'var(--silver-dim)', fontStyle: 'italic' }}>TBD</span>
                                  }
                                  {p.sp_xbaa_source === 'team_overall' && (
                                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 8, color: 'var(--yellow)', marginLeft: 6, fontWeight: 400 }}>
                                      (team avg used)
                                    </span>
                                  )}
                                </div>
                                <StatRow label="SP xBAA"     value={p.sp_xbaa?.toFixed(3)} />
                                <StatRow label="Bullpen xBAA" value={p.bullpen_xbaa?.toFixed(3)} />
                                <StatRow label="Opp team"    value={p.opposing_team} />
                              </div>

                              {/* Model inputs */}
                              <div>
                                <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: 8 }}>
                                  Model Inputs
                                </div>
                                <StatRow label="Batter xBA"     value={p.batter_xba?.toFixed(3)} />
                                <StatRow label="League avg xBA"  value={p.league_avg_xba?.toFixed(4)} />
                                <div style={{ marginTop: 8, padding: '6px 8px', background: 'var(--navy-dark)', borderRadius: 3, fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', lineHeight: 1.6 }}>
                                  log5(B, P, L) = (B·P/L) /<br />
                                  &nbsp;&nbsp;(B·P/L + (1−B)·(1−P)/(1−L))
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
            {/* Model notes */}
            <div style={{
              background: 'var(--navy)', border: '1px solid var(--navy-border)',
              borderRadius: 6, padding: '14px 18px', flex: '1 1 200px',
            }}>
              <div style={{
                fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)',
                letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 10,
              }}>Model Notes</div>
              {[
                { label: 'Formula',      val: 'Bill James Log5' },
                { label: 'Batter stat', val: 'Statcast xBA' },
                { label: 'Pitcher stat', val: 'Statcast xBAA' },
                { label: 'League avg',  val: leagueAvg ? `${leagueAvg.toFixed(4)} (live)` : 'Live (computed daily)' },
                { label: 'Qualifier',   val: '≥ 50% of team games' },
                { label: 'SP fallback', val: 'Team overall xBAA' },
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
