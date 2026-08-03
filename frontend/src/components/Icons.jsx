// Line icons, drawn rather than fetched.
//
// An icon font or an SVG sprite is another request on a link that may not
// complete, and these render at any size without one. Stroke-based so they
// stay legible at 16px on a cheap screen.

const S = ({ children, size = 18, ...rest }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
       stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
       strokeLinejoin="round" aria-hidden="true" {...rest}>{children}</svg>
)

export const Home = (p) => <S {...p}><path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.5V21h14V9.5" /></S>
export const People = (p) => <S {...p}><circle cx="9" cy="8" r="3.2" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><path d="M16 5.3a3.2 3.2 0 0 1 0 5.4" /><path d="M17.5 14.2A6.5 6.5 0 0 1 21.5 20" /></S>
export const Calendar = (p) => <S {...p}><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></S>
export const Chart = (p) => <S {...p}><path d="M5 20V10M12 20V4M19 20v-7" /></S>
export const Gear = (p) => <S {...p}><circle cx="12" cy="12" r="3.2" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></S>
export const Warning = (p) => <S {...p}><path d="M10.3 3.9 1.9 18a2 2 0 0 0 1.7 3h16.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4M12 17h.01" /></S>
export const Bell = (p) => <S {...p}><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 0 1-3.4 0" /></S>
export const Search = (p) => <S {...p} size={p.size || 16}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></S>
export const Chevron = (p) => <S {...p} size={p.size || 16}><path d="m9 18 6-6-6-6" /></S>
export const Back = (p) => <S {...p}><path d="M19 12H5M12 19l-7-7 7-7" /></S>
export const Burger = (p) => <S {...p} size={p.size || 20}><path d="M3 6h18M3 12h18M3 18h18" /></S>
export const Cloud = (p) => <S {...p} size={p.size || 15}><path d="M17.5 19a4.5 4.5 0 0 0 .5-9 6 6 0 0 0-11.6-1.6A4 4 0 0 0 6.5 19z" /></S>
export const Signal = (p) => <S {...p} size={p.size || 15}><path d="M4 20v-4M9 20v-8M14 20v-12M19 20V4" /></S>
export const Radio = (p) => <S {...p}><circle cx="12" cy="12" r="2.4" /><path d="M7.8 16.2a6 6 0 0 1 0-8.4M16.2 7.8a6 6 0 0 1 0 8.4" /><path d="M4.9 19.1a10 10 0 0 1 0-14.2M19.1 4.9a10 10 0 0 1 0 14.2" /></S>
export const Bolt = (p) => <S {...p}><path d="M13 2 4 14h7l-1 8 9-12h-7z" /></S>
export const AddPerson = (p) => <S {...p}><circle cx="9" cy="8" r="3.2" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><path d="M18 8v6M21 11h-6" /></S>
export const Phone = (p) => <S {...p} size={p.size || 16}><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.2a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z" /></S>
export const Pin = (p) => <S {...p} size={p.size || 16}><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z" /><circle cx="12" cy="10" r="2.6" /></S>
export const Clock = (p) => <S {...p} size={p.size || 16}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></S>
export const Drop = (p) => <S {...p} size={p.size || 16}><path d="M12 2.7 6.9 8.4a7 7 0 1 0 10.2 0z" /></S>
export const Baby = (p) => <S {...p} size={p.size || 16}><circle cx="12" cy="12" r="9" /><path d="M9 10h.01M15 10h.01M9 15a4 4 0 0 0 6 0" /></S>
export const Car = (p) => <S {...p} size={p.size || 16}><path d="M5 17h14M6.5 17V9.5l1.8-3.4A2 2 0 0 1 10 5h4a2 2 0 0 1 1.7 1.1l1.8 3.4V17" /><circle cx="8" cy="17" r="1.6" /><circle cx="16" cy="17" r="1.6" /></S>
export const Card = (p) => <S {...p} size={p.size || 16}><rect x="2.5" y="5.5" width="19" height="13" rx="2" /><path d="M2.5 10h19" /></S>
export const Note = (p) => <S {...p}><path d="M5 3h9l5 5v13H5z" /><path d="M14 3v5h5" /></S>
export const Check = (p) => <S {...p} size={p.size || 15}><path d="m4 12 5 5L20 6" /></S>
export const Circle = (p) => <S {...p}><circle cx="12" cy="12" r="9" /><path d="M12 8v4l2.5 2" /></S>
export const Help = (p) => <S {...p}><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.6 2.6 0 0 1 5 .9c0 1.7-2.5 2.1-2.5 3.6M12 17.5h.01" /></S>
export const Info = (p) => <S {...p}><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></S>
export const Download = (p) => <S {...p} size={p.size || 16}><path d="M12 3v12M7.5 10.5 12 15l4.5-4.5" /><path d="M4 20h16" /></S>
export const Logo = ({ size = 34 }) => (
  <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <path d="M16 3 5 7.2v7.6c0 6.9 4.6 12.4 11 14.2 6.4-1.8 11-7.3 11-14.2V7.2z"
          stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
    <path d="M16 20.5s-4.6-2.9-4.6-6a2.6 2.6 0 0 1 4.6-1.7 2.6 2.6 0 0 1 4.6 1.7c0 3.1-4.6 6-4.6 6z"
          fill="currentColor" />
  </svg>
)
