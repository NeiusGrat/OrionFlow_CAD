interface OrionFlowLogoProps {
  size?: number;
  className?: string;
  /** 'dark' (default): light strokes for dark backgrounds.
   *  'light': dark strokes for light backgrounds.
   *  'mono': single-value, for a coloured or inverted surface. */
  theme?: 'light' | 'dark' | 'mono';
}

/**
 * The OrionFlow mark — the constellation of Orion's belt: three nodes joined by
 * struts, the apex node heavier than the other two.
 *
 * Monochrome. The apex used to be brand violet, which was the only hue in an
 * interface that has deliberately spent its colour budget on meaning — a check
 * that passed, a revision mark, a caution. A logo that is the one coloured
 * thing on the screen competes with those for attention and wins, so the
 * hierarchy inside the mark is carried by weight and value instead: the apex is
 * full ink, the struts and lesser nodes a step back from it.
 */
export default function OrionFlowLogo({ size = 40, className = '', theme = 'dark' }: OrionFlowLogoProps) {
  const ink = theme === 'mono' ? 'currentColor' : 'var(--st-ink)';
  const quiet = theme === 'mono' ? 'currentColor' : 'var(--st-graphite)';

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 26 26"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <line x1="6" y1="19" x2="13" y2="7" stroke={quiet} strokeWidth="1.6" />
      <line x1="13" y1="7" x2="20" y2="13" stroke={quiet} strokeWidth="1.6" />
      <circle cx="6" cy="19" r="2.6" fill={quiet} />
      <circle cx="20" cy="13" r="2.6" fill={quiet} />
      <circle cx="13" cy="7" r="3.2" fill={ink} />
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
