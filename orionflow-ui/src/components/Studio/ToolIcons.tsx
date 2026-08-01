/**
 * Workbench glyphs.
 *
 * Drawn rather than borrowed from a general icon set: a pocket and an extrude
 * are the same box in any generic library, and an engineer scanning a toolbar
 * reads the shape before the label. Each glyph shows the operation happening —
 * material added above the face, material removed below it, an edge rounded
 * against the sharp original. Two strokes: solid for the part, dashed for what
 * the operation does to it.
 */

const S = {
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.35,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
};

const ACCENT = { ...S, stroke: 'currentColor', opacity: 0.55, strokeDasharray: '2 1.6' };

function Frame({ children }: { children: React.ReactNode }) {
    return (
        <svg width="19" height="19" viewBox="0 0 24 24" aria-hidden="true">
            {children}
        </svg>
    );
}

const GLYPHS: Record<string, React.ReactNode> = {
    // A profile lifted off its plane.
    pad: (
        <>
            <path {...S} d="M4 16h16" />
            <path {...S} d="M8 16V8h8v8" />
            <path {...ACCENT} d="M12 6.5V2M9.5 4.5 12 2l2.5 2.5" />
        </>
    ),
    // The same profile driven into the block.
    pocket: (
        <>
            <path {...S} d="M3 7h18v11H3z" />
            <path {...S} d="M9 7v6h6V7" />
            <path {...ACCENT} d="M12 2v4M9.5 3.5 12 6l2.5-2.5" />
        </>
    ),
    // A section swept about an axis.
    revolve: (
        <>
            <path {...S} d="M12 3v18" />
            <path {...S} d="M14 7h5v10h-5z" />
            <path {...ACCENT} d="M9 8.5c-2 1-2 6 0 7" />
        </>
    ),
    groove: (
        <>
            <path {...S} d="M12 3v18" />
            <path {...S} d="M15 6h5v12h-5z" />
            <path {...S} d="M15 10h3v4h-3z" />
            <path {...ACCENT} d="M9 8.5c-2 1-2 6 0 7" />
        </>
    ),
    // A rounded corner against the square one it replaced.
    fillet: (
        <>
            <path {...S} d="M5 19V11a6 6 0 0 1 6-6h8" />
            <path {...ACCENT} d="M5 5h6M5 5v6" />
        </>
    ),
    chamfer: (
        <>
            <path {...S} d="M5 19v-6l8-8h6" />
            <path {...ACCENT} d="M5 5h6M5 5v6" />
        </>
    ),
    // Wall left behind after hollowing.
    shell: (
        <>
            <path {...S} d="M4 5h16v14H4z" />
            <path {...S} d="M7.5 5v10.5h9V5" />
        </>
    ),
    draft: (
        <>
            <path {...S} d="M4 19h16" />
            <path {...S} d="M8.5 19 10 6h4l1.5 13" />
            <path {...ACCENT} d="M10 6v13M14 6v13" />
        </>
    ),
    linear: (
        <>
            <path {...S} d="M3.5 8h4v8h-4zM10 8h4v8h-4zM16.5 8h4v8h-4z" />
        </>
    ),
    polar: (
        <>
            <circle {...S} cx="12" cy="12" r="8.5" />
            <path {...S} d="M12 3.5v3M20.5 12h-3M12 20.5v-3M3.5 12h3" />
            <circle {...S} cx="12" cy="12" r="1.6" />
        </>
    ),
    mirror: (
        <>
            <path {...ACCENT} d="M12 2v20" />
            <path {...S} d="M9 6 4 12l5 6zM15 6l5 6-5 6" />
        </>
    ),
    loft: (
        <>
            <path {...S} d="M6 18h12M9 6h6" />
            <path {...S} d="M6 18 9 6M18 18 15 6" />
        </>
    ),
    sweep: (
        <>
            <path {...ACCENT} d="M4 18c6 0 8-12 16-12" />
            <circle {...S} cx="6" cy="16" r="2.6" />
            <circle {...S} cx="18" cy="8" r="2.6" />
        </>
    ),
};

export default function ToolIcon({ name }: { name: string }) {
    return <Frame>{GLYPHS[name] ?? GLYPHS.pad}</Frame>;
}
