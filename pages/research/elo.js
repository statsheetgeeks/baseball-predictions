import { useState, useEffect } from 'react'
import Layout from '../../components/Layout'
import { PageHeader } from '../../components/PredictionTable'

// ── Data hook ─────────────────────────────────────────────────────────────────
function useEloData() {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  useEffect(() => {
    fetch('/data/research-elo.json')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(data => setState({ data, loading: false, error: null }))
      .catch(err  => setState({ data: null, loading: false, error: err.message }))
  }, [])
  return state
}

// ── Shared table styles ───────────────────────────────────────────────────────
const thStyle = {
  textAlign:     'left',
  fontSize:      11,
  fontWeight:    600,
  letterSpacing: 1,
  textTransform: 'uppercase',
  color:         'var(--silver)',
  padding:       '10px 14px',
  borderBottom:  '2px solid var(--navy-border)',
  whiteSpace:    'nowrap',
}

const tdStyle = {
  padding:       '9px 14px',
  borderBottom:  '1px solid var(--navy-border)',
  fontSize:      13,
  verticalAlign: 'middle',
}

// ── Delta badge ───────────────────────────────────────────────────────────────
function DeltaBadge({ delta }) {
  const pos   = delta >= 0
  const color = pos ? 'var(--green)' : 'var(--red)'
  return (
    <span style={{
      fontFamily:  "'DM Mono', monospace",
      fontSize:    12,
      color,
      fontWeight:  600,
    }}>
      {delta >= 0 ? '+' : ''}{delta.toFixed(1)}
    </span>
  )
}

// ── Win-probability bar ───────────────────────────────────────────────────────
function WpBar({ value }) {
  const pct = (value * 100).toFixed(1)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, width: 40 }}>
        {pct}%
      </span>
      <div style={{
        width: 60, height: 5, background: 'var(--navy-border)', borderRadius: 3, overflow: 'hidden',
      }}>
        <div style={{
          width:        `${Math.min(pct, 100)}%`,
          height:       '100%',
          background:   'var(--accent)',
          borderRadius: 3,
        }} />
      </div>
    </div>
  )
}

// ── Correct/incorrect indicator ───────────────────────────────────────────────
function ResultBadge({ correct }) {
  return (
    <span style={{
      display:      'inline-block',
      fontSize:     10,
      fontWeight:   700,
      fontFamily:   "'DM Mono', monospace",
      letterSpacing: 0.5,
      padding:      '2px 7px',
      borderRadius: 3,
      background:   correct ? 'rgba(39,174,96,0.15)' : 'rgba(192,57,43,0.12)',
      color:        correct ? 'var(--green)'          : 'var(--red)',
      border:       `1px solid ${correct ? 'rgba(39,174,96,0.35)' : 'rgba(192,57,43,0.3)'}`,
    }}>
      {correct ? '✓ CORRECT' : '✗ WRONG'}
    </span>
  )
}

// ── Standings table ───────────────────────────────────────────────────────────
function StandingsTable({ standings }) {
  return (
    <div style={{
      background:   'var(--navy-mid)',
      border:       '1px solid var(--navy-border)',
      borderRadius: 8,
      overflow:     'hidden',
      marginBottom: 32,
    }}>
      <div style={{
        padding:     '14px 18px',
        borderBottom:'1px solid var(--navy-border)',
        fontFamily:  "'Barlow Condensed', sans-serif",
        fontWeight:  700,
        fontSize:    13,
        letterSpacing: 2,
        textTransform: 'uppercase',
        color:       'var(--accent)',
      }}>
        Current Elo Standings — {new Date().getFullYear()} Season
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 560 }}>
          <thead>
            <tr>
              <th style={{ ...thStyle, textAlign: 'center', width: 40 }}>RK</th>
              <th style={thStyle}>Team</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>Elo Rating</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>Δ Mean</th>
              <th style={{ ...thStyle }}>Implied Win%</th>
              <th style={{ ...thStyle, textAlign: 'center' }}>W-L</th>
            </tr>
          </thead>
          <tbody>
            {standings.map((team, i) => (
              <tr
                key={team.abbr}
                style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)' }}
              >
                {/* Rank */}
                <td style={{ ...tdStyle, textAlign: 'center', color: 'var(--muted)', fontFamily: "'DM Mono', monospace", fontSize: 11 }}>
                  {team.rank}
                </td>

                {/* Team */}
                <td style={tdStyle}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{
                      fontFamily:   "'Barlow Condensed', sans-serif",
                      fontWeight:   700,
                      fontSize:     13,
                      letterSpacing: 1,
                      color:        'var(--accent)',
                      minWidth:     36,
                    }}>
                      {team.abbr}
                    </span>
                    <span style={{ color: 'var(--silver)', fontSize: 13 }}>{team.team}</span>
                  </div>
                </td>

                {/* Rating */}
                <td style={{ ...tdStyle, textAlign: 'right', fontFamily: "'DM Mono', monospace", fontSize: 13, fontWeight: 600, color: 'var(--white)' }}>
                  {team.rating.toFixed(1)}
                </td>

                {/* Delta from 1500 */}
                <td style={{ ...tdStyle, textAlign: 'right' }}>
                  <DeltaBadge delta={team.delta} />
                </td>

                {/* Implied win% bar */}
                <td style={tdStyle}>
                  <WpBar value={team.implied_wp} />
                </td>

                {/* W-L */}
                <td style={{ ...tdStyle, textAlign: 'center', fontFamily: "'DM Mono', monospace", fontSize: 12, color: 'var(--silver)' }}>
                  {team.wins}–{team.losses}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Recent games table ────────────────────────────────────────────────────────
function RecentGamesTable({ games }) {
  return (
    <div style={{
      background:   'var(--navy-mid)',
      border:       '1px solid var(--navy-border)',
      borderRadius: 8,
      overflow:     'hidden',
    }}>
      <div style={{
        padding:      '14px 18px',
        borderBottom: '1px solid var(--navy-border)',
        fontFamily:   "'Barlow Condensed', sans-serif",
        fontWeight:   700,
        fontSize:     13,
        letterSpacing: 2,
        textTransform: 'uppercase',
        color:        'var(--accent)',
      }}>
        Recent Games — Model Performance
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 680 }}>
          <thead>
            <tr>
              <th style={thStyle}>Date</th>
              <th style={thStyle}>Matchup</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>Away Elo</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>Home Elo</th>
              <th style={{ ...thStyle, textAlign: 'center' }}>Home Win%</th>
              <th style={{ ...thStyle, textAlign: 'center' }}>Result</th>
              <th style={{ ...thStyle, textAlign: 'center' }}>Model</th>
            </tr>
          </thead>
          <tbody>
            {games.map((g, i) => {
              const homeWon = g.home_win === 1
              return (
                <tr
                  key={`${g.date}-${g.game_pk}`}
                  style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)' }}
                >
                  {/* Date */}
                  <td style={{ ...tdStyle, color: 'var(--muted)', fontFamily: "'DM Mono', monospace", fontSize: 11, whiteSpace: 'nowrap' }}>
                    {g.date}
                  </td>

                  {/* Matchup */}
                  <td style={tdStyle}>
                    <span style={{ color: homeWon ? 'var(--silver)' : 'var(--white)', fontWeight: homeWon ? 400 : 600 }}>
                      {g.away_abbr}
                    </span>
                    <span style={{ color: 'var(--muted)', margin: '0 6px', fontSize: 11 }}>@</span>
                    <span style={{ color: homeWon ? 'var(--white)' : 'var(--silver)', fontWeight: homeWon ? 600 : 400 }}>
                      {g.home_abbr}
                    </span>
                  </td>

                  {/* Away Elo */}
                  <td style={{ ...tdStyle, textAlign: 'right', fontFamily: "'DM Mono', monospace", fontSize: 12, color: 'var(--silver)' }}>
                    {g.away_elo_pre.toFixed(1)}
                  </td>

                  {/* Home Elo */}
                  <td style={{ ...tdStyle, textAlign: 'right', fontFamily: "'DM Mono', monospace", fontSize: 12, color: 'var(--silver)' }}>
                    {g.home_elo_pre.toFixed(1)}
                  </td>

                  {/* Home win probability */}
                  <td style={{ ...tdStyle, textAlign: 'center', fontFamily: "'DM Mono', monospace", fontSize: 12 }}>
                    {(g.home_prob * 100).toFixed(1)}%
                  </td>

                  {/* Actual score */}
                  <td style={{ ...tdStyle, textAlign: 'center', fontFamily: "'DM Mono', monospace", fontSize: 13, fontWeight: 600, color: 'var(--white)' }}>
                    {g.away_score}–{g.home_score}
                  </td>

                  {/* Model correct */}
                  <td style={{ ...tdStyle, textAlign: 'center' }}>
                    <ResultBadge correct={g.model_correct} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Methodology pill ──────────────────────────────────────────────────────────
function MethodologyBar({ params }) {
  const pills = [
    { label: 'K-Factor',       value: params.k },
    { label: 'Home Advantage', value: `+${params.home_adv} pts` },
    { label: 'Season Reversion', value: `${(params.reversion * 100).toFixed(0)}% → 1500` },
    { label: 'Training Window', value: `${params.seasons[0]}–${params.seasons[params.seasons.length - 1]}` },
  ]
  return (
    <div style={{
      display:    'flex',
      flexWrap:   'wrap',
      gap:        10,
      marginBottom: 28,
    }}>
      {pills.map(p => (
        <div key={p.label} style={{
          background:   'var(--navy-mid)',
          border:       '1px solid var(--navy-border)',
          borderRadius: 6,
          padding:      '8px 14px',
          display:      'flex',
          flexDirection:'column',
          gap:          3,
        }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', fontFamily: "'DM Mono', monospace", letterSpacing: 0.5, textTransform: 'uppercase' }}>
            {p.label}
          </div>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--white)', fontFamily: "'Barlow Condensed', sans-serif", letterSpacing: 0.5 }}>
            {p.value}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Accuracy stat bar ─────────────────────────────────────────────────────────
function AccuracyBar({ accuracy }) {
  if (!accuracy || !accuracy.games) return null
  const pct = (accuracy.pct * 100).toFixed(1)
  return (
    <div style={{
      display:             'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
      gap:                 1,
      background:          'var(--navy-border)',
      border:              '1px solid var(--navy-border)',
      borderRadius:        10,
      overflow:            'hidden',
      marginBottom:        32,
    }}>
      {[
        { label: `${accuracy.season} Accuracy`, value: `${pct}%` },
        { label: 'Games Graded',  value: accuracy.games.toLocaleString() },
        { label: 'Correct Picks', value: accuracy.correct.toLocaleString() },
        { label: 'Baseline',      value: '50.0%' },
      ].map(s => (
        <div key={s.label} style={{ background: 'var(--navy)', padding: '18px 20px', textAlign: 'center' }}>
          <div style={{
            fontFamily: "'Barlow Condensed', sans-serif",
            fontWeight: 800,
            fontSize:   26,
            color:      'var(--white)',
            lineHeight: 1,
            marginBottom: 4,
          }}>
            {s.value}
          </div>
          <div style={{ fontSize: 11, color: 'var(--silver-dim)', fontFamily: "'DM Mono', monospace", letterSpacing: 0.5 }}>
            {s.label}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function EloRatings() {
  const { data, loading, error } = useEloData()

  const updatedLabel = data?.updated
    ? new Date(data.updated).toLocaleString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
      })
    : null

  return (
    <Layout title="Elo Ratings">
      <PageHeader
        tag="Research → Elo"
        title="MLB ELO RATINGS"
        subtitle="Team power ratings built on the FiveThirtyEight methodology: K=4, 24-point home advantage, 1/3 seasonal regression toward 1500. Trained on regular-season game results since 2021."
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
          Loading Elo data…
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
          <MethodologyBar params={data.params} />
          <AccuracyBar accuracy={data.accuracy} />
          <StandingsTable standings={data.standings} />
          <RecentGamesTable games={data.recent_games} />
        </>
      )}
    </Layout>
  )
}
