interface OrionFlowLogoProps {
  size?: number;
  className?: string;
  /** 'dark' (default): light strokes for dark backgrounds.
   *  'light': dark strokes for light backgrounds.
   *  'mono': all-white for colored/gradient surfaces. */
  theme?: 'light' | 'dark' | 'mono';
}

/**
 * Official OrionFlow mark — the constellation (Orion's belt): three nodes
 * joined by struts, apex node in brand violet. Matches the marketing site.
 */
export default function OrionFlowLogo({ size = 40, className = '', theme = 'dark' }: OrionFlowLogoProps) {
  const stroke = theme === 'light' ? '#10121a' : '#EDEAFB';
  const accent = theme === 'mono' ? '#ffffff' : theme === 'light' ? '#8AA5E6' : '#8AA5E6';
  const s = theme === 'mono' ? '#ffffff' : stroke;

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
      <line x1="6" y1="19" x2="13" y2="7" stroke={s} strokeWidth="1.6" />
      <line x1="13" y1="7" x2="20" y2="13" stroke={s} strokeWidth="1.6" />
      <circle cx="6" cy="19" r="2.6" fill={s} />
      <circle cx="20" cy="13" r="2.6" fill={s} />
      <circle cx="13" cy="7" r="3.2" fill={accent} />
    </svg>
  );
}

/** Gradient wordmark matching the marketing site's brand treatment. */
export function OrionFlowWordmark({ size = 16 }: { size?: number }) {
  return (
    <span
      style={{
        fontSize: `${size}px`,
        fontWeight: 700,
        letterSpacing: '-0.01em',
        background: 'linear-gradient(96deg, #8AA5E6, #B0C7E8)',
        WebkitBackgroundClip: 'text',
        backgroundClip: 'text',
        color: 'transparent',
      }}
    >
      OrionFlow
    </span>
  );
}
