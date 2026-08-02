import { useEffect, useRef, useState } from 'react'
import { get, post, put, upload } from '../api'

// The voice workbench.
//
// Every line the platform says, in every language, with its English source, its
// Khaya translation, and whatever audio exists. A speaker can correct the
// machine's wording and record over it in the browser — and a recorded human
// take always beats a generated one, because it is more trustworthy and because
// re-running the pipeline must not undo an evening in a recording room.

const LANGUAGES = [
  { key: 'dagbani', label: 'Dagbani' },
  { key: 'kusaal', label: 'Kusaal' },
  { key: 'frafra', label: 'Frafra' },
  { key: 'gonja', label: 'Gonja' },
]

const CATEGORIES = [
  { key: '', label: 'Everything' },
  { key: 'script', label: 'Call script' },
  { key: 'diet', label: 'Diet questions' },
  { key: 'food', label: 'Nutrition advice' },
]

export default function Voice() {
  const [language, setLanguage] = useState('dagbani')
  const [category, setCategory] = useState('script')
  const [overview, setOverview] = useState(null)
  const [rows, setRows] = useState([])
  const [busy, setBusy] = useState('')
  const [flash, setFlash] = useState(null)

  async function load() {
    try {
      const [status, phrases] = await Promise.all([
        get('/api/language/status'),
        get(`/api/language/phrases?language=${language}` +
            (category ? `&category=${category}` : '')),
      ])
      setOverview(status)
      setRows(phrases.phrases)
    } catch (e) {
      setFlash({ bad: true, text: e.message === 'offline'
        ? 'No connection — the voice workbench needs the server.' : e.message })
    }
  }

  useEffect(() => { load() }, [language, category])

  const here = overview?.languages?.find(l => l.language === language)

  async function run(action, label) {
    setBusy(action); setFlash(null)
    try {
      const out = await post(`/api/language/${action}?language=${language}`)
      if (action === 'translate') {
        setFlash(out.translated
          ? { text: `Translated ${out.translated} lines. ${out.remaining} left.` }
          : { bad: true, text: out.errors?.[0] || out.note || 'Nothing translated.' })
      } else {
        setFlash(out.generated
          ? { text: `Generated ${out.generated} clips.` }
          : { warn: true, text: out.note || 'No audio generated.' })
      }
      await load()
    } catch (e) {
      setFlash({ bad: true, text: e.message })
    } finally { setBusy('') }
  }

  return (
    <>
      <h1>Voice</h1>
      <p className="muted">
        What the platform says out loud, and in which languages it can actually
        say it.
      </p>

      {flash && (
        <div className={`notice ${flash.bad ? 'bad' : flash.warn ? 'warn' : 'ok'}`}
             role="status">{flash.text}</div>
      )}

      <div className="chips" style={{ marginBottom: '.8rem' }}>
        {LANGUAGES.map(l => (
          <button key={l.key} className={`chip ${language === l.key ? 'on' : ''}`}
                  aria-pressed={language === l.key}
                  onClick={() => setLanguage(l.key)}>{l.label}</button>
        ))}
      </div>

      {here && (
        <div className="card">
          <div className="row">
            <h2 style={{ margin: 0 }}>{LANGUAGES.find(l => l.key === language).label}</h2>
            <span className="spacer" />
            <span className={`badge ${here.spoken_coverage > 0 ? 'green' : 'amber'}`}>
              {here.spoken_coverage}% spoken
            </span>
          </div>

          <div className="counts" style={{ marginTop: '.7rem' }}>
            <div className="count">
              <div className="n">{here.translated}</div>
              <div className="l">translated</div>
            </div>
            <div className="count green">
              <div className="n">{here.with_audio}</div>
              <div className="l">with audio</div>
            </div>
            <div className="count amber">
              <div className="n">{here.needs_recording}</div>
              <div className="l">to record</div>
            </div>
          </div>

          {here.note && <div className="notice warn">{here.note}</div>}

          <p className="muted tiny">
            {here.recorded_by_human} of {here.with_audio || 0} clips are a human
            voice. Anything without audio falls back to spoken English on a real
            call — so “{here.needs_recording} to record” is the honest measure of
            how much of this language the platform can speak today.
          </p>

          {here.can_translate && (
            <div className="row wrap" style={{ gap: '.5rem', marginTop: '.6rem' }}>
              <button onClick={() => run('translate')} disabled={!!busy}>
                {busy === 'translate' ? <span className="spin" /> : 'Translate with Khaya'}
              </button>
              <button onClick={() => run('speak')} disabled={!!busy}>
                {busy === 'speak' ? <span className="spin" /> : 'Generate speech'}
              </button>
              <a className="btn" href={`/api/language/recording-pack?language=${language}`}
                 target="_blank" rel="noreferrer">Recording list</a>
            </div>
          )}
        </div>
      )}

      <div className="chips" style={{ marginBottom: '.8rem' }}>
        {CATEGORIES.map(c => (
          <button key={c.key} className={`chip ${category === c.key ? 'on' : ''}`}
                  aria-pressed={category === c.key}
                  onClick={() => setCategory(c.key)}>{c.label}</button>
        ))}
      </div>

      <div className="list">
        {rows.map(p => <PhraseRow key={p.id} phrase={p} onChange={load} />)}
        {rows.length === 0 && (
          <div className="card muted">Nothing in this category yet.</div>
        )}
      </div>
    </>
  )
}

function PhraseRow({ phrase, onChange }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(phrase.translated || '')
  const [recording, setRecording] = useState(false)
  const [error, setError] = useState('')
  const recorder = useRef(null)
  const chunks = useRef([])

  async function startRecording() {
    setError('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mr = new MediaRecorder(stream)
      chunks.current = []
      mr.ondataavailable = e => chunks.current.push(e.data)
      mr.onstop = async () => {
        stream.getTracks().forEach(t => t.stop())
        const blob = new Blob(chunks.current, { type: mr.mimeType })
        try {
          await upload(`/api/language/phrases/${phrase.id}/audio`, blob,
                       `${phrase.key}.wav`)
          onChange()
        } catch (e) { setError(e.message) }
      }
      mr.start()
      recorder.current = mr
      setRecording(true)
    } catch {
      // Denied, or no microphone. Say which, rather than failing silently.
      setError('No microphone access. Allow it in the browser, or upload a file.')
    }
  }

  function stopRecording() {
    recorder.current?.stop()
    setRecording(false)
  }

  async function save() {
    try {
      await put(`/api/language/phrases/${phrase.id}`, { translated_text: text })
      setEditing(false)
      onChange()
    } catch (e) { setError(e.message) }
  }

  const state = phrase.audio_url
    ? (phrase.audio_source === 'recorded' ? 'recorded' : 'synthesised')
    : phrase.translated ? 'needs a voice' : phrase.status

  return (
    <div className="card tight">
      <div className="row">
        <code className="tiny muted">{phrase.key}</code>
        <span className="spacer" />
        <span className={`badge ${
          state === 'recorded' ? 'green' : state === 'needs a voice' ? 'amber' : 'plain'
        }`}>{state}</span>
      </div>

      <div className="muted tiny" style={{ margin: '.35rem 0' }}>{phrase.english}</div>

      {editing ? (
        <>
          <textarea id={`t-${phrase.id}`} value={text}
                    onChange={e => setText(e.target.value)}
                    aria-label={`Translation for ${phrase.english}`} />
          <div className="row" style={{ gap: '.4rem', marginTop: '.4rem' }}>
            <button className="primary small" onClick={save}>Save</button>
            <button className="small" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </>
      ) : (
        <div style={{ fontSize: '1.02rem' }}>
          {phrase.translated || <span className="muted">— not translated —</span>}
        </div>
      )}

      {phrase.error && <div className="tiny" style={{ color: 'var(--red)' }}>{phrase.error}</div>}
      {error && <div className="tiny" style={{ color: 'var(--red)' }}>{error}</div>}

      {phrase.audio_url && (
        <audio controls preload="none" src={phrase.audio_url}
               style={{ width: '100%', marginTop: '.5rem' }} />
      )}

      <div className="row wrap" style={{ gap: '.4rem', marginTop: '.5rem' }}>
        {!editing && phrase.translated && (
          <button className="small" onClick={() => setEditing(true)}>Correct wording</button>
        )}
        {recording ? (
          <button className="danger small" onClick={stopRecording}>■ Stop</button>
        ) : (
          <button className="small" onClick={startRecording}>● Record</button>
        )}
      </div>
    </div>
  )
}
