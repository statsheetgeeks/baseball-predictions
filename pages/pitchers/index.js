import Layout from '../../components/Layout'
import { PageHeader } from '../../components/PredictionTable'

export default function PitchersHub() {
  return (
    <Layout title="Pitcher Predictions">
      <PageHeader
        tag="Pitchers"
        title="PITCHER PREDICTIONS"
        subtitle="Projection models for starting pitcher performance. Coming soon."
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
          fontFamily:    "'Barlow Condensed', sans-serif",
          fontWeight:    700,
          fontSize:      13,
          letterSpacing: 2,
          textTransform: 'uppercase',
          color:         'var(--silver-dim)',
          marginBottom:  16,
        }}>
          Under Development
        </div>
        <p style={{ fontSize: 14, color: 'var(--silver)', lineHeight: 1.7, marginBottom: 12 }}>
          Pitcher models are in active development. Planned features include
          strikeout projections, ERA estimators, and pitching matchup analysis
          using Statcast whiff rate, chase rate, and batter handedness splits.
        </p>
        <p style={{ fontSize: 13, color: 'var(--silver-dim)', lineHeight: 1.6 }}>
          Check back soon — this section will be enabled once the models are
          validated and ready for daily production runs.
        </p>
      </div>
    </Layout>
  )
}
