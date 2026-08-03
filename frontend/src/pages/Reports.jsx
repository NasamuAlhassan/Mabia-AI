import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Metrics from './Metrics'
import Nutrition from './Nutrition'
import * as I from '../components/Icons'

// Two reports that answer different questions, behind one word in the rail.
//
// Indicators answer "is the programme working". Nutrition answers "what is
// happening in these households, and did the advice land". A supervisor wants
// the first; a nutrition officer lives in the second.

export default function Reports() {
  const [params, setParams] = useSearchParams()
  const view = params.get('view') === 'nutrition' ? 'nutrition' : 'indicators'
  const set = (v) => setParams(v === 'indicators' ? {} : { view: v })

  return (
    <>
      <h1>Reports</h1>
      <p className="sub">
        What the programme is achieving, and what the households are eating.
      </p>

      <div className="row" style={{ gap: 8, marginBottom: 16 }}>
        <button className={view === 'indicators' ? 'primary' : ''}
                onClick={() => set('indicators')}>
          <I.Chart size={16} /> Indicators
        </button>
        <button className={view === 'nutrition' ? 'primary' : ''}
                onClick={() => set('nutrition')}>
          <I.Baby size={16} /> Nutrition
        </button>
      </div>

      {view === 'indicators' ? <Metrics /> : <Nutrition />}
    </>
  )
}
