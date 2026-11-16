// The languages a household can be called in, in the order they are offered.
//
// Static for the same reason as regions.js: the enrolment form has to work with
// no signal. A backend test reads this file and fails if it differs from
// backend/app/prompts.py::LANGUAGES, so adding a language on one side and
// forgetting the other cannot ship.
//
// Dagbani, Kusaal and Frafra are the Mabia languages the platform began with.
// Gonja has no translation or speech model anywhere and is a recorded human
// voice only. Twi, Ewe and Hausa are served by our own language service.
export const LANGUAGES = [
  { key: 'dagbani', label: 'Dagbani' },
  { key: 'kusaal', label: 'Kusaal' },
  { key: 'frafra', label: 'Frafra' },
  { key: 'gonja', label: 'Gonja' },
  { key: 'twi', label: 'Twi' },
  { key: 'ewe', label: 'Ewe' },
  { key: 'hausa', label: 'Hausa' },
  { key: 'english', label: 'English' },
]

// The Voice workbench manages recorded prompts. English is the source text and
// is never translated, recorded or synthesised there.
export const VOICE_LANGUAGES = LANGUAGES.filter(l => l.key !== 'english')
