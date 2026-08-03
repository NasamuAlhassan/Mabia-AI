import assert from 'node:assert/strict'
import test from 'node:test'
import { install } from './fake-idb.mjs'

install()
const { outbox, flush, uuid7 } = await import('../src/db.js')

const event = (type, payload = {}) => ({
  event_type: type, payload, occurred_at: new Date().toISOString(),
})

test('work the server refuses is kept, not deleted', async () => {
  const enrolment = await outbox.add(event('enrolment', { name: 'Amina' }))
  const visit = await outbox.add(event('visit_recorded'))

  // The server takes the visit and refuses the enrolment by name.
  const post = async () => ({
    accepted: 1, duplicates: 0, patients_refolded: 1,
    rejected: [{ event_id: enrolment.event_id,
                 reason: 'enrolment missing name or phone' }],
  })

  const out = await flush(post)
  assert.equal(out.sent, 1)
  assert.equal(out.refused, 1)

  const left = await outbox.all()
  assert.equal(left.length, 1, 'the refused record was deleted from the only copy of it')
  assert.equal(left[0].event_id, enrolment.event_id)
  assert.match(left[0].rejected_reason, /missing name or phone/)

  // And it is not counted as "waiting to send" -- waiting will not fix it.
  assert.equal((await outbox.sendable()).length, 0)
  assert.equal((await outbox.rejected()).length, 1)
})

test('a refused record is never silently retried forever', async () => {
  let calls = 0
  const post = async () => { calls += 1; return { accepted: 0, rejected: [] } }
  await flush(post)
  assert.equal(calls, 0, 'it was sent again despite the server having refused it')
})

test('a clean batch is cleared and nothing lingers', async () => {
  const fresh = await outbox.add(event('visit_recorded'))
  const post = async () => ({ accepted: 1, duplicates: 0, rejected: [] })
  const out = await flush(post)
  assert.equal(out.sent, 1)
  const ids = (await outbox.all()).map(e => e.event_id)
  assert.ok(!ids.includes(fresh.event_id))
})

test('a network failure mid-flush keeps everything queued', async () => {
  const queued = await outbox.add(event('visit_recorded'))
  const post = async () => { throw new Error('offline') }
  await assert.rejects(flush(post))
  const ids = (await outbox.all()).map(e => e.event_id)
  assert.ok(ids.includes(queued.event_id), 'work vanished when the link dropped')
})

test('ids are time-sortable, so replay order is chronological order', async () => {
  const ids = []
  for (let i = 0; i < 40; i++) ids.push(uuid7())
  assert.deepEqual([...ids].sort(), ids, 'uuid7 is not lexically time-ordered')
  assert.equal(new Set(ids).size, ids.length, 'collision')
  for (const id of ids) {
    assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  }
})

test('events written in the same millisecond keep their order', async () => {
  const { outbox, uuid7 } = await import('../src/db.js')
  // Freeze the clock: every id below is minted in "the same millisecond",
  // which is what actually happens when one visit form is submitted.
  const realNow = Date.now
  Date.now = () => 1754200000000
  try {
    const ids = Array.from({ length: 500 }, () => uuid7())
    assert.deepEqual([...ids].sort(), ids,
      'same-millisecond ids do not sort into the order they were created')
    assert.equal(new Set(ids).size, ids.length)

    const seqs = []
    for (let i = 0; i < 3; i++) {
      seqs.push((await outbox.add({
        event_type: 'visit_recorded', payload: {},
        occurred_at: new Date(1754200000000).toISOString(),
      })).seq)
    }
    assert.deepEqual(seqs, [...seqs].sort((a, b) => a - b))
    assert.equal(new Set(seqs).size, 3,
      'every event carried the same seq, so the server had no tiebreak')
  } finally {
    Date.now = realNow
  }
})
