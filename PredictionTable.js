/**
 * PredictionTable + helper cells — Chalk Line Labs palette
 */

export function ProbCell({ value }) {
  if (value == null) return <span style={{ color: 'var(--silver-dim)' }}>—</span>;
  const pct   = Math.round(value * 100);
  const color = pct >= 60 ? '#4fc97e' : pct <= 40 ? 'var(--red)' : 'var(--yellow)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{
        width: 52,
        height: 4,
        background: 'var(--navy-border)',
        borderRadius: 2,
        overflow: 'hidden',
      }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 2 }} />
      </div>
      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 13, color }}>
        {pct}%
      </span>
    </div>
  );
}

export function FavoriteCell({ value }) {
  if (!value) return <span style={{ color: 'var(--silver-dim)' }}>—</span>;
  const isFav = String(value).toUpperCase() === 'FAV';
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 9px',
      borderRadius: 4,
      fontSize: 11,
      fontWeight: 700,
      fontFamily: "'DM Mono', monospace",
      letterSpacing: 1,
      background: isFav ? 'rgba(79,201,126,0.12)' : 'rgba(224,84,84,0.12)',
      color:      isFav ? '#4fc97e' : 'var(--red)',
      border:     `1px solid ${isFav ? '#1d4f33' : '#5a2020'}`,
    }}>
      {isFav ? 'FAV' : 'DOG'}
    </span>
  );
}

export default function PredictionTable({ columns, data, loading, error, updated }) {
  if (loading) {
    return (
      <div style={{
        padding: '60px 0',
        textAlign: 'center',
        color: 'var(--silver-dim)',
        fontFamily: "'DM Mono', monospace",
        fontSize: 13,
      }}>
        Loading predictions…
      </div>
    );
  }

  if (error) {
    return (
      <div style={{
        background: 'rgba(224,84,84,0.08)',
        border: '1px solid rgba(224,84,84,0.3)',
        borderRadius: 8,
        padding: '16px 20px',
        color: 'var(--red)',
        fontFamily: "'DM Mono', monospace",
        fontSize: 13,
      }}>
        ⚠ {error}
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div style={{ padding: '60px 0', textAlign: 'center', color: 'var(--silver-dim)' }}>
        No predictions available yet.
      </div>
    );
  }

  return (
    <div>
      {updated && (
        <div style={{
          fontSize: 11,
          color: 'var(--silver-dim)',
          fontFamily: "'DM Mono', monospace",
          marginBottom: 16,
        }}>
          Last updated: {new Date(updated).toLocaleString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric',
            hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
          })}
        </div>
      )}

      <div style={{
        background: 'var(--navy)',
        border: '1px solid var(--navy-border)',
        borderRadius: 10,
        overflow: 'hidden',
      }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--navy-border)', background: 'rgba(255,255,255,0.03)' }}>
                {columns.map(col => (
                  <th key={col.key} style={{
                    padding: '11px 16px',
                    textAlign: 'left',
                    fontFamily: "'Barlow Condensed', sans-serif",
                    fontWeight: 700,
                    fontSize: 12,
                    letterSpacing: 1.2,
                    textTransform: 'uppercase',
                    color: 'var(--silver-dim)',
                    whiteSpace: 'nowrap',
                  }}>
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row, i) => (
                <tr key={i} style={{
                  borderBottom: i < data.length - 1 ? '1px solid rgba(44,62,94,0.6)' : 'none',
                  transition: 'background 0.1s',
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(74,144,217,0.06)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  {columns.map(col => (
                    <td key={col.key} style={{ padding: '12px 16px', whiteSpace: 'nowrap' }}>
                      {col.render ? col.render(row[col.key], row) : (row[col.key] ?? '—')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{ marginTop: 10, fontSize: 12, color: 'var(--silver-dim)' }}>
        {data.length} prediction{data.length !== 1 ? 's' : ''}
      </div>
    </div>
  );
}
