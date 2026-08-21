import { useEffect, useMemo, useState } from "react";
import { Loader2, RotateCcw } from "lucide-react";
import { useStudioStore } from "../../store/studioStore";

/**
 * Live parameters.
 *
 * Every variable the Blueprint declares, with a slider and a number field. A
 * change here is not a preview: it re-resolves the Blueprint, rebuilds under
 * FreeCAD and re-grades the result against the same assertions. That is what
 * makes the slider trustworthy — the assertions are expressions over these
 * variables, so they follow the value rather than being invalidated by it.
 *
 * The rebuild is deliberately not fired on every drag. A build is a container,
 * not a shader uniform, so the panel collects the edits and sends them when the
 * user lets go — the number tracks the drag, the geometry follows the release.
 *
 * Ranges are derived from the model's own value rather than authored: half to
 * double is wide enough to explore and narrow enough that the slider has
 * resolution where it matters. The number field is not clamped to it, because
 * the range is a convenience and the value is the user's.
 */

/** Sensible decimals for a dimension of this magnitude. */
function tidy(n: number): string {
    const abs = Math.abs(n);
    if (abs >= 100) return n.toFixed(1);
    if (abs >= 10) return n.toFixed(2);
    return n.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

function step(v: number): number {
    const abs = Math.abs(v);
    if (abs >= 100) return 1;
    if (abs >= 10) return 0.5;
    if (abs >= 1) return 0.1;
    return 0.01;
}

export default function ParametersPanel() {
    const part = useStudioStore((s) => s.part);
    const rebuilding = useStudioStore((s) => s.rebuilding);
    const rebuild = useStudioStore((s) => s.rebuild);

    const committed = useMemo(() => part?.variables ?? {}, [part]);
    const [draft, setDraft] = useState<Record<string, number>>(committed);

    // The part can change underneath this panel — a new build, an undo, a
    // project opened — and the drafts belong to the part that was on screen
    // when they were typed. Adopting the new values wholesale is the only
    // correct move; keeping them would show one part's numbers over another's.
    useEffect(() => setDraft(committed), [committed]);

    const names = Object.keys(committed);
    const dirty = names.filter((k) => draft[k] !== committed[k]);

    if (!part) {
        return (
            <div style={empty}>
                Parameters appear once a part is open. Every dimension the model
                named is tunable here, and each change rebuilds and re-checks the
                part.
            </div>
        );
    }

    if (names.length === 0) {
        return <div style={empty}>This part declares no variables.</div>;
    }

    // An example loaded from the gallery ships as geometry and a parameter
    // list, with no frozen Blueprint behind it. The numbers are still worth
    // reading, so they are shown — but a slider that cannot move anything is
    // worse than no slider, so the controls are locked and the reason is given.
    const editable = !!part.blueprint;

    const commit = () => {
        if (!editable || !dirty.length || rebuilding) return;
        const overrides: Record<string, number> = {};
        for (const k of dirty) overrides[k] = draft[k];
        void rebuild({ variables: overrides }, `Retune ${dirty.join(", ")}`);
    };

    return (
        <div>
            {!editable && (
                <div style={{ ...empty, paddingBottom: "4px" }}>
                    Read-only — this part has no Blueprint behind it, so there is
                    nothing to rebuild from. Describe it to Orion to get a parametric
                    version.
                </div>
            )}
            {names.map((name) => {
                const base = committed[name];
                const value = draft[name] ?? base;
                const changed = value !== base;
                // A variable that starts at zero has no meaningful proportional
                // range, so it gets an absolute one instead of a dead slider.
                const lo = base === 0 ? -10 : Math.min(base * 0.5, base * 1.5);
                const hi = base === 0 ? 10 : Math.max(base * 0.5, base * 1.5);

                return (
                    <div key={name} style={{ padding: "7px 12px 8px" }}>
                        <div style={{ display: "flex", alignItems: "baseline", gap: "8px" }}>
                            <span
                                className="of-num"
                                style={{
                                    flex: 1,
                                    minWidth: 0,
                                    fontSize: "11px",
                                    color: changed ? "var(--st-blue)" : "var(--st-graphite)",
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                    whiteSpace: "nowrap",
                                }}
                                title={name}
                            >
                                {name}
                            </span>
                            <input
                                type="number"
                                className="of-num"
                                value={value}
                                step={step(base)}
                                disabled={rebuilding || !editable}
                                onChange={(e) =>
                                    setDraft((d) => ({ ...d, [name]: Number(e.target.value) }))
                                }
                                onKeyDown={(e) => e.key === "Enter" && commit()}
                                onBlur={commit}
                                style={{
                                    width: "72px",
                                    padding: "2px 5px",
                                    textAlign: "right",
                                    background: "var(--st-raise)",
                                    border: `1px solid ${changed ? "var(--st-blue)" : "var(--st-rule)"}`,
                                    borderRadius: "4px",
                                    color: "var(--st-ink)",
                                    fontSize: "11px",
                                    outline: "none",
                                }}
                            />
                        </div>
                        <input
                            type="range"
                            className="of-range"
                            aria-label={name}
                            min={lo}
                            max={hi}
                            step={step(base)}
                            value={value}
                            disabled={rebuilding || !editable}
                            onChange={(e) =>
                                setDraft((d) => ({ ...d, [name]: Number(e.target.value) }))
                            }
                            // Commit on release, not on every frame: each build
                            // is a FreeCAD container.
                            onMouseUp={commit}
                            onTouchEnd={commit}
                            onKeyUp={(e) => {
                                if (e.key.startsWith("Arrow") || e.key === "Home" || e.key === "End") commit();
                            }}
                        />
                        {changed && (
                            <div
                                className="of-num"
                                style={{ fontSize: "9.5px", color: "var(--st-pencil)", marginTop: "-1px" }}
                            >
                                was {tidy(base)}
                            </div>
                        )}
                    </div>
                );
            })}

            {editable && (dirty.length > 0 || rebuilding) && (
                <div
                    style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                        padding: "8px 12px",
                        borderTop: "1px solid var(--st-rule-soft)",
                    }}
                >
                    {rebuilding ? (
                        <span
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: "6px",
                                fontSize: "11px",
                                color: "var(--st-graphite)",
                            }}
                        >
                            <Loader2 size={11} className="of-spin" />
                            Rebuilding and re-checking…
                        </span>
                    ) : (
                        <>
                            <button
                                onClick={commit}
                                style={{
                                    padding: "4px 10px",
                                    borderRadius: "5px",
                                    border: "none",
                                    background: "var(--st-blue)",
                                    color: "var(--st-on-accent)",
                                    fontSize: "11px",
                                    fontWeight: 700,
                                    cursor: "pointer",
                                }}
                            >
                                Rebuild
                            </button>
                            <button
                                onClick={() => setDraft(committed)}
                                title="Discard the edited values"
                                style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "5px",
                                    padding: "4px 8px",
                                    borderRadius: "5px",
                                    border: "1px solid var(--st-rule)",
                                    background: "transparent",
                                    color: "var(--st-graphite)",
                                    fontSize: "11px",
                                    cursor: "pointer",
                                }}
                            >
                                <RotateCcw size={10} />
                                Revert
                            </button>
                        </>
                    )}
                </div>
            )}
        </div>
    );
}

const empty: React.CSSProperties = {
    padding: "12px",
    fontSize: "11.5px",
    lineHeight: 1.6,
    color: "var(--st-pencil)",
};
