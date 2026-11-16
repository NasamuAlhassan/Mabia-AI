import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Metrics from './Metrics'
import Nutrition from './Nutrition'
import Tabs from '../components/Tabs'
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

      <Tabs label="Reports" value={view} onChange={set} items={[
        { key: 'indicators', label: 'Indicators', Icon: I.Chart },
        { key: 'nutrition', label: 'Nutrition', Icon: I.Baby },
      ]} />

      <div className="view">
        {view === 'indicators' ? <Metrics /> : <Nutrition />}
      </div>
    </>
  )
}
