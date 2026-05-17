/**
 * PredictionTable
 *
 * Props:
 *  - data   : array of row objects (from your JSON file)
 *  - columns: array of { key, label, render? }
 *             render(value, row) is optional — lets you format a cell however you want
 *  - updated: ISO date string from the JSON (shown in header)
 *  - loading: bool
 *  - error  : string or null
 */
export default function PredictionTable({ data = [], columns = [], updated, loading, error }) {
  if (loading) {
    return (
      <div style={{
        padding:    '3rem',
        textAlign:  'center',
        fontFamily: "'Inter', sans-serif",
        color:      'var(--muted)',
        fontSize:   13,
      }}>
        Loading predictions…
      </div>
    )
  }

  if (error) {
    return (
      <div style={{
        padding:      '1.5rem',
        background:   'rgba(224,84,84,0.08)',
        border:       '1px solid var(--red)',
        borderRadius: 6,
        fontFamily:   "'Inter', sans-serif",
        fontSize:     12,
        color:        'var(--red)',
      }}>
        {error}
      </div>
    )
  }

  if (!data.length) {
    return (
      <div style={{
        padding:    '2rem',
        fontFamily: "'Inter', sans-serif",
        color:      'var(--muted)',
        fontSize:   12,
      }}>
        No prediction data found. Run your models to generate predictions.
      </div>
    )
  }

  return (
    <div>
      {/* Table meta */}
      {updated && (
        <div style={{
          marginBottom: 12,
          fontFamily:   "'Inter', sans-serif",
          fontSize:     11,
          color:        'var(--muted)',
        }}>
          Last updated:{' '}
          <span style={{ color: 'var(--text)' }}>
            {new Date(updated).toLocaleString()}
          </span>
          &nbsp;·&nbsp;{data.length} predictions
        </div>
      )}

      {/* Scrollable table wrapper */}
      <div style={{ overflowX: 'auto', borderRadius: 8, border: '1px solid var(--border)' }}>
        <table className="pred-table">
          <thead>
            <tr>
              {columns.map(col => (
                <th key={col.key}>{col.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((row, i) => (
              <tr key={i}>
                {columns.map(col => (
                  <td key={col.key}>
                    {col.render ? col.render(row[col.key], row) : (row[col.key] ?? '—')}
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

/* ── Reusable cell renderers ─────────────────────────────────────────────────── */

/** Shows a percentage: 0.637 → "63.7%" with a small bar underneath */
export function ProbCell({ value }) {
  if (value == null) return <>—</>
  const pct = (value * 100).toFixed(1)
  return (
    <div>
      <div style={{ marginBottom: 3 }}>{pct}%</div>
      <div className="prob-bar" style={{ width: 80 }}>
        <div className="prob-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

/** Highlights a favorite (prob > 0.5) in green/muted */
export function FavoriteCell({ value }) {
  if (value == null) return <>—</>
  const isFav = value > 0.5
  return (
    <span className={`tag ${isFav ? 'tag-green' : 'tag-muted'}`}>
      {isFav ? 'FAV' : 'DOG'}
    </span>
  )
}

/** Section header at top of every model page — cyan accent, Sora font */
export function PageHeader({ tag, title, subtitle }) {
  return (
    <div style={{
      marginBottom: '2rem',
      borderLeft:   '3px solid var(--accent)',
      paddingLeft:  '1.25rem',
    }}>
      {tag && (
        <div style={{
          fontFamily:    "'Inter', sans-serif",
          fontSize:      10,
          fontWeight:    600,
          color:         'var(--accent)',
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          marginBottom:  8,
        }}>
          {tag}
        </div>
      )}
      <h1 style={{
        fontFamily: "'Sora', sans-serif",
        fontWeight: 700,
        fontSize:   '2.4rem',
        color:      'var(--text)',
        lineHeight: 1.1,
        marginBottom: 8,
      }}>
        {title}
      </h1>
      {subtitle && (
        <p style={{
          fontFamily: "'Inter', sans-serif",
          fontSize:   14,
          color:      'var(--muted)',
          maxWidth:   560,
          lineHeight: 1.6,
        }}>
          {subtitle}
        </p>
      )}
    </div>
  )
}

/** Small stat box used on hub / index pages */
export function StatBox({ label, value, sub }) {
  return (
    <div style={{
      background:   'var(--navy-mid)',
      border:       '1px solid var(--accent)',
      boxShadow:    'inset 0 0 10px rgba(0,217,255,0.06)',
      borderRadius: 8,
      padding:      '1rem',
      transition:   'box-shadow 0.2s ease-out',
    }}>
      <div style={{
        fontFamily:    "'Inter', sans-serif",
        fontSize:      10,
        fontWeight:    600,
        color:         'var(--muted)',
        textTransform: 'uppercase',
        letterSpacing: '0.1em',
        marginBottom:  6,
      }}>
        {label}
      </div>
      <div style={{
        fontFamily: "'Sora', sans-serif",
        fontSize:   22,
        fontWeight: 700,
        color:      'var(--accent)',
      }}>
        {value}
      </div>
      {sub && (
        <div style={{
          fontFamily: "'Inter', sans-serif",
          fontSize:   11,
          color:      'var(--muted)',
          marginTop:  4,
        }}>
          {sub}
        </div>
      )}
    </div>
  )
}

/** Model card for hub / overview pages — cyan hover accent */
export function ModelCard({ title, description, href, tag }) {
  return (
    <a
      href={href}
      style={{
        display:      'block',
        textDecoration: 'none',
        background:   'var(--navy-mid)',
        border:       '1px solid var(--border)',
        borderRadius: 8,
        padding:      '1.25rem',
        transition:   'border-color 0.15s, background 0.15s, box-shadow 0.15s',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.borderColor = 'var(--accent)';
        e.currentTarget.style.background  = 'rgba(0,217,255,0.04)';
        e.currentTarget.style.boxShadow   = '0 0 20px rgba(0,217,255,0.12)';
      }}
      onMouseLeave={e => {
        e.currentTarget.style.borderColor = 'var(--border)';
        e.currentTarget.style.background  = 'var(--navy-mid)';
        e.currentTarget.style.boxShadow   = 'none';
      }}
    >
      {tag && (
        <div className="tag" style={{ marginBottom: 12 }}>
          {tag}
        </div>
      )}
      <h3 style={{
        fontFamily:   "'Sora', sans-serif",
        fontWeight:   700,
        fontSize:     '1.15rem',
        color:        'var(--text)',
        marginBottom: 8,
        lineHeight:   1.2,
      }}>
        {title}
      </h3>
      <p style={{
        fontFamily: "'Inter', sans-serif",
        fontSize:   13,
        color:      'var(--muted)',
        lineHeight: 1.6,
      }}>
        {description}
      </p>
      <div style={{
        fontFamily:    "'Inter', sans-serif",
        fontSize:      11,
        fontWeight:    600,
        color:         'var(--accent)',
        marginTop:     16,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
      }}>
        View Predictions →
      </div>
    </a>
  )
}
