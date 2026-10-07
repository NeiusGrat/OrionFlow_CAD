interface OrionFlowLogoProps {
  size?: number;
  className?: string;
  /** 'dark' (default): light strokes for dark backgrounds.
   *  'light': dark strokes for light backgrounds.
   *  'mono': single-value, for a coloured or inverted surface. */
  theme?: 'light' | 'dark' | 'mono';
}

/** The mark's geometry, in a 64 × 64 box: an eight-lobed ring (the outer edge
 *  is r = 28.6 + 2.3·cos 8θ around a ⌀36.4 hole) and a four-point star at its
 *  centre. Generated, not hand-drawn, so every size renders the same shape. */
const RING = "M62.9 32 L62.69 33.51 L62.08 34.96 L61.16 36.33 L60.05 37.58 L58.89 38.74 L57.81 39.83 L56.93 40.92 L56.3 42.06 L55.93 43.32 L55.79 44.72 L55.78 46.25 L55.78 47.89 L55.68 49.56 L55.37 51.18 L54.77 52.63 L53.85 53.85 L52.63 54.77 L51.18 55.37 L49.56 55.68 L47.89 55.78 L46.25 55.78 L44.72 55.79 L43.32 55.93 L42.06 56.3 L40.92 56.93 L39.83 57.81 L38.74 58.89 L37.58 60.05 L36.33 61.16 L34.96 62.08 L33.51 62.69 L32 62.9 L30.49 62.69 L29.04 62.08 L27.67 61.16 L26.42 60.05 L25.26 58.89 L24.17 57.81 L23.08 56.93 L21.94 56.3 L20.68 55.93 L19.28 55.79 L17.75 55.78 L16.11 55.78 L14.44 55.68 L12.82 55.37 L11.37 54.77 L10.15 53.85 L9.23 52.63 L8.63 51.18 L8.32 49.56 L8.22 47.89 L8.22 46.25 L8.21 44.72 L8.07 43.32 L7.7 42.06 L7.07 40.92 L6.19 39.83 L5.11 38.74 L3.95 37.58 L2.84 36.33 L1.92 34.96 L1.31 33.51 L1.1 32 L1.31 30.49 L1.92 29.04 L2.84 27.67 L3.95 26.42 L5.11 25.26 L6.19 24.17 L7.07 23.08 L7.7 21.94 L8.07 20.68 L8.21 19.28 L8.22 17.75 L8.22 16.11 L8.32 14.44 L8.63 12.82 L9.23 11.37 L10.15 10.15 L11.37 9.23 L12.82 8.63 L14.44 8.32 L16.11 8.22 L17.75 8.22 L19.28 8.21 L20.68 8.07 L21.94 7.7 L23.08 7.07 L24.17 6.19 L25.26 5.11 L26.42 3.95 L27.67 2.84 L29.04 1.92 L30.49 1.31 L32 1.1 L33.51 1.31 L34.96 1.92 L36.33 2.84 L37.58 3.95 L38.74 5.11 L39.83 6.19 L40.92 7.07 L42.06 7.7 L43.32 8.07 L44.72 8.21 L46.25 8.22 L47.89 8.22 L49.56 8.32 L51.18 8.63 L52.63 9.23 L53.85 10.15 L54.77 11.37 L55.37 12.82 L55.68 14.44 L55.78 16.11 L55.78 17.75 L55.79 19.28 L55.93 20.68 L56.3 21.94 L56.93 23.08 L57.81 24.17 L58.89 25.26 L60.05 26.42 L61.16 27.67 L62.08 29.04 L62.69 30.49ZM50.2 32A18.2 18.2 0 1 0 13.8 32A18.2 18.2 0 1 0 50.2 32Z";
const STAR = "M32 19.4Q33.35 30.65 44.6 32Q33.35 33.35 32 44.6Q30.65 33.35 19.4 32Q30.65 30.65 32 19.4Z";

/**
 * The OrionFlow mark — a lobed ring with a star at its centre.
 *
 * Monochrome, one value: the ring and the star share an ink, and the hole is
 * left transparent so the mark sits on any surface. It used to be the
 * constellation of Orion's belt; the star keeps the name, the ring makes it
 * read as a single object at favicon size.
 */
export default function OrionFlowLogo({ size = 40, className = '', theme = 'dark' }: OrionFlowLogoProps) {
  const ink = theme === 'mono' ? 'currentColor' : 'var(--st-ink)';

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <path fill={ink} fillRule="evenodd" d={RING} />
      <path fill={ink} d={STAR} />
    </svg>
  );
}

/** The wordmark. Set in the interface face at tight tracking, in ink — the
 *  gradient it used to carry was the last of the old blue system. */
export function OrionFlowWordmark({ size = 16 }: { size?: number }) {
  return (
    <span
      style={{
        fontSize: `${size}px`,
        fontWeight: 600,
        letterSpacing: '-0.026em',
        color: 'var(--st-ink)',
      }}
    >
      OrionFlow
    </span>
  );
}
