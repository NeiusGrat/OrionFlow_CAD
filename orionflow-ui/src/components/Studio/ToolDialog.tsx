import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, X } from "lucide-react";
import ToolIcon from "./ToolIcons";
import { activeFields, defaultValues, findTool } from "../../lib/workbench";
import { useUIStore } from "../../store/uiStore";
import { useStudioStore } from "../../store/studioStore";

/**
 * The dialog a workbench tool opens.
 *
 * Small, modal and keyboard-first: Escape closes it, Enter applies it, and the
 * first field takes focus on open. It states plainly what applying it costs —
 * every dimension becomes a named variable, and adding a feature puts the part
 * outside the assertions the model was graded on. That warning is the honest
 * part of a manual edit and it belongs before the click, not after.
 */

export default function ToolDialog() {
    const request = useUIStore((s) => s.tool);
    const close = useUIStore((s) => s.closeTool);
    const rebuild = useStudioStore((s) => s.rebuild);
    const rebuilding = useStudioStore((s) => s.rebuilding);
    const featureCount = useStudioStore((s) => s.part?.featureTree?.features.length ?? 0);

    const tool = request ? findTool(request.kind) : undefined;
    const [values, setValues] = useState<Record<string, string | number>>({});
    const firstRef = useRef<HTMLInputElement | HTMLSelectElement>(null);

    useEffect(() => {
        if (tool) setValues(defaultValues(tool));
    }, [tool]);

    useEffect(() => {
        if (tool) firstRef.current?.focus();
    }, [tool]);

    // A sequence number keeps every hand-added variable unique across a
    // session, so `fillet_r_3` never collides with an earlier one.
    const seq = useMemo(() => featureCount + 1, [featureCount]);

    if (!request || !tool) return null;

    const fields = activeFields(tool, values);

    const apply = async () => {
        if (rebuilding) return;
        const payload = tool.build(values, seq);
        close();
        await rebuild(
            {
                add_feature: {
                    type: payload.type,
                    label: payload.label,
                    variables: payload.variables,
                    parameters: payload.parameters,
                    ...(payload.sketch ? { sketch: payload.sketch } : {}),
                },
            },
            payload.label,
        );
    };

    return (
        <div
            role="dialog"
            aria-modal="true"
            aria-label={tool.label}
            onKeyDown={(e) => {
                if (e.key === "Escape") close();
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void apply();
            }}
            style={{
                position: "fixed",
                inset: 0,
                zIndex: 500,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background: "rgba(0,0,0,0.45)",
            }}
            onMouseDown={(e) => {
                if (e.target === e.currentTarget) close();
            }}
        >
            <div
                className="of-enter studio-scroll"
                style={{
                    width: "330px",
                    maxHeight: "84vh",
                    overflowY: "auto",
                    background: "var(--st-sheet)",
                    border: "1px solid var(--st-rule)",
                    borderRadius: "8px",
                    boxShadow: "var(--st-shadow)",
                }}
            >
                <div
                    style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "9px",
                        padding: "11px 12px",
                        borderBottom: "1px solid var(--st-rule)",
                        color: "var(--st-ink)",
                    }}
                >
                    <ToolIcon name={tool.icon} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: "13px", fontWeight: 600 }}>{tool.label}</div>
                        <div style={{ fontSize: "10.5px", color: "var(--st-pencil)", lineHeight: 1.35 }}>
                            {tool.hint}
                        </div>
                    </div>
                    <button
                        onClick={close}
                        title="Close"
                        style={{ background: "transparent", border: "none", color: "var(--st-pencil)", cursor: "pointer" }}
                    >
                        <X size={14} />
                    </button>
                </div>

                <div style={{ padding: "12px", display: "flex", flexDirection: "column", gap: "10px" }}>
                    {fields.map((f, i) => (
                        <label key={f.key} style={{ display: "block" }}>
                            <span
                                className="of-label"
                                style={{ display: "block", marginBottom: "4px", color: "var(--st-graphite)" }}
                            >
                                {f.label}
                                {f.unit ? ` · ${f.unit}` : ""}
                            </span>
                            {f.kind === "select" ? (
                                <select
                                    ref={i === 0 ? (firstRef as any) : undefined}
                                    value={String(values[f.key] ?? f.value)}
                                    onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                                    style={inputStyle}
                                >
                                    {f.options?.map((o) => (
                                        <option key={o.value} value={o.value}>
                                            {o.label}
                                        </option>
                                    ))}
                                </select>
                            ) : (
                                <input
                                    ref={i === 0 ? (firstRef as any) : undefined}
                                    type="number"
                                    value={String(values[f.key] ?? f.value)}
                                    min={f.min}
                                    max={f.max}
                                    step={f.step}
                                    onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                                    className="of-num"
                                    style={inputStyle}
                                />
                            )}
                            {f.hint && (
                                <span
                                    style={{
                                        display: "block",
                                        marginTop: "3px",
                                        fontSize: "10px",
                                        color: "var(--st-pencil)",
                                        lineHeight: 1.4,
                                    }}
                                >
                                    {f.hint}
                                </span>
                            )}
                        </label>
                    ))}

                    <p
                        style={{
                            margin: "2px 0 0",
                            fontSize: "10.5px",
                            lineHeight: 1.5,
                            color: "var(--st-pencil)",
                            borderTop: "1px solid var(--st-rule-soft)",
                            paddingTop: "9px",
                        }}
                    >
                        Each dimension is added as a named variable, so you can retune it
                        afterwards from Parameters. Adding a feature puts the part outside
                        the assertions it was graded against — the checks still run, but
                        the verdict stops describing the model's own design.
                    </p>
                </div>

                <div
                    style={{
                        display: "flex",
                        justifyContent: "flex-end",
                        gap: "8px",
                        padding: "10px 12px",
                        borderTop: "1px solid var(--st-rule)",
                    }}
                >
                    <button onClick={close} style={ghostButton}>
                        Cancel
                    </button>
                    <button onClick={apply} disabled={rebuilding} style={primaryButton}>
                        {rebuilding ? <Loader2 size={12} className="of-spin" /> : null}
                        Apply {tool.label.toLowerCase()}
                    </button>
                </div>
            </div>
        </div>
    );
}

const inputStyle: React.CSSProperties = {
    width: "100%",
    padding: "6px 8px",
    background: "var(--st-raise)",
    border: "1px solid var(--st-rule)",
    borderRadius: "5px",
    color: "var(--st-ink)",
    fontSize: "12.5px",
    fontFamily: "inherit",
    outline: "none",
};

const ghostButton: React.CSSProperties = {
    padding: "6px 12px",
    borderRadius: "6px",
    border: "1px solid var(--st-rule)",
    background: "transparent",
    color: "var(--st-graphite)",
    fontSize: "12px",
    fontWeight: 600,
    cursor: "pointer",
};

const primaryButton: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    padding: "6px 12px",
    borderRadius: "6px",
    border: "none",
    background: "var(--st-blue)",
    color: "var(--st-on-accent)",
    fontSize: "12px",
    fontWeight: 700,
    cursor: "pointer",
};
