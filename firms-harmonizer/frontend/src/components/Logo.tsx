/**
 * Project mark: a single H3 cell with one thermal detection at its centre.
 *
 * The outer cell is stroked with `currentColor`, so it follows the light/dark
 * theme. The inner hexagon is the fire-energy red used across the map, charts
 * and audit tables, and is the only accent in the mark.
 */
export function Logo({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" focusable="false">
      <path
        d="M12 4.5 18.5 8.25v7.5L12 19.5 5.5 15.75v-7.5L12 4.5Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path
        d="M12 9.8 13.9 10.9v2.2L12 14.2 10.1 13.1v-2.2L12 9.8Z"
        fill="#B30000"
      />
    </svg>
  );
}
