interface OrionFlowLogoProps {
  size?: number;
  className?: string;
  /** 'light': blue/black rays for light backgrounds (default).
   *  'dark': blue/white rays for dark backgrounds.
   *  'mono': all-white rays for colored/gradient surfaces. */
  theme?: 'light' | 'dark' | 'mono';
}

export default function OrionFlowLogo({ size = 40, className = '', theme = 'dark' }: OrionFlowLogoProps) {
  const rayCount = 12;
  const innerRadius = size * 0.25;
  const outerRadius = size * 0.48;
  const rayWidth = size * 0.08;
  const center = size / 2;

  const rays = [];
  for (let i = 0; i < rayCount; i++) {
    const angle = (i * 360) / rayCount - 90;
    const rad = (angle * Math.PI) / 180;

    // Calculate ray start and end points
    const x1 = center + innerRadius * Math.cos(rad);
    const y1 = center + innerRadius * Math.sin(rad);
    const x2 = center + outerRadius * Math.cos(rad);
    const y2 = center + outerRadius * Math.sin(rad);

    // Blue rays on left (indices 6-11), contrast rays on right (indices 0-5)
    const isBlue = i >= 6 && i <= 11;
    const contrast = theme === 'light' ? '#0a0a0a' : '#f8fafc';
    const color = theme === 'mono' ? '#ffffff' : isBlue ? '#2563eb' : contrast;

    rays.push(
      <line
        key={i}
        x1={x1}
        y1={y1}
        x2={x2}
        y2={y2}
        stroke={color}
        strokeWidth={rayWidth}
        strokeLinecap="round"
      />
    );
  }

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      {/* Rays */}
      {rays}
      {/* Center circle */}
      <circle
        cx={center}
        cy={center}
        r={innerRadius}
        fill="white"
      />
    </svg>
  );
}
