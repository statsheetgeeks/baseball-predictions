import { useState, useEffect } from 'react'
import Layout from '../../components/Layout'

/*
 * Hitters Composite Page
 * ─────────────────────────────────────────────────────────────────────────────
 * Fetches five JSON files in parallel:
 *   1. hitters-log5-hit.json        — Log5 Hit top-25 (hit_probability)
 *   2. hitters-ml-hit.json          — ML Hit top-25 (p_mlp)
 *   3. hitters-hr-model.json        — HR Model top-25 (score 0-100)
 *   4. hitters-ml-hr.json           — ML HR top-25 (lambda_poisson)
 *   5. hitters-spotlight-history.json — yesterday + all-time spotlight tracking
 *
 * Spotlight logic (client-side):
 *   Any player appearing in 2+ of the four top-25 lists is a Spotlight Hitter.
 *   Their rows are highlighted in all columns where they appear.
 */

// ── Model definitions ─────────────────────────────────────────────────────────
const MODELS = [
  {
    key:       'log5',
    label:     'Log5 Hit',
    slug:      'hitters-log5-hit',
    metric:    'hit_probability',
    href:      '/hitters/log5-hit',
    color:     'var(--accent)',
    fmt:       v => v != null ? (v * 100).toFixed(1) + '%' : '—',
    desc:      'P(≥1 hit) via Log5 xBA',
  },
  {
    key:       'mlhit',
    label:     'ML Hit',
    slug:      'hitters-ml-hit',
    metric:    'p_mlp',
    href:      '/hitters/ml-hit',
    color:     'var(--green)',
    fmt:       v => v != null ? (v * 100).toFixed(1) + '%' : '—',
    desc:      'MLP hit probability',
  },
  {
    key:       'hr',
    label:     'HR Model',
    slug:      'hitters-hr-model',
    metric:    'score',
    href:      '/hitters/hr-model',
    color:     'var(--yellow)',
    fmt:       v => v != null ? String(v) : '—',
    desc:      'Composite HR score (0–100)',
  },
  {
    key:       'mlhr',
    label:     'ML HR',
    slug:      'hitters-ml-hr',
    metric:    'lambda_poisson',
    href:      '/hitters/ml-hr',
    color:     '#e8944c',
    fmt:       v => v != null ? v.toFixed(4) : '—',
    desc:      'Poisson λ (expected HR rate)',
  },
]

// ── Spotlight highlight style ─────────────────────────────────────────────────
const SPOT_BG     = 'rgba(212, 168, 67, 0.08)'
const SPOT_BORDER = 'var(--yellow)'

// ── Appearance badge colors ───────────────────────────────────────────────────
const modelColor = (label) => {
  const m = MODELS.find(m => m.label === label)
  return m ? m.color : 'var(--silver-dim)'
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const rankColor = (i) =>
  i === 0 ? '#FFD700' : i === 1 ? '#C0C0C0' : i === 2 ? '#CD7F32' : 'var(--silver-dim)'

function AppearanceBadge({ label }) {
  return (
    <span style={{
      display:       'inline-block',
      padding:       '1px 6px',
      borderRadius:  2,
      border:        `1px solid ${modelColor(label)}`,
      color:         modelColor(label),
      fontFamily:    "'DM Mono', monospace",
      fontSize:      9,
      letterSpacing: '0.5px',
      marginRight:   4,
      marginBottom:  2,
    }}>
      {label}
    </span>
  )
}

function MiniBar({ value, max = 100, color }) {
  const pct = Math.min((value ?? 0) / max * 100, 100)
  return (
    <div style={{ flex: 1, height: 3, background: 'var(--navy-border)', borderRadius: 2 }}>
      <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 2 }} />
    </div>
  )
}

// ── Model column ──────────────────────────────────────────────────────────────
function ModelColumn({ model, predictions, spotlightNames, updatedStr }) {
  const top25 = (predictions || []).slice(0, 25)

  return (
    <div style={{
      flex:         '1 1 220px',
      minWidth:     200,
      background:   'var(--navy)',
      border:       '1px solid var(--navy-border)',
      borderTop:    `3px solid ${model.color}`,
      borderRadius: 4,
      overflow:     'hidden',
    }}>
      {/* Column header */}
      <div style={{ padding: '12px 14px 10px', borderBottom: '1px solid var(--navy-border)' }}>
        <div style={{
          fontFamily:    "'Barlow Condensed', sans-serif",
          fontWeight:    800,
          fontSize:      15,
          color:         model.color,
          letterSpacing: 0.5,
          marginBottom:  2,
        }}>
          {model.label}
        </div>
        <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)' }}>
          {model.desc}
        </div>
        {updatedStr && (
          <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 8, color: 'var(--navy-border)', marginTop: 4 }}>
            {updatedStr}
          </div>
        )}
      </div>

      {/* Rows */}
      {top25.length === 0 ? (
        <div style={{ padding: '24px 14px', color: 'var(--silver-dim)', fontFamily: "'DM Mono', monospace", fontSize: 11, textAlign: 'center' }}>
          No predictions yet
        </div>
      ) : (
        top25.map((p, i) => {
          const isSpot  = spotlightNames.has(p.player)
          const val     = p[model.metric]

          return (
            <div
              key={i}
              style={{
                display:      'flex',
                alignItems:   'center',
                gap:          8,
                padding:      '7px 14px',
                background:   isSpot ? SPOT_BG : 'transparent',
                borderLeft:   isSpot ? `3px solid ${SPOT_BORDER}` : '3px solid transparent',
                borderBottom: '1px solid var(--navy-border)',
              }}
            >
              {/* Rank */}
              <span style={{
                fontFamily: "'Barlow Condensed', sans-serif",
                fontWeight: 700,
                fontSize:   13,
                color:      rankColor(i),
                minWidth:   20,
                textAlign:  'right',
                flexShrink: 0,
              }}>
                {p.rank ?? i + 1}
              </span>

              {/* Name + team */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize:     12,
                  fontWeight:   isSpot ? 700 : 400,
                  color:        isSpot ? 'var(--white)' : 'var(--silver)',
                  whiteSpace:   'nowrap',
                  overflow:     'hidden',
                  textOverflow: 'ellipsis',
                }}>
                  {isSpot && (
                    <span style={{ color: 'var(--yellow)', marginRight: 4, fontSize: 10 }}>★</span>
                  )}
                  {p.player}
                </div>
                <div style={{
                  fontFamily:    "'DM Mono', monospace",
                  fontSize:      8,
                  color:         'var(--silver-dim)',
                  letterSpacing: '1px',
                  textTransform: 'uppercase',
                }}>
                  {p.team}
                </div>
              </div>

              {/* Metric */}
              <span style={{
                fontFamily: "'DM Mono', monospace",
                fontSize:   11,
                fontWeight: 600,
                color:      isSpot ? model.color : 'var(--silver)',
                flexShrink: 0,
                minWidth:   44,
                textAlign:  'right',
              }}>
                {model.fmt(val)}
              </span>
            </div>
          )
        })
      )}
    </div>
  )
}

// ── Spotlight box ─────────────────────────────────────────────────────────────
function SpotlightBox({ players }) {
  if (!players || players.length === 0) {
    return (
      <div style={{
        padding:      '16px 20px',
        background:   'var(--navy)',
        border:       '1px solid var(--navy-border)',
        borderTop:    '3px solid var(--yellow)',
        borderRadius: 4,
        marginBottom: 20,
      }}>
        <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--yellow)', letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 6 }}>
          Spotlight Hitters of the Day
        </div>
        <div style={{ color: 'var(--silver-dim)', fontSize: 12 }}>
          No player appears in more than one list today.
        </div>
      </div>
    )
  }

  const tier4 = players.filter(p => p.appearances === 4)
  const tier3 = players.filter(p => p.appearances === 3)
  const tier2 = players.filter(p => p.appearances === 2)

  const PlayerCard = ({ p }) => (
    <div style={{
      display:      'flex',
      flexWrap:     'wrap',
      alignItems:   'center',
      gap:          8,
      padding:      '8px 12px',
      background:   SPOT_BG,
      border:       `1px solid ${SPOT_BORDER}`,
      borderRadius: 4,
    }}>
      <div>
        <div style={{ fontWeight: 700, color: 'var(--white)', fontSize: 13 }}>
          {p.player}
        </div>
        <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', letterSpacing: '1.5px', textTransform: 'uppercase' }}>
          {p.team}
        </div>
      </div>
      <div style={{ marginLeft: 'auto', display: 'flex', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        {p.models.map(m => <AppearanceBadge key={m} label={m} />)}
      </div>
    </div>
  )

  const Section = ({ label, items, color }) => {
    if (!items.length) return null
    return (
      <div style={{ marginBottom: 12 }}>
        <div style={{
          fontFamily:    "'DM Mono', monospace",
          fontSize:      9,
          color,
          letterSpacing: '2px',
          textTransform: 'uppercase',
          marginBottom:  6,
        }}>
          {label}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {items.map(p => <PlayerCard key={p.player} p={p} />)}
        </div>
      </div>
    )
  }

  return (
    <div style={{
      padding:      '16px 20px',
      background:   'var(--navy)',
      border:       '1px solid var(--navy-border)',
      borderTop:    '3px solid var(--yellow)',
      borderRadius: 4,
      marginBottom: 20,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
        <div style={{
          fontFamily:    "'DM Mono', monospace",
          fontSize:      9,
          color:         'var(--yellow)',
          letterSpacing: '2px',
          textTransform: 'uppercase',
        }}>
          ★ Spotlight Hitters of the Day
        </div>
        <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--silver-dim)' }}>
          {players.length} player{players.length !== 1 ? 's' : ''} in 2+ models
        </div>
      </div>

      <Section label="In all 4 models"   items={tier4} color="#FFD700" />
      <Section label="In 3 models"       items={tier3} color="var(--accent)" />
      <Section label="In 2 models"       items={tier2} color="var(--silver-dim)" />
    </div>
  )
}

// ── Tracking panels ───────────────────────────────────────────────────────────
function TrackingPanel({ title, data }) {
  const hasData = (data?.total ?? 0) > 0
  return (
    <div style={{
      background:   'var(--navy)',
      border:       '1px solid var(--navy-border)',
      borderRadius: 6,
      padding:      '14px 18px',
      flex:         '1 1 220px',
    }}>
      <div style={{
        fontFamily:    "'DM Mono', monospace",
        fontSize:      9,
        color:         'var(--silver-dim)',
        letterSpacing: '2px',
        textTransform: 'uppercase',
        marginBottom:  8,
      }}>
        {title}
      </div>

      {!hasData ? (
        <div style={{ color: 'var(--silver-dim)', fontSize: 12 }}>No graded picks yet</div>
      ) : (
        <>
          {/* Hit rate */}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 4 }}>
            <span style={{
              fontFamily: "'Barlow Condensed', sans-serif",
              fontSize:   28, fontWeight: 700, color: 'var(--green)',
            }}>
              {data.hit_count}
            </span>
            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: 'var(--silver-dim)' }}>
              / {data.total} got a hit
            </span>
            <span style={{ marginLeft: 'auto', fontFamily: "'DM Mono', monospace", fontSize: 13, color: 'var(--accent)' }}>
              {data.hit_rate_pct}%
            </span>
          </div>

          {/* HR rate */}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 12 }}>
            <span style={{
              fontFamily: "'Barlow Condensed', sans-serif",
              fontSize:   22, fontWeight: 700, color: 'var(--yellow)',
            }}>
              {data.hr_count}
            </span>
            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: 'var(--silver-dim)' }}>
              / {data.total} hit a HR
            </span>
            <span style={{ marginLeft: 'auto', fontFamily: "'DM Mono', monospace", fontSize: 13, color: 'var(--yellow)' }}>
              {data.hr_rate_pct}%
            </span>
          </div>

          {/* By appearances */}
          {data.by_appearances && Object.entries(data.by_appearances).map(([key, s]) => (
            <div key={key} style={{ marginBottom: 8 }}>
              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', marginBottom: 3 }}>
                {key}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 8, color: 'var(--green)', minWidth: 20 }}>H</span>
                <MiniBar value={s.hit_rate_pct} max={100} color="var(--green)" />
                <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', minWidth: 30, textAlign: 'right' }}>
                  {s.hit_rate_pct}%
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 8, color: 'var(--yellow)', minWidth: 20 }}>HR</span>
                <MiniBar value={s.hr_rate_pct} max={100} color="var(--yellow)" />
                <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)', minWidth: 30, textAlign: 'right' }}>
                  {s.hr_rate_pct}%
                </span>
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  )
}

// ── Yesterday detail panel ────────────────────────────────────────────────────
function YesterdayDetail({ record }) {
  if (!record?.graded || !record?.players?.length) return null

  return (
    <div style={{
      background:   'var(--navy)',
      border:       '1px solid var(--navy-border)',
      borderRadius: 6,
      padding:      '14px 18px',
      flex:         '2 1 360px',
    }}>
      <div style={{
        fontFamily:    "'DM Mono', monospace",
        fontSize:      9,
        color:         'var(--silver-dim)',
        letterSpacing: '2px',
        textTransform: 'uppercase',
        marginBottom:  10,
      }}>
        Yesterday's Spotlight — {record.date}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {record.players.map(p => {
          const gotHit = p.actual_hit
          const gotHR  = p.actual_hr
          return (
            <div
              key={p.player}
              style={{
                padding:      '6px 10px',
                background:   gotHit ? 'rgba(74,144,217,0.08)' : 'rgba(255,255,255,0.02)',
                border:       `1px solid ${gotHit ? 'var(--accent)' : 'var(--navy-border)'}`,
                borderRadius: 4,
                minWidth:     140,
              }}
            >
              <div style={{ fontWeight: 600, color: 'var(--white)', fontSize: 12 }}>
                {p.player}
              </div>
              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 8, color: 'var(--silver-dim)', textTransform: 'uppercase', marginTop: 2 }}>
                {p.team} · {p.appearances} models
              </div>
              <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                <span style={{
                  fontFamily: "'DM Mono', monospace",
                  fontSize:   10,
                  color:      gotHit ? 'var(--green)' : 'var(--silver-dim)',
                  fontWeight: gotHit ? 700 : 400,
                }}>
                  {gotHit ? '✓ HIT' : '✗ NO HIT'}
                </span>
                {gotHR && (
                  <span style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize:   10,
                    color:      'var(--yellow)',
                    fontWeight: 700,
                  }}>
                    · ⚾ HR
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function HittersComposite() {
  const [modelData,    setModelData]    = useState({})
  const [spotHistory,  setSpotHistory]  = useState(null)
  const [loading,      setLoading]      = useState(true)
  const [errors,       setErrors]       = useState({})

  useEffect(() => {
    const fetches = [
      ...MODELS.map(m =>
        fetch(`/data/${m.slug}.json`)
          .then(r => r.ok ? r.json() : null)
          .then(d => [m.key, d])
          .catch(() => [m.key, null])
      ),
      fetch('/data/hitters-spotlight-history.json')
        .then(r => r.ok ? r.json() : null)
        .then(d => ['spotlight', d])
        .catch(() => ['spotlight', null]),
    ]

    Promise.all(fetches).then(results => {
      const data = {}
      const errs = {}
      results.forEach(([key, val]) => {
        if (val) data[key] = val
        else     errs[key] = true
      })
      setModelData(data)
      setSpotHistory(data.spotlight ?? null)
      setErrors(errs)
      setLoading(false)
    })
  }, [])

  // ── Compute spotlight from the four model prediction lists ─────────────────
  const spotlightPlayers = (() => {
    const counts = {}   // name → {models: [], team: ''}
    MODELS.forEach(m => {
      const preds = modelData[m.key]?.predictions ?? []
      preds.slice(0, 25).forEach(p => {
        if (!p.player) return
        if (!counts[p.player]) counts[p.player] = { models: [], team: p.team ?? '' }
        counts[p.player].models.push(m.label)
        if (p.team) counts[p.player].team = p.team
      })
    })
    return Object.entries(counts)
      .filter(([, v]) => v.models.length >= 2)
      .map(([name, v]) => ({ player: name, team: v.team, appearances: v.models.length, models: v.models }))
      .sort((a, b) => b.appearances - a.appearances || a.player.localeCompare(b.player))
  })()

  const spotlightNames = new Set(spotlightPlayers.map(p => p.player))

  // Spotlight history data
  const yesterday  = spotHistory?.yesterday  ?? {}
  const alltime    = spotHistory?.alltime    ?? {}
  const ydayRecord = spotHistory?.records?.find(r => r.date === yesterday.date)

  // Updated timestamps per model
  const updatedStr = (key) => {
    const updated = modelData[key]?.updated
    if (!updated) return null
    try {
      return new Date(updated).toLocaleString('en-US', {
        month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
        timeZone: 'America/Chicago',
      }) + ' CT'
    } catch { return null }
  }

  const anyLoaded = Object.keys(modelData).length > 0

  return (
    <Layout title="Hitters Composite">

      {/* ── Page header ──────────────────────────────────────────────────── */}
      <div style={{ marginBottom: '1.5rem', borderLeft: '3px solid var(--yellow)', paddingLeft: '1.25rem' }}>
        <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--yellow)', letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 8 }}>
          Hitters → Composite
        </div>
        <h1 style={{ fontFamily: "'Barlow Condensed', sans-serif", fontWeight: 900, fontSize: '2.4rem', color: 'var(--white)', lineHeight: 1.1, marginBottom: 8 }}>
          HITTERS COMPOSITE
        </h1>
        <p style={{ fontSize: 13, color: 'var(--silver)', maxWidth: 660, lineHeight: 1.65 }}>
          Top 25 from all four hitter models side by side. Players appearing in two or more lists
          are <span style={{ color: 'var(--yellow)' }}>★ Spotlight Hitters</span> — highlighted in every column where they appear.
        </p>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: '80px 20px', color: 'var(--silver-dim)', fontFamily: "'DM Mono', monospace", fontSize: 12 }}>
          Loading all four models…
        </div>
      )}

      {!loading && (
        <>
          {/* ── Spotlight box ─────────────────────────────────────────────── */}
          <SpotlightBox players={spotlightPlayers} />

          {/* ── Four model columns ────────────────────────────────────────── */}
          {anyLoaded && (
            <div style={{
              display:   'flex',
              gap:       12,
              flexWrap:  'wrap',
              alignItems: 'flex-start',
              marginBottom: 28,
            }}>
              {MODELS.map(m => (
                <ModelColumn
                  key={m.key}
                  model={m}
                  predictions={modelData[m.key]?.predictions ?? []}
                  spotlightNames={spotlightNames}
                  updatedStr={updatedStr(m.key)}
                />
              ))}
            </div>
          )}

          {/* ── Error notices ─────────────────────────────────────────────── */}
          {Object.keys(errors).filter(k => k !== 'spotlight').length > 0 && (
            <div style={{
              padding: '10px 14px', marginBottom: 20,
              background: 'rgba(224,84,84,0.06)',
              border: '1px solid var(--red, #e05454)',
              borderRadius: 4,
              fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--red, #e05454)',
            }}>
              ⚠ Could not load:{' '}
              {Object.keys(errors).filter(k => k !== 'spotlight').map(k => {
                const m = MODELS.find(m => m.key === k)
                return m ? m.label : k
              }).join(', ')}
              {' '}— data may not be available yet today.
            </div>
          )}

          {/* ── Tracking section ──────────────────────────────────────────── */}
          <div style={{
            fontFamily:    "'DM Mono', monospace",
            fontSize:      9,
            color:         'var(--silver-dim)',
            letterSpacing: '2px',
            textTransform: 'uppercase',
            marginBottom:  12,
            paddingTop:    8,
            borderTop:     '1px solid var(--navy-border)',
          }}>
            ★ Spotlight Hitter Tracking
          </div>

          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
            <TrackingPanel
              title={`Yesterday (${yesterday.date || '—'})`}
              data={yesterday.total ? yesterday : null}
            />
            <TrackingPanel
              title="All-Time Spotlight"
              data={alltime.total ? alltime : null}
            />
            <YesterdayDetail record={ydayRecord} />
          </div>

          {/* ── Model key ─────────────────────────────────────────────────── */}
          <div style={{
            display:      'flex',
            gap:          16,
            flexWrap:     'wrap',
            padding:      '10px 14px',
            background:   'var(--navy)',
            border:       '1px solid var(--navy-border)',
            borderRadius: 4,
          }}>
            {MODELS.map(m => (
              <div key={m.key} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{ width: 8, height: 8, borderRadius: '50%', background: m.color, flexShrink: 0 }} />
                <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--silver)' }}>
                  {m.label}
                </span>
                <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--silver-dim)' }}>
                  — {m.desc}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </Layout>
  )
}
