// One place that knows how a Ghanaian phone number is written.
//
// The server stores E.164 (+233240000001) because that is what the network
// needs. Nobody here writes a number that way. A CHO checking a handset
// against a scrap of paper reads 024 000 0001, and asking her to do that
// translation in her head is how numbers get mistyped in the first place.
//
// tel: links keep the E.164 form — that is what the dialler wants.

export function display(raw) {
  if (!raw) return ''
  const digits = String(raw).replace(/[^\d+]/g, '')
  if (!digits.startsWith('+233')) return raw
  const national = digits.slice(4)
  if (national.length !== 9) return digits
  return `0${national.slice(0, 2)} ${national.slice(2, 5)} ${national.slice(5)}`
}
