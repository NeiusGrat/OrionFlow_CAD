import { createElement, useState } from "react";
import {
    Box,
    Circle,
    Layers,
    Minus,
    Plus,
    RotateCcw,
    Scissors,
    Slash,
    Sparkles,
    AlertTriangle,
    HelpCircle,
} from "lucide-react";
import { useStudioStore } from "../../store/studioStore";
import type { FeatureNode } from "../../services/studioApi";

/** How the part was built, in the order it was built.
 *
 *  Everything shown here is either what the model authored or what the kernel
 *  measured — nothing is inferred. That is why an unmeasured feature says so
 *  instead of showing 0 mm³: a history that quietly reports a number nobody
 *  measured is worse than one that admits the gap, because the user cannot
 *  tell the two apart.
 */

const ICONS: Record<string, typeof Box> = {
    Pad: Plus,
    Pocket: Minus,
    Revolution: RotateCcw,
    Groove: RotateCcw,
    Hole: Circle,
    Fillet: Slash,
    Chamfer: Scissors,
    Draft: Slash,
    Thickness: Layers,
    LinearPattern: Layers,
    PolarPattern: Layers,
    Mirrored: Layers,
    Loft: Sparkles,
    Sweep: Sparkles,
};

function iconFor(type: string) {
    return ICONS[type] ?? Box;
}

/** mm³ is unreadable past a few thousand; cm³ is what an engineer thinks in. */
function volume(mm3: number | null): string | null {
    if (mm3 === null || mm3 === undefined) return null;
    const cm3 = mm3 / 1000;
    const sign = cm3 > 0 ? "+" : cm3 < 0 ? "−" : "";
    const magnitude = Math.abs(cm3);
    const digits = magnitude >= 100 ? 0 : magnitude >= 10 ? 1 : 2;
    return `${sign}${magnitude.toFixed(digits)} cm³`;
}

const STATUS_COLOR: Record<FeatureNode["status"], string> = {
    success: "var(--studio-text-dim)",
    error: "var(--studio-err)",
    unsupported: "var(--studio-warn)",
    unknown: "var(--studio-text-faint)",
};

function FeatureRow({ feature, index, open, onToggle }: {
    feature: FeatureNode;
    index: number;
    open: boolean;
    onToggle: () => void;
}) {
    const delta = volume(feature.volume_delta_mm3);
    const failed = feature.status === "error";
    const params = Object.entries(feature.parameters);
    const exprs = Object.entries(feature.expressions).filter(
        ([k]) => !k.startsWith("_"),
    );

    return (
        <div style={{ borderBottom: "1px solid var(--studio-border-soft)" }}>
            <button
                onClick={onToggle}
                title={feature.error ?? feature.rationale ?? undefined}
                style={{
                    width: "100%",
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    padding: "7px 12px",
                    background: open ? "var(--studio-accent-dim)" : "transparent",
                    border: "none",
                    cursor: "pointer",
                    textAlign: "left",
                    color: "var(--studio-text)",
                }}
            >
                <span
                    style={{
                        color: "var(--studio-text-faint)",
                        fontSize: "10px",
                        fontVariantNumeric: "tabular-nums",
                        minWidth: "14px",
                    }}
                >
                    {index + 1}
                </span>
                {/* createElement rather than a capitalised local: binding the
                    icon to a variable inside render declares a new component
                    on every pass, which resets its state and trips the
                    static-components rule. */}
                {createElement(iconFor(feature.type), {
                    size: 13,
                    style: { color: STATUS_COLOR[feature.status], flexShrink: 0 },
                })}
                <span
                    style={{
                        flex: 1,
                        fontSize: "12px",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        color: failed ? "var(--studio-err)" : "var(--studio-text)",
                    }}
                >
                    {feature.label}
                </span>

                {failed && <AlertTriangle size={12} style={{ color: "var(--studio-err)" }} />}
                {feature.status === "unknown" && !failed && (
                    <HelpCircle size={12} style={{ color: "var(--studio-text-faint)" }} />
                )}
                {delta && (
                    <span
                        style={{
                            fontSize: "10px",
                            fontVariantNumeric: "tabular-nums",
                            color:
                                (feature.volume_delta_mm3 ?? 0) < 0
                                    ? "var(--studio-warn)"
                                    : "var(--studio-text-dim)",
                        }}
                    >
                        {delta}
                    </span>
                )}
            </button>

            {open && (
                <div style={{ padding: "2px 12px 10px 34px", fontSize: "11px" }}>
                    {feature.error && (
                        <div style={{ color: "var(--studio-err)", marginBottom: "6px" }}>
                            {feature.error}
                        </div>
                    )}
                    {feature.status === "unknown" && !feature.error && (
                        <div style={{ color: "var(--studio-text-faint)", marginBottom: "6px" }}>
                            no measurement was recorded for this feature
                        </div>
                    )}
                    {feature.rationale && (
                        <div style={{ color: "var(--studio-text-dim)", marginBottom: "6px" }}>
                            {feature.rationale}
                        </div>
                    )}
                    {params.map(([key, value]) => (
                        <div
                            key={key}
                            style={{
                                display: "flex",
                                justifyContent: "space-between",
                                gap: "10px",
                                padding: "1px 0",
                                color: "var(--studio-text-dim)",
                            }}
                        >
                            <span>{key}</span>
                            <span
                                style={{
                                    color: "var(--studio-text)",
                                    fontVariantNumeric: "tabular-nums",
                                }}
                            >
                                {typeof value === "number" ? +value.toFixed(3) : String(value)}
                                {/* The expression is the reason for the number,
                                    so it travels beside it rather than in a
                                    separate view. */}
                                {exprs.length > 0 && (
                                    <span style={{ color: "var(--studio-text-faint)" }}>
                                        {(() => {
                                            const e = feature.expressions[key];
                                            return e !== undefined && String(e) !== String(value)
                                                ? `  = ${e}`
                                                : "";
                                        })()}
                                    </span>
                                )}
                            </span>
                        </div>
                    ))}
                    {params.length === 0 && exprs.length > 0 && (
                        <div style={{ color: "var(--studio-text-faint)" }}>
                            dimensions could not be resolved; showing expressions only
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

export default function FeatureHistoryTree() {
    const tree = useStudioStore((s) => s.part?.featureTree ?? null);
    const [open, setOpen] = useState<string | null>(null);

    if (!tree || tree.features.length === 0) {
        return (
            <div
                style={{
                    padding: "14px 12px",
                    color: "var(--studio-text-faint)",
                    fontSize: "11px",
                    lineHeight: 1.6,
                }}
            >
                {tree
                    ? "This part has no feature history on record."
                    : "Design a part to see how it was built."}
            </div>
        );
    }

    return (
        <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
            {!tree.evidence_available && (
                // Said once, at the top, rather than repeated on every row.
                <div
                    style={{
                        padding: "7px 12px",
                        color: "var(--studio-text-faint)",
                        fontSize: "10px",
                        borderBottom: "1px solid var(--studio-border-soft)",
                    }}
                >
                    No build record for this part — feature volumes are unknown.
                </div>
            )}
            <div style={{ overflowY: "auto", minHeight: 0 }}>
                {tree.features.map((f, i) => (
                    <FeatureRow
                        key={f.id || String(i)}
                        feature={f}
                        index={i}
                        open={open === f.id}
                        onToggle={() => setOpen(open === f.id ? null : f.id)}
                    />
                ))}
            </div>
        </div>
    );
}
