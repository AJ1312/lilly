const PATHS: Record<string, string> = {
  talk: 'M4 5h16v11H9l-5 4V5z',
  approve: 'M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3zM9 12l2 2 4-4',
  activity: 'M3 12h4l3-8 4 16 3-8h4',
  notes: 'M6 3h9l4 4v14H6V3zM14 3v5h5M9 13h7M9 17h7',
  memory: 'M12 3c-3 0-5 2-5 4.5-2 .5-3 2.200-3 4s1 3.500 3 4c.5 2.500 2.500 4.500 5 4.500s4.500-2 5-4.500c2-.5 3-2.200 3-4s-1-3.500-3-4C17 5 15 3 12 3zM12 3v18',
  agents: 'M12 4a3 3 0 100 6 3 3 0 000-6zM5 20c0-4 3-6 7-6s7 2 7 6',
  settings: 'M4 7h9M17 7h3M4 17h3M11 17h9M15 4v6M9 14v6',
  stop: 'M7 7h10v10H7z',
  send: 'M4 12l16-8-6 16-3-7-7-1z',
  plus: 'M12 5v14M5 12h14',
  trash: 'M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13M10 11v6M14 11v6',
  x: 'M6 6l12 12M18 6L6 18',
  check: 'M5 12l5 5L19 7',
  chevron: 'M9 6l6 6-6 6',
  up: 'M6 15l6-6 6 6',
  down: 'M6 9l6 6 6-6',
  lock: 'M6 11h12v9H6zM8 11V8a4 4 0 018 0v3',
  sun: 'M12 8a4 4 0 100 8 4 4 0 000-8zM12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.500 1.500M17.500 17.500L19 19M5 19l1.500-1.500M17.500 6.500L19 5',
  moon: 'M20 14A8 8 0 0110 4a8 8 0 1010 10z',
  menu: 'M4 7h16M4 12h16M4 17h16',
  edit: 'M4 20h4L19 9l-4-4L4 16v4zM14 6l4 4',
  download: 'M12 4v11M7 11l5 5 5-5M5 20h14',
  spark: 'M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2 2-6z',
  folder: 'M3 6h6l2 2h10v11H3V6z',
  globe: 'M12 3a9 9 0 100 18 9 9 0 000-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18',
  key: 'M8 11a4 4 0 100 8 4 4 0 000-8zM11 14l9-9M17 8l3 3M14 11l2 2',
  play: 'M8 5l11 7-11 7V5z',
  routines: 'M12 7v5l3 2M20 12a8 8 0 11-2.6-5.9M20 4v4h-4',
  gauge: 'M4 17a8 8 0 1116 0M12 17l4-6M7 17h.01M17 17h.01M12 8v.01',
  search: 'M11 4a7 7 0 100 14 7 7 0 000-14zM20 20l-4-4',
  shield: 'M12 3l8 3v6c0 5-4 8-8 9-4-1-8-4-8-9V6l8-3z',
}

export function Icon({ name, size = 18 }: { name: keyof typeof PATHS | string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name] ?? PATHS.spark} />
    </svg>
  )
}

/** The lily: four petals around a centre. Used as the mark in the corner and on the sign-in page. */
export function Petals({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <g fill="currentColor">
        <path d="M32 6c6.500 8.500 7.500 16 0 26-7.500-10-6.500-17.500 0-26z" />
        <path d="M32 32c10-3.500 18.500-2.500 26 4-10 6.500-18.500 5.500-26-4z" opacity=".85" />
        <path d="M32 32c-10-3.500-18.500-2.500-26 4 10 6.500 18.500 5.500 26-4z" opacity=".85" />
        <path d="M32 32c5.500 9 5.500 17.500 0 26-5.500-8.500-5.500-17 0-26z" opacity=".65" />
      </g>
    </svg>
  )
}
