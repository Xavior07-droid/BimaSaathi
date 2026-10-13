// Small inline SVG icon set (no icon library = smaller bundle, works offline).
const PATHS = {
  home: 'M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10',
  policy: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3zM9 12l2 2 4-4',
  claim: 'M9 4h6a1 1 0 011 1v1H8V5a1 1 0 011-1zM6 6h12v15H6zM9 11h6M9 15h6',
  compare: 'M12 3v18M5 7h14M5 7l-2 6a3 3 0 006 0L7 7m10 0l-2 6a3 3 0 006 0l-2-6',
  bell: 'M6 16V11a6 6 0 1112 0v5l2 2H4l2-2zM10 21h4',
  settings: 'M12 15a3 3 0 100-6 3 3 0 000 6zM19 12a7 7 0 00-.1-1.2l2-1.5-2-3.5-2.4 1a7 7 0 00-2-1.2L14 3h-4l-.5 2.6a7 7 0 00-2 1.2l-2.4-1-2 3.5 2 1.5a7 7 0 000 2.4l-2 1.5 2 3.5 2.4-1a7 7 0 002 1.2L10 21h4l.5-2.6a7 7 0 002-1.2l2.4 1 2-3.5-2-1.5c.1-.4.1-.8.1-1.2z',
  camera: 'M4 8h3l2-3h6l2 3h3v11H4zM12 17a4 4 0 100-8 4 4 0 000 8z',
  upload: 'M12 16V4M7 9l5-5 5 5M4 20h16',
  mic: 'M12 15a3 3 0 003-3V6a3 3 0 00-6 0v6a3 3 0 003 3zM6 11a6 6 0 0012 0M12 17v4',
  flag: 'M5 21V4M5 4h11l-2 4 2 4H5',
  info: 'M12 8h.01M11 12h1v5h1M12 21a9 9 0 100-18 9 9 0 000 18z',
} as const;

export type IconName = keyof typeof PATHS;

export default function Icon({ name, className = 'h-6 w-6' }: { name: IconName; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
