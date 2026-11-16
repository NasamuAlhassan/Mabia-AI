import { useRef } from 'react'

// A pill-shaped tab group: the same shape as the main navigation, so a person
// who has learned one has learned both. Arrow keys move between tabs, which is
// what a tablist promises and what a row of plain buttons never delivered.

export default function Tabs({ value, onChange, items, label, quiet = false }) {
  const refs = useRef({})

  function onKey(e, index) {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
    if (!step) return
    e.preventDefault()
    const next = items[(index + step + items.length) % items.length]
    onChange(next.key)
    refs.current[next.key]?.focus()
  }

  return (
    <div className={`seg ${quiet ? 'quiet' : ''}`} role="tablist" aria-label={label}>
      {items.map(({ key, label: text, Icon }, i) => {
        const on = value === key
        return (
          <button key={key} role="tab" type="button"
                  ref={el => { refs.current[key] = el }}
                  aria-selected={on} tabIndex={on ? 0 : -1}
                  className={on ? 'on' : ''}
                  onKeyDown={e => onKey(e, i)}
                  onClick={() => onChange(key)}>
            {Icon && <Icon size={16} />}
            {text}
          </button>
        )
      })}
    </div>
  )
}
