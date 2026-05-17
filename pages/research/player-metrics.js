import Layout from '../../components/Layout'
import { PageHeader } from '../../components/PredictionTable'

export default function PlayerMetrics() {
  return (
    <Layout title="Player Metrics">
      <PageHeader
        tag="Research → Player Metrics"
        title="PLAYER METRICS"
        subtitle="Advanced individual player analytics and performance metrics. Coming soon."
      />

      <div style={{
        background:   'var(--navy-mid)',
        border:       '1px solid var(--navy-border)',
        borderRadius: 8,
        padding:      '40px 32px',
        textAlign:    'center',
        maxWidth:     560,
      }}>
        <div style={{
          fontFamily:    "'Sora', sans-serif",
          fontWeight:    700,
          fontSize:      11,
          letterSpacing: 2,
          textTransform: 'uppercase',
          color:         'var(--silver-dim)',
          marginBottom:  16,
        }}>
          Under Development
        </div>
        <p style={{ fontSize: 14, color: 'var(--silver)', lineHeight: 1.7, marginBottom: 12, fontFamily: "'Inter', sans-serif" }}>
          Player Metrics is in active development. Planned features include
          Statcast-based player profiles, rolling performance trends,
          platoon splits, and park-adjusted individual statistics.
        </p>
        <p style={{ fontSize: 13, color: 'var(--silver-dim)', lineHeight: 1.6, fontFamily: "'Inter', sans-serif" }}>
          Check back soon — this section will be enabled once the metrics
          are validated and ready for daily production runs.
        </p>
      </div>
    </Layout>
  )
}
