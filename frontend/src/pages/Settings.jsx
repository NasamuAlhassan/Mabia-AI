import { useSearchParams } from 'react-router-dom'
import Setup from './Setup'
import Simulator from './Simulator'
import Voice from './Voice'
import Tabs from '../components/Tabs'
import * as I from '../components/Icons'

// Everything operational, and nothing clinical.
//
// The call simulator lives here rather than in the rail: a CHO has no reason to
// answer a simulated handset, and giving a developer tool a fifth of her
// primary navigation told anyone looking that the app is a demo harness.

export default function Settings() {
  const [params, setParams] = useSearchParams()
  const view = ['voice', 'calls'].includes(params.get('view'))
    ? params.get('view') : 'service'
  const set = (v) => setParams(v === 'service' ? {} : { view: v })

  return (
    <>
      <h1>Settings</h1>
      <p className="sub">
        Telephony, language and the tools for proving the flow without a SIM.
      </p>

      <Tabs label="Settings" value={view} onChange={set} items={[
        { key: 'service', label: 'Service', Icon: I.Gear },
        { key: 'voice', label: 'Voice', Icon: I.Radio },
        { key: 'calls', label: 'Test calls', Icon: I.Phone },
      ]} />

      <div className="view">
        {view === 'service' && <Setup />}
        {view === 'voice' && <Voice />}
        {view === 'calls' && <Simulator />}
      </div>
    </>
  )
}
