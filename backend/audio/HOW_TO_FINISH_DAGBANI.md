# Finishing the Dagbani voice

The platform speaks Dagbani on a real call. One line so far — `danger_bleeding`
— generated through Khaya Studio and verified playing through the call flow.
This is how to finish the rest, and what stopped it.

## What happened

Khaya's **TTS API endpoint** returns a hosting error page and is unavailable.
Khaya **Studio** does have Dagbani text-to-speech, and it works. Both draw on
the same account credits, and this account is now out of them:

```
POST /api/translate     429  "no credits remaining for this browser session"
POST /api/tts/generate  429  same
```

Translation does not matter for Dagbani — all 79 lines are already translated
and committed. What is left is synthesis.

## When credits return

1. Sign in to `studio.khaya.ai` in Chrome.
2. Open the Text to Speech tab once, so the session is live.
3. From the browser console on that page, define the generator:

```js
window.__gen = async function (items) {
  const out = [];
  for (const item of items) {
    const r = await fetch('/api/tts/generate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: item.text, language: 'dag',
                             speaker_id: 'female', stream: false, format: 'mp3' })
    });
    if (r.status === 429) { out.push('out of credits — stopping'); break; }
    if (!r.ok) { out.push(item.key + ': HTTP ' + r.status); continue; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = item.key + '.mp3';
    document.body.appendChild(a); a.click(); a.remove();
    out.push(item.key + ': ' + blob.size);
    await new Promise(res => setTimeout(res, 2000));   // pace it
  }
  return out;
};
```

4. Get the outstanding lines:

```bash
cd backend && .venv/bin/python -c "
import json
from app.db import SessionLocal
from app.language.pipeline import MAX_SPOKEN_CHARS
from app.models import Phrase
db = SessionLocal()
rows = db.query(Phrase).filter(Phrase.language=='dagbani',
                               Phrase.audio_path.is_(None),
                               Phrase.translated_text.isnot(None)).all()
print(json.dumps([{'key': r.key, 'text': r.translated_text} for r in rows
                  if len(r.translated_text) <= MAX_SPOKEN_CHARS],
                 ensure_ascii=False))"
```

5. Paste that array into `await window.__gen([...])`.
6. File the results:

```bash
cd backend && .venv/bin/python file_studio_batch.py dagbani
```

The clips land in `backend/audio/dagbani/` and the call flow picks them up with
no further change — it already prefers a clip over spoken English.

## Nine lines need shortening first

Khaya refuses text much over 100 characters: 100 succeeds, 120 returns HTTP 400.
Nine translated lines exceed that and cannot be synthesised as one clip.

That limit is inconvenient and also correct. A prompt too long to synthesise in
one breath is a prompt a woman on a poor line was never going to absorb in one
breath either. `pipeline.status()` reports these under `too_long`, and the
answer is to shorten the **English** and re-translate, not to work around it.
The greeting is the worst offender at 148 characters and should be split into a
greeting and a separate "press 9 for a nurse" line.

## Do not try to defeat the quota

The 429 is the service saying no. Wait for it to replenish, or record the lines
with a human voice through the Voice screen — which is better anyway, and which
the platform already prefers over anything generated.
