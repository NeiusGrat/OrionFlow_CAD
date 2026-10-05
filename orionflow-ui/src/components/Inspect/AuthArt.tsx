/** Sign-in panel art: the OF-1001 bracket drawn in white line, ballooning itself. */
const BALLOONS: [number, number, number, number, number][] = [
    // no, balloon x, y, leader-to x, y
    [1, 62, 58, 108, 92],
    [2, 352, 52, 300, 96],
    [3, 40, 214, 132, 178],
    [4, 384, 232, 330, 196],
    [5, 214, 306, 214, 262],
    [6, 450, 120, 430, 150],
];

export default function AuthArt() {
    return (
        <div className="in-auth-art">
            <div style={{ display: "flex", alignItems: "center", gap: 10, fontWeight: 600 }}>
                <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
                    <circle cx="9" cy="9" r="7.2" fill="#fff" />
                    <text x="9" y="12.4" textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize="9.5" fontWeight="600" fill="#000">1</text>
                    <path d="M14.2 14.2 L21 21" stroke="#fff" strokeWidth="1.6" />
                    <rect x="19.4" y="19.4" width="3.2" height="3.2" fill="#fff" />
                </svg>
                OrionFlow Inspect
            </div>
            <svg viewBox="0 0 500 340" role="img" aria-label="A bracket drawing being ballooned" style={{ margin: "24px 0" }}>
                <style>{`
                    .ln { stroke: #fff; fill: none; stroke-width: 1.4; }
                    .th { stroke: #fff; fill: none; stroke-width: .7; stroke-dasharray: 4 3; opacity: .55; }
                    .dm { stroke: #fff; stroke-width: .7; opacity: .7; }
                    .tx { fill: #fff; font: 500 10px "IBM Plex Mono", monospace; opacity: .8; }
                    .bl { opacity: 0; animation: pop .5s ease-out forwards; }
                    @keyframes pop { from { opacity: 0; transform: scale(.6); } to { opacity: 1; transform: scale(1); } }
                    @media (prefers-reduced-motion: reduce) { .bl { animation: none; opacity: 1; } }
                `}</style>
                {/* front view */}
                <rect className="ln" x="90" y="80" width="260" height="160" />
                <circle className="ln" cx="155" cy="160" r="20" />
                {[[110, 100], [330, 100], [110, 220], [330, 220]].map(([x, y]) => <circle key={`${x}${y}`} className="ln" cx={x} cy={y} r="5" />)}
                <circle className="ln" cx="245" cy="160" r="5.5" />
                <circle className="th" cx="245" cy="160" r="7" />
                <line className="th" x1="155" y1="128" x2="155" y2="192" />
                <line className="th" x1="123" y1="160" x2="187" y2="160" />
                {/* side view */}
                <rect className="ln" x="405" y="80" width="40" height="160" />
                <line className="th" x1="405" y1="140" x2="445" y2="140" />
                <line className="th" x1="405" y1="180" x2="445" y2="180" />
                {/* dimensions */}
                <line className="dm" x1="90" y1="262" x2="350" y2="262" />
                <line className="dm" x1="90" y1="252" x2="90" y2="270" />
                <line className="dm" x1="350" y1="252" x2="350" y2="270" />
                <text className="tx" x="196" y="280">200 ±0.1</text>
                <line className="dm" x1="368" y1="80" x2="368" y2="240" />
                <text className="tx" x="374" y="164">120</text>
                <text className="tx" x="128" y="204">Ø30 H7</text>
                {/* balloons, one after another */}
                {BALLOONS.map(([n, x, y, lx, ly], i) => (
                    <g key={n} className="bl" style={{ animationDelay: `${0.5 + i * 0.45}s`, transformOrigin: `${x}px ${y}px` }}>
                        <line x1={x} y1={y} x2={lx} y2={ly} stroke="#fff" strokeWidth="1" />
                        <circle cx={lx} cy={ly} r="2" fill="#fff" />
                        <circle cx={x} cy={y} r="12" fill="#fff" />
                        <text x={x} y={y + 4} textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize="11" fontWeight="600" fill="#000">{n}</text>
                    </g>
                ))}
            </svg>
            <div>
                <h2>Drawing in. First article report out.</h2>
                <p>Every characteristic ballooned and toleranced, checked against the 3D model and the PO,
                    and drafted into AS9102 Forms 1, 2 and 3 for you to review and sign.</p>
            </div>
        </div>
    );
}
