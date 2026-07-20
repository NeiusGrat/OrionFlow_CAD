import { useEffect, useRef, useState } from "react";
import { Cpu, Download, CheckCircle2, AlertTriangle, Wrench } from "lucide-react";
import { designWithAgent, type AgentDesignResponse } from "../../services/agentApi";
import { getFullUrl } from "../../services/oflApi";
import { useOFLStore } from "../../store/oflStore";

const PHASES = [
    "Reading the brief",
    "Sourcing standard parts",
    "Engineering plan",
    "Generating & validating geometry",
    "DFM check & simulation export",
];

const label: React.CSSProperties = {
    fontSize: "10px",
    fontWeight: 700,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    color: "var(--studio-text-faint)",
    margin: "14px 0 6px",
};

const card: React.CSSProperties = {
    background: "var(--studio-panel-2)",
    border: "1px solid var(--studio-border)",
    borderRadius: "8px",
    padding: "10px",
    fontSize: "12px",
};

function scoreColor(score: number): string {
    if (score >= 90) return "#7FB894";
    if (score >= 70) return "#D9A441";
    return "#DE8871";
}

export default function AgentPanel() {
    const [prompt, setPrompt] = useState("");
    const [running, setRunning] = useState(false);
    const [phaseIdx, setPhaseIdx] = useState(0);
    const [result, setResult] = useState<AgentDesignResponse | null>(null);
    const [error, setError] = useState("");
    const timer = useRef<ReturnType<typeof setInterval> | null>(null);

    const setFromResponse = useOFLStore((s) => s.setFromResponse);

    useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

    const run = async () => {
        if (!prompt.trim() || running) return;
        setRunning(true);
        setError("");
        setResult(null);
        setPhaseIdx(0);
        // The endpoint is one-shot; advance the stepper on a timer so the
        // user sees where the harness typically is, capped before "done".
        timer.current = setInterval(
            () => setPhaseIdx((i) => Math.min(i + 1, PHASES.length - 1)),
            4000
        );
        try {
            const res = await designWithAgent(prompt.trim());
            setResult(res);
            if (res.success) {
                // Light up the 3D viewer + code/param panels with the result.
                setFromResponse({
                    success: true,
                    ofl_code: res.ofl_code,
                    files: {
                        step: res.files.step ?? null,
                        stl: res.files.stl ?? null,
                        glb: res.files.glb ?? null,
                    },
                    parameters: res.parameters ?? [],
                    error: null,
                    generation_time_ms: res.generation_time_ms,
                    repair_attempts: res.repair_attempts,
                    stats: res.stats ?? null,
                });
            } else {
                setError(res.error || "Design failed");
            }
        } catch (e: any) {
            setError(e.message || "Agent request failed");
        } finally {
            if (timer.current) clearInterval(timer.current);
            setRunning(false);
        }
    };

    const analysis = result?.analysis;
    const plan = result?.reasoning;
    const score = analysis?.manufacturability_score;

    return (
        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "12px", display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                <Cpu size={14} color="var(--studio-accent)" />
                <span style={{ fontSize: "12px", fontWeight: 700, color: "var(--studio-text)" }}>
                    Engineer mode
                </span>
            </div>
            <p style={{ fontSize: "11.5px", color: "var(--studio-text-faint)", margin: "0 0 10px", lineHeight: 1.5 }}>
                Describe the part with the real components it interfaces with (NEMA 17,
                608 bearing, M3…). The agent sources exact specs, plans the design,
                validates the geometry, and exports simulation-ready URDF/SDF.
            </p>

            <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(); }}
                placeholder="A motor mounting bracket for a NEMA 17 stepper with 4x M3 clearance holes and a 22mm center bore…"
                rows={3}
                style={{
                    width: "100%",
                    boxSizing: "border-box",
                    resize: "vertical",
                    background: "var(--studio-panel-2)",
                    border: "1px solid var(--studio-border)",
                    borderRadius: "8px",
                    padding: "9px 10px",
                    color: "var(--studio-text)",
                    fontSize: "12.5px",
                    outline: "none",
                    fontFamily: "inherit",
                }}
            />
            <button
                onClick={run}
                disabled={running || !prompt.trim()}
                style={{
                    marginTop: "8px",
                    padding: "9px 0",
                    borderRadius: "8px",
                    border: "none",
                    background: running || !prompt.trim() ? "var(--studio-panel-2)" : "var(--studio-accent)",
                    color: running || !prompt.trim() ? "var(--studio-text-faint)" : "#fff",
                    fontSize: "12.5px",
                    fontWeight: 700,
                    cursor: running || !prompt.trim() ? "default" : "pointer",
                }}
            >
                {running ? "Engineering…" : "Design it"}
            </button>

            {running && (
                <div style={{ marginTop: "14px" }}>
                    {PHASES.map((p, i) => (
                        <div key={p} style={{ display: "flex", alignItems: "center", gap: "8px", padding: "4px 0", fontSize: "11.5px" }}>
                            <span style={{
                                width: "7px", height: "7px", borderRadius: "50%", flexShrink: 0,
                                background: i < phaseIdx ? "#7FB894" : i === phaseIdx ? "var(--studio-accent)" : "var(--studio-border)",
                            }} />
                            <span style={{ color: i <= phaseIdx ? "var(--studio-text)" : "var(--studio-text-faint)" }}>{p}</span>
                        </div>
                    ))}
                </div>
            )}

            {error && (
                <div style={{ ...card, marginTop: "12px", borderColor: "rgba(248,113,113,.4)", color: "#E8A594" }}>
                    {error}
                </div>
            )}

            {result?.success && (
                <>
                    {result.sourced_parts.length > 0 && (
                        <>
                            <div style={label}>Sourced parts</div>
                            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                                {result.sourced_parts.map((p) => (
                                    <div key={p.part_id} style={card}>
                                        <div style={{ fontWeight: 600, color: "var(--studio-text)", display: "flex", alignItems: "center", gap: "6px" }}>
                                            <Wrench size={11} color="var(--studio-accent)" />{p.name}
                                        </div>
                                        <div style={{ color: "var(--studio-text-faint)", marginTop: "3px", fontSize: "11px" }}>
                                            {Object.entries(p.spec)
                                                .filter(([k, v]) => k !== "name" && k !== "category" && typeof v !== "object")
                                                .slice(0, 4)
                                                .map(([k, v]) => `${k.replace(/_mm$/, "").replace(/_/g, " ")}: ${v}`)
                                                .join(" · ")}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </>
                    )}

                    {plan?.knowledge_used && plan.knowledge_used.length > 0 && (
                        <>
                            <div style={label}>
                                Knowledge applied · {plan.knowledge_used.length} rules
                                {plan.reasoning_mode === "llm" ? " · LLM reasoning" : ""}
                            </div>
                            <div style={{ ...card, display: "flex", flexDirection: "column", gap: "4px", maxHeight: "160px", overflowY: "auto" }}>
                                {plan.knowledge_used.map((k, i) => (
                                    <div key={i} style={{ color: "var(--studio-text-faint)", fontSize: "11px", lineHeight: 1.45 }}>
                                        <span style={{ color: "var(--studio-accent)" }}>▸</span> {k}
                                    </div>
                                ))}
                            </div>
                        </>
                    )}

                    {plan?.features && plan.features.length > 0 && (
                        <>
                            <div style={label}>Engineering plan
                                {plan.material ? ` · ${plan.material.replace(/_/g, " ")}` : ""}
                            </div>
                            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                                {plan.features.map((f, i) => (
                                    <div key={i} style={card}>
                                        <span style={{ color: "var(--studio-text)", fontWeight: 600 }}>{f.name?.replace(/_/g, " ")}</span>
                                        {f.dims_mm && (
                                            <span style={{ color: "var(--studio-text-faint)" }}>
                                                {" — "}
                                                {Object.entries(f.dims_mm).filter(([, v]) => v != null).map(([k, v]) => `${k} ${v}`).join(", ")} mm
                                            </span>
                                        )}
                                        {f.justification && (
                                            <div style={{ color: "var(--studio-text-faint)", fontSize: "11px", marginTop: "2px" }}>
                                                {f.justification}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </>
                    )}

                    <div style={label}>Validation</div>
                    <div style={{ ...card, display: "flex", flexDirection: "column", gap: "5px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "6px", color: "var(--studio-text)" }}>
                            {result.stats?.watertight
                                ? <CheckCircle2 size={12} color="#7FB894" />
                                : <AlertTriangle size={12} color="#D9A441" />}
                            {result.stats?.watertight ? "Watertight solid" : "Geometry flagged — check analysis"}
                            {typeof score === "number" && (
                                <span style={{ marginLeft: "auto", fontWeight: 700, color: scoreColor(score) }}>
                                    DFM {score}/100
                                </span>
                            )}
                        </div>
                        {analysis?.properties?.mass_g != null && (
                            <div style={{ color: "var(--studio-text-faint)" }}>
                                Mass ≈ {analysis.properties.mass_g} g ({analysis.material?.replace(/_/g, " ")}) ·
                                {" "}{result.stats?.bbox_mm?.map((v) => Math.round(v)).join("×")} mm ·
                                {" "}{result.repair_attempts} repair{result.repair_attempts === 1 ? "" : "s"}
                            </div>
                        )}
                        {(analysis?.issues ?? []).map((iss, i) => (
                            <div key={i} style={{ color: iss.severity === "critical" ? "#DE8871" : "#D9A441", fontSize: "11px" }}>
                                {iss.severity.toUpperCase()}: {iss.issue}
                            </div>
                        ))}
                    </div>

                    {plan?.risks && plan.risks.length > 0 && (
                        <>
                            <div style={label}>Engineering risks</div>
                            <div style={{ ...card, display: "flex", flexDirection: "column", gap: "4px" }}>
                                {plan.risks.map((r, i) => (
                                    <div key={i} style={{ color: "#D9A441", fontSize: "11px" }}>⚠ {r}</div>
                                ))}
                            </div>
                        </>
                    )}

                    <div style={label}>Agent trace</div>
                    <div style={{ ...card, display: "flex", flexDirection: "column", gap: "3px" }}>
                        {result.trace.map((t, i) => (
                            <div key={i} style={{ display: "flex", gap: "8px", fontSize: "11px" }}>
                                <span style={{ color: "var(--studio-text-faint)", minWidth: "52px", textAlign: "right" }}>
                                    {(t.t_ms / 1000).toFixed(1)}s
                                </span>
                                <span style={{ color: "var(--studio-text)" }}>{t.phase}</span>
                                {typeof t.status === "string" && (
                                    <span style={{ color: "var(--studio-text-faint)" }}>{t.status}</span>
                                )}
                            </div>
                        ))}
                    </div>

                    <div style={label}>Export for simulation</div>
                    <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                        {([
                            ["STEP", result.files.step],
                            ["STL", result.files.stl],
                            ["URDF", result.files.urdf],
                            ["SDF", result.files.sdf],
                        ] as const).filter(([, url]) => url).map(([name, url]) => (
                            <a
                                key={name}
                                href={getFullUrl(url as string) ?? "#"}
                                target="_blank"
                                rel="noreferrer"
                                style={{
                                    display: "inline-flex", alignItems: "center", gap: "5px",
                                    padding: "6px 11px", borderRadius: "7px", fontSize: "11.5px", fontWeight: 600,
                                    background: "var(--studio-panel-2)", border: "1px solid var(--studio-border)",
                                    color: "var(--studio-text)", textDecoration: "none",
                                }}
                            >
                                <Download size={11} />{name}
                            </a>
                        ))}
                    </div>
                </>
            )}
        </div>
    );
}
