import { useState, useEffect } from 'react'
import Layout from '../../components/Layout'
import { PageHeader } from '../../components/PredictionTable'

// ── Data hook ─────────────────────────────────────────────────────────────────
function useHotHitters() {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  useEffect(() => {
    fetch('/data/research-hot-hitters.json')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(data => setState({ data, loading: false, error: null }))
      .catch(err  => setState({ data: null, loading: false, error: err.message }))
  }, [])
  return state
}

// ── Shared table styles ───────────────────────────────────────────────────────
const thBase = {
  fontSize:      11,
  fontWeight:    600,
  letterSpacing: 1,
  textTransform: 'uppercase',
  color:         'var(--silver)',
  padding:       '10px 12px',
  borderBottom:  '2px solid var(--navy-border)',
  whiteSpace:    'nowrap',
  fontFamily:    "'Inter', sans-serif",
  userSelect:    'none',
}

const tdBase = {
  padding:       '9px 12px',
  borderBottom:  '1px solid var(--navy-border)',
  fontSize:      13,
  verticalAlign: 'middle',
  fontFamily:    "'Inter', sans-serif",
}

// ── Column definitions ────────────────────────────────────────────────────────
const COLUMNS = [
  { key: 'rank',          label: '#',           align: 'center', width: 40,  sortable: false },
  { key: 'player',        label: 'Player',      align: 'left',   width: 160, sortable: true  },
  { key: 'hotness_score', label: 'Hotness',     align: 'right',  width: 90,  sortable: true  },
  { key: 'hit_streak',    label: 'Hit Stk',     align: 'right',  width: 72,  sortable: true  },
  { key: 'hr_streak',     label: 'HR Stk',      align: 'right',  width: 72,  sortable: true  },
  { key: 'ops_5',         label: 'OPS (L5)',    align: 'right',  width: 82,  sortable: true  },
  { key: 'ops_10',        label: 'OPS (L10)',   align: 'right',  width: 82,  sortable: true  },
  { key: 'xwoba_5',       label: 'xwOBA (L5)',  align: 'right',  width: 90,  sortable: true  },
  { key: 'xwoba_10',      label: 'xwOBA (L10)', align: 'right',  width: 90,  sortable: true  },
  { key: 'ab_5',          label: 'AB (L5)',     align: 'right',  width: 70,  sortable: true  },
]

// ── Cell renderers ────────────────────────────────────────────────────────────

function HotnessCell({ value }) {
  // 0.0 → grey, ~0.4+ → gold
  const norm  = Math.min(value / 0.45, 1)
  const r     = Math.round(255 * norm)
  const g     = Math.round(180 * norm)
  const b     = Math.round(20  * norm)
  const color = `rgb(${r},${g},${b})`
  return (
    <span style={{
      fontFamily: "'DM Mono', monospace",
      fontSize:   13,
      fontWeight: 700,
      color,
    }}>
      {value.toFixed(3)}
    </span>
  )
}

function StreakCell({ value, type }) {
  if (value === 0) {
    return (
      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: 'var(--silver-dim)' }}>
        —
      </span>
    )
  }
  const color  = type === 'hr' ? '#ff6b6b' : '#ffd27a'
  const border = type === 'hr' ? 'rgba(255,107,107,0.3)' : 'rgba(255,210,122,0.3)'
  const bg     = type === 'hr' ? 'rgba(255,107,107,0.08)' : 'rgba(255,210,122,0.08)'
  return (
    <span style={{
      display:      'inline-block',
      fontFamily:   "'DM Mono', monospace",
      fontSize:     12,
      fontWeight:   700,
      color,
      background:   bg,
      border:       `1px solid ${border}`,
      borderRadius: 4,
      padding:      '2px 7px',
    }}>
      {value}G
    </span>
  )
}

function OpsCell({ value }) {
  // colour-code: ≥1.0 green, ≥.800 accent, ≥.600 silver, below muted
  let color = 'var(--silver-dim)'
  if (value >= 1.0)      color = 'var(--green)'
  else if (value >= 0.8) color = 'var(--accent)'
  else if (value >= 0.6) color = 'var(--silver)'
  return (
    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color }}>
      {value.toFixed(3)}
    </span>
  )
}

function XwobaCell({ value }) {
  // colour-code: ≥.400 green, ≥.350 accent, ≥.280 silver, below muted
  let color = 'var(--silver-dim)'
  if (value >= 0.4)      color = 'var(--green)'
  else if (value >= 0.35) color = 'var(--accent)'
  else if (value >= 0.28) color = 'var(--silver)'
  return (
    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color }}>
      {value.toFixed(3)}
    </span>
  )
}

function MonoCell({ value }) {
  return (
    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: 'var(--silver)' }}>
      {value}
    </span>
  )
}

function renderCell(col, row) {
  const v = row[col.key]
  switch (col.key) {
    case 'hotness_score': return <HotnessCell value={v} />
    case 'hit_streak':    return <StreakCell value={v} type="hit" />
    case 'hr_streak':     return <StreakCell value={v} type="hr" />
    case 'ops_5':
    case 'ops_10':        return <OpsCell value={v} />
    case 'xwoba_5':
    case 'xwoba_10':      return <XwobaCell value={v} />
    case 'ab_5':          return <MonoCell value={v} />
    case 'rank':
      return (
        <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: 'var(--silver-dim)' }}>
          {v}
        </span>
      )
    default: return <span style={{ color: 'var(--white)' }}>{v}</span>
  }
}

// ── Sort indicator ────────────────────────────────────────────────────────────
function SortArrow({ dir }) {
  if (!dir) return <span style={{ opacity: 0.25, marginLeft: 4 }}>↕</span>
  return <span style={{ marginLeft: 4, color: 'var(--accent)' }}>{dir === 'asc' ? '↑' : '↓'}</span>
}

// ── Legend pill ───────────────────────────────────────────────────────────────
function LegendPill({ color, border, label }) {
  return (
    <div style={{
      display:      'flex',
      alignItems:   'center',
      gap:          6,
      background:   'var(--navy-mid)',
      border:       `1px solid var(--navy-border)`,
      borderLeft:   `3px solid ${color}`,
      borderRadius: 5,
      padding:      '5px 10px',
    }}>
      <span style={{
        fontFamily:    "'Barlow Condensed', sans-serif",
        fontWeight:    700,
        fontSize:      10,
        letterSpacing: 1.5,
        textTransform: 'uppercase',
        color,
      }}>
        {label}
      </span>
    </div>
  )
}

// ── Main table ────────────────────────────────────────────────────────────────
function HittersTable({ players }) {
  const [sortKey, setSortKey]   = useState('hotness_score')
  const [sortDir, setSortDir]   = useState('desc')
  const [search,  setSearch]    = useState('')

  const filtered = players.filter(p =>
    p.player.toLowerCase().includes(search.toLowerCase())
  )

  const sorted = [...filtered].sort((a, b) => {
    if (!sortKey) return 0
    const av = a[sortKey], bv = b[sortKey]
    if (typeof av === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av)
    return sortDir === 'asc' ? av - bv : bv - av
  })

  function handleSort(key) {
    if (key === sortKey) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  return (
    <div>
      {/* Search bar */}
      <div style={{ marginBottom: 16 }}>
        <input
          type="text"
          placeholder="Search player…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{
            background:   'var(--navy-mid)',
            border:       '1px solid var(--navy-border)',
            borderRadius: 6,
            padding:      '8px 14px',
            color:        'var(--white)',
            fontFamily:   "'Inter', sans-serif",
            fontSize:     13,
            width:        220,
            outline:      'none',
          }}
          onFocus={e => { e.target.style.borderColor = 'var(--accent)' }}
          onBlur={e  => { e.target.style.borderColor = 'var(--navy-border)' }}
        />
        <span style={{ marginLeft: 12, fontSize: 12, color: 'var(--silver-dim)', fontFamily: "'Inter', sans-serif" }}>
          {sorted.length} player{sorted.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Table */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 780 }}>
          <thead>
            <tr>
              {COLUMNS.map(col => (
                <th
                  key={col.key}
                  onClick={() => col.sortable && handleSort(col.key)}
                  style={{
                    ...thBase,
                    textAlign: col.align,
                    width:     col.width,
                    cursor:    col.sortable ? 'pointer' : 'default',
                    color:     sortKey === col.key ? 'var(--accent)' : 'var(--silver)',
                  }}
                >
                  {col.label}
                  {col.sortable && (
                    <SortArrow dir={sortKey === col.key ? sortDir : null} />
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => (
              <tr
                key={row.player}
                style={{ transition: 'background 0.1s' }}
                onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.025)' }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
              >
                {COLUMNS.map(col => (
                  <td key={col.key} style={{ ...tdBase, textAlign: col.align }}>
                    {renderCell(col, row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function PlayerMetrics() {
  const { data, loading, error } = useHotHitters()

  const updatedLabel = data?.updated
    ? new Date(data.updated).toLocaleString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
      })
    : null

  return (
    <Layout title="Player Metrics">
      <PageHeader
        tag="Research → Player Metrics"
        title="HOT HITTERS"
        subtitle="Top 100 hitters ranked by Hotness Score — a recency-weighted composite of xwOBA, OPS, and active streaks over the last 10 days. Requires ≥ 10 ABs and ≥ 2 games played in the last 5 days."
      />

      {updatedLabel && (
        <div style={{ color: 'var(--silver-dim)', fontSize: 12, marginBottom: 20, fontFamily: "'Inter', sans-serif" }}>
          Last updated: {updatedLabel} · λ = {data.decay} decay
        </div>
      )}

      {/* Legend */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 24 }}>
        <LegendPill color="var(--green)"      label="xwOBA ≥ .400 / OPS ≥ 1.000" />
        <LegendPill color="var(--accent)"     label="xwOBA ≥ .350 / OPS ≥ .800"  />
        <LegendPill color="var(--silver)"     label="xwOBA ≥ .280 / OPS ≥ .600"  />
        <LegendPill color="#ffd27a"            label="Active hit streak"            />
        <LegendPill color="#ff6b6b"            label="Active HR streak"             />
      </div>

      {loading && (
        <div style={{
          background: 'var(--navy-mid)', border: '1px solid var(--navy-border)',
          borderRadius: 8, padding: '40px 24px', textAlign: 'center', color: 'var(--silver)',
          fontFamily: "'Inter', sans-serif", fontSize: 14,
        }}>
          Loading hot hitters…
        </div>
      )}

      {error && (
        <div style={{
          background: '#1a0000', border: '1px solid #ff4444', borderRadius: 8,
          padding: '20px 24px', color: '#ff8888', marginBottom: 24,
          fontFamily: "'Inter', sans-serif", fontSize: 13,
        }}>
          Failed to load data: {error}
        </div>
      )}

      {data && (
        <div style={{
          background:   'var(--navy-mid)',
          border:       '1px solid var(--navy-border)',
          borderRadius: 8,
          padding:      '20px 24px',
        }}>
          <HittersTable players={data.players} />
        </div>
      )}

      {/* Score methodology card */}
      {data && (
        <div style={{
          marginTop:    24,
          background:   'var(--navy-mid)',
          border:       '1px solid var(--navy-border)',
          borderRadius: 8,
          padding:      '16px 20px',
          maxWidth:     560,
        }}>
          <div style={{
            fontFamily:    "'Inter', sans-serif",
            fontWeight:    600,
            fontSize:      10,
            letterSpacing: 2,
            textTransform: 'uppercase',
            color:         'var(--silver-dim)',
            marginBottom:  8,
          }}>
            Hotness Score Formula
          </div>
          <p style={{ fontSize: 12, color: 'var(--silver)', fontFamily: "'DM Mono', monospace", lineHeight: 1.8 }}>
            0.40 × (xwOBA_L5 × 2) + 0.30 × (xwOBA_L10 × 2)<br />
            + 0.20 × Hit Streak + 0.10 × HR Streak
          </p>
          <p style={{ marginTop: 8, fontSize: 12, color: 'var(--silver-dim)', fontFamily: "'Inter', sans-serif", lineHeight: 1.6 }}>
            All rolling windows use exponential decay (λ = {data.decay}) — games from yesterday
            carry full weight, games from 7 days ago carry ~{Math.round(data.decay ** 7 * 100)}% weight.
            Minimum qualifier: {'>'}= 10 AB and {'>'} = 2 games in the last 5 days.
          </p>
        </div>
      )}
    </Layout>
  )
}
