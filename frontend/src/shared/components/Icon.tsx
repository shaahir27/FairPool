const PATHS = {
  search: "M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0 M15 15l6 6",
  layers: "M12 3L2 8l10 5 10-5z M2 12l10 5 10-5 M2 16l10 5 10-5",
  bag: "M4 7h16l1 14H3z M8 8V6a4 4 0 0 1 8 0v2",
  settings: "M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M19 5l-2 2 M7 17l-2 2",
  wallet: "M3 5h16v4 M3 5v15h18V9H3z M16 13h5v4h-5z",
  chevron: "M9 5l7 7-7 7",
  down: "M5 9l7 7 7-7",
  menu: "M4 6h16 M4 12h16 M4 18h16",
  mail: "M3 5h18v14H3z M3 6l9 7 9-7",
  lock: "M7 10V7a5 5 0 0 1 10 0v3 M5 10h14v11H5z",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  user: "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M4 22v-3a8 8 0 0 1 16 0v3",
  arrow: "M5 12h14 M13 6l6 6-6 6",
  close: "M6 6l12 12 M18 6L6 18",
  logout: "M9 4H3v16h6 M9 12h12 M16 7l5 5-5 5",
  copy: "M8 8h12v13H8z M16 8V3H3v13h5",
  receipt: "M5 2h14v20l-3-2-4 2-4-2-3 2z M8 7h8 M8 11h8 M8 15h5",
  check: "M4 12l5 5L20 6",
  box: "M3 7l9-5 9 5v10l-9 5-9-5z M3 7l9 5 9-5 M12 12v10",
  truck: "M2 5h12v12H2z M14 9h5l3 4v4h-8 M8 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0 M20 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0",
  returns: "M3 3v6h6 M3 9a9 9 0 1 1-1 6",
  clock: "M9 2h6 M12 8v5l3 2 M21 13a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  info: "M12 11v6 M12 7h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  shield: "M12 2l9 4v6c0 5-9 10-9 10S3 17 3 12V6z M8 11l3 3 5-5",
} as const;

export function Icon({ name, className = "" }: { name: keyof typeof PATHS; className?: string }) {
  return <svg className={`icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={PATHS[name]} /></svg>;
}
