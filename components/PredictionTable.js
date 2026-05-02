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
      <div style={{ padding: '3rem', textAlign: 'center', fontFamily: 'var(--font-m)', color: 'var(--muted)', fontSize: 13 }}>
        Loading predictions…
      </div>
    )
  }

  if (error) {
    return (
      <div style={{
        padding: '1.5rem', background: 'rgba(192,57,43,0.08)', border: '1px solid var(--red)',
        borderRadius: 6, fontFamily: 'var(--font-m)', fontSize: 12, color: 'var(--red)',
      }}>
        {error}
      </div>
    )
  }

  if (!data.length) {
    return (
      <div style={{ padding: '2rem', fontFamily: 'var(--font-m)', color: 'var(--muted)', fontSize: 12 }}>
        No prediction data found. Run your models to generate predictions.
      </div>
    )
  }

  return (
    <div>
      {/* Table meta */}
      {updated && (
        <div style={{ marginBottom: 12, fontFamily: 'var(--font-m)', fontSize: 11, color: 'var(--muted)' }}>
          Last updated: <span style={{ color: 'var(--text)' }}>{new Date(updated).toLocaleString()}</span>
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

/* ── Reusable cell renderers ── */

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

/** Highlights a favorite (prob > 0.5) in red/green */
export function FavoriteCell({ value }) {
  if (value == null) return <>—</>
  const isFav = value > 0.5
  return (
    <span className={`tag ${isFav ? 'tag-green' : 'tag-muted'}`}>
      {isFav ? 'FAV' : 'DOG'}
    </span>
  )
}

/** Section header used at top of every model page */
export function PageHeader({ tag, title, subtitle }) {
  return (
    <div style={{ marginBottom: '2rem', borderLeft: '3px solid var(--red)', paddingLeft: '1.25rem' }}>
      {tag && (
        <div className="mono" style={{ fontSize: 10, color: 'var(--red)', letterSpacing: '0.12em',
                                       textTransform: 'uppercase', marginBottom: 8 }}>
          {tag}
        </div>
      )}
      <h1 className="display" style={{ fontSize: '2.4rem', color: 'var(--text)', lineHeight: 1.1, marginBottom: 8 }}>
        {title}
      </h1>
      {subtitle && (
        <p style={{ fontSize: 14, color: 'var(--muted)', maxWidth: 560, lineHeight: 1.6 }}>{subtitle}</p>
      )}
    </div>
  )
}

/** Small stat box used on hub/index pages */
export function StatBox({ label, value, sub }) {
  return (
    <div style={{
      background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, padding: '1rem',
    }}>
      <div className="mono" style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase',
                                     letterSpacing: '0.1em', marginBottom: 6 }}>
        {label}
      </div>
      <div className="mono" style={{ fontSize: 22, color: 'var(--text)', fontWeight: 600 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

/** Model card for hub pages */
export function ModelCard({ title, description, href, tag }) {
  return (
    <a href={href} style={{
      display: 'block', textDecoration: 'none',
      background: 'var(--card)', border: '1px solid var(--border)',
      borderRadius: 8, padding: '1.25rem',
      transition: 'border-color 0.15s, background 0.15s',
    }}
    onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--red)'; e.currentTarget.style.background = '#1e2a28'; }}
    onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.background = 'var(--card)'; }}>
      {tag && <div className="tag" style={{ marginBottom: 12 }}>{tag}</div>}
      <h3 className="display" style={{ fontSize: '1.2rem', color: 'var(--text)', marginBottom: 8 }}>{title}</h3>
      <p style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.6 }}>{description}</p>
      <div className="mono" style={{ fontSize: 11, color: 'var(--red)', marginTop: 16, letterSpacing: '0.08em' }}>
        VIEW PREDICTIONS →
      </div>
    </a>
  )
}
