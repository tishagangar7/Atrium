import type { ReactNode } from "react";
export type IconName =
  | "mesh"
  | "map"
  | "info"
  | "link"
  | "arrow"
  | "expand"
  | "chevron"
  | "people"
  | "fire"
  | "truck"
  | "agreement"
  | "activity"
  | "layers"
  | "play"
  | "reset"
  | "close"
  | "check";
const paths: Record<IconName, ReactNode> = {
  mesh: (
    <>
      <path d="m12 3 8 5v8l-8 5-8-5V8Z M4 8l8 5 8-5 M12 13v8 M12 3v5" />
      <circle cx="12" cy="11" r="2" />
    </>
  ),
  map: <path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3Z M9 3v15 M15 6v15" />,
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6 M12 7v.1" />
    </>
  ),
  link: (
    <>
      <path d="m9 15 6-6 M7 14l-2 2a3.5 3.5 0 0 0 5 5l4-4 M10 7l4-4a3.5 3.5 0 0 1 5 5l-2 2" />
    </>
  ),
  arrow: <path d="M4 12h15 M14 6l6 6-6 6" />,
  expand: <path d="M8 3H3v5 M16 3h5v5 M3 16v5h5 M21 16v5h-5" />,
  chevron: <path d="m9 5 7 7-7 7" />,
  people: (
    <>
      <circle cx="9" cy="8" r="3" />
      <path d="M3 20v-2a6 6 0 0 1 12 0v2 M16 5a3 3 0 0 1 0 6 M18 14a5 5 0 0 1 3 4v2" />
    </>
  ),
  fire: (
    <path d="M13 2c1 6-4 7-3 11 2-1 3-3 3-3 4 2 6 5 5 8-2 6-12 5-13 0C3 12 10 10 13 2Z" />
  ),
  truck: (
    <>
      <path d="M2 5h12v12H2Z M14 9h4l4 4v4h-8" />
      <circle cx="6" cy="18" r="2" />
      <circle cx="18" cy="18" r="2" />
    </>
  ),
  agreement: <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z M8 12l3 3 5-6" />,
  activity: <path d="M2 12h5l3-8 4 16 3-8h5" />,
  layers: <path d="m12 3 10 5-10 5L2 8Z M2 12l10 5 10-5 M2 16l10 5 10-5" />,
  play: <path d="m8 4 12 8-12 8Z" />,
  reset: <path d="M3 10a9 9 0 1 1 2 8 M3 4v6h6" />,
  close: <path d="m6 6 12 12 M6 18 18 6" />,
  check: <path d="m5 12 4 4L19 6" />,
};
export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}
