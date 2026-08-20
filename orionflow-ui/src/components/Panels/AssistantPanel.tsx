import { useEffect, useRef, useState } from "react";
import {
    ArrowUp,
    ChevronDown,
    ChevronRight,
    Download,
    Loader2,
    AlertCircle,
    Hammer,
    Check,
} from "lucide-react";
import OrionFlowLogo from "../OrionFlowLogo";
import VerificationCard from "./VerificationCard";
import {
    useStudioStore,
    type StudioMessage,
    type DesignOutcome,
    type StudioMode,
    type ToolCheck,
} from "../../store/studioStore";
import {
    fetchStudioHealth,
    fullUrl,
    LENSES,
    type StudioHealth,
    type StudioStep,
    type DesignNarrative,
    type Lens,
} from "../../services/studioApi";

/* ────────────────────────── bits ────────────────────────── */

function AgentAvatar({ size = 22 }: { size?: number }) {
    return (
        <div
            style={{
                width: size,
                height: size,
                borderRadius: Math.round(size / 4),
                background: "var(--st-blue)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
            }}
        >
            <OrionFlowLogo size={Math.round(size * 0.62)} theme="mono" />
        </div>
    );
}

/** Which model answered. A fallback is always named — a demo that quietly
 *  degrades to a general model is worse than one that stops, because nobody
 *  can tell which system produced the result. */
function ModelBadge({ model }: { model: string }) {
    if (!model) return null;
    // Three states, not two. A compiled part is not a fallback: no model
    // authored its geometry, so labelling it "Fallback" understates it and
    // labelling it "OrionFlow" claims weights that never ran. It names the
    // provider that only read the request into slots.
    const compiled = model.startsWith("compiled:");
    const readBy = compiled ? model.slice("compiled:".length) : "";
    const ours = model === "orionflow" || compiled;
    return (
        <span
            title={
                compiled
                    ? `Blueprint compiled deterministically in Python — ${readBy} only read the request into named fields, and authored no geometry`
                    : ours
                      ? "OrionFlow fine-tuned model"
                      : `Fallback model: ${model}`
            }
            style={{
                fontSize: "9px",
                fontWeight: 700,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                padding: "2px 5px",
                borderRadius: "3px",
                color: ours ? "var(--st-blue)" : "var(--st-caution)",
                background: ours ? "var(--st-blue-wash)" : "rgba(217,164,65,0.14)",
                border: `1px solid ${ours ? "var(--st-blue-edge)" : "rgba(217,164,65,0.3)"}`,
            }}
        >
            {compiled ? "Compiled" : ours ? "OrionFlow" : "Fallback"}
        </span>
    );
}

/** The lens a turn was answered under, kept beside the turn so a DFM review
 *  stays labelled as one after the selector has moved on. */
function LensTag({ lens }: { lens: Lens }) {
    if (lens === "modeling") return null;
    const label = LENSES.find((l) => l.id === lens)?.label ?? lens;
    return (
        <span
            style={{
                fontSize: "9px",
                fontWeight: 600,
                letterSpacing: "0.05em",
                padding: "2px 5px",
                borderRadius: "3px",
                color: "var(--st-graphite)",
                border: "1px solid var(--st-rule)",
            }}
        >
            {label}
        </span>
    );
}

/** The live progress list — every row a stage the server actually reported
 *  reaching. Nothing here is on a timer, so a stage that stalls looks stalled
 *  instead of animating towards a result that is not coming. */
function Steps({ steps }: { steps: StudioStep[] }) {
    if (!steps.length) return null;
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: "5px", margin: "2px 0 4px" }}>
            {steps.map((s) => {
                const color =
                    s.status === "done"
                        ? "var(--st-verify)"
                        : s.status === "fail"
                          ? "var(--st-redline)"
                          : "var(--st-blue)";
                return (
                    <div key={s.id}>
                        <div style={{ display: "flex", alignItems: "center", gap: "7px", fontSize: "12px" }}>
                            {s.status === "active" ? (
                                <Loader2 size={11} className="of-spin" style={{ color }} />
                            ) : (
                                <span style={{ color, fontSize: "11px", width: "11px", textAlign: "center" }}>
                                    {s.status === "done" ? "✓" : "✕"}
                                </span>
                            )}
                            <span style={{ color: s.status === "active" ? "var(--st-ink)" : "var(--st-graphite)" }}>
                                {s.label}
                            </span>
                            {s.detail && (
                                <span
                                    className="of-num"
                                    style={{
                                        marginLeft: "auto",
                                        fontSize: "10px",
                                        color: "var(--st-pencil)",
                                        textAlign: "right",
                                        maxWidth: "55%",
                                    }}
                                >
                                    {s.detail}
                                </span>
                            )}
                        </div>
                        {s.status !== "active" && s.items.length > 0 && (
                            <div style={{ paddingLeft: "18px", marginTop: "2px" }}>
                                {s.items.slice(0, 8).map((it, i) => (
                                    <div
                                        key={i}
                                        className="of-num"
                                        style={{
                                            fontSize: "10.5px",
                                            color: "var(--st-pencil)",
                                            lineHeight: 1.5,
                                            whiteSpace: "nowrap",
                                            overflow: "hidden",
                                            textOverflow: "ellipsis",
                                        }}
                                    >
                                        · {it}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                );
            })}
        </div>
    );
}

/** What each tool call means in plain words.
 *
 *  The raw names are the model's vocabulary, not the reader's. Anything not
 *  listed falls back to its own name rather than to a vague "checked
 *  something" — an unfamiliar tool name is still a true statement.
 */
const CHECK_LABELS: Record<string, string> = {
    list_objects: "Listed what the part is made of",
    inspect_topology: "Read the built topology",
    expand_topology: "Expanded one shape in full",
    get_parameters: "Read a feature's dimensions",
    get_featuregraph: "Read how the part was built",
    get_model_tier: "Checked how the part can be edited",
    measure: "Measured the built geometry",
    lookup_standard: "Looked up a standard",
    lookup_mechanical_knowledge: "Looked up mechanical data",
    lookup_nasa_requirement: "Looked up a NASA requirement",
    resolve_design_context: "Resolved the design context",
    calculate_sheet_metal_bend: "Calculated a bend allowance",
    check_sheet_metal_dfm: "Ran sheet-metal DFM checks",
    lookup_robotics_knowledge: "Looked up robotics data",
};

/** The one argument worth showing next to a check — which face, which part. */
function checkDetail(args?: Record<string, unknown>): string {
    if (!args) return "";
    for (const key of ["name", "query", "designation", "sub", "selector"]) {
        const v = args[key];
        if (typeof v === "string" && v) return v;
    }
    const a = args.a as Record<string, unknown> | undefined;
    const b = args.b as Record<string, unknown> | undefined;
    if (a?.sub && b?.sub) return `${a.sub} → ${b.sub}`;
    return "";
}

/** What the assistant went and checked before answering.
 *
 *  Shown rather than summarised away: an answer that measured the part and one
 *  that recalled a number look identical in prose, and only this tells them
 *  apart. A failed call stays on the list — a lookup that found nothing is a
 *  reason to trust the answer less, not something to hide.
 */
function Checks({ checks }: { checks: ToolCheck[] }) {
    if (!checks.length) return null;
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: "3px", margin: "6px 0 2px" }}>
            {checks.map((c, i) => {
                const detail = checkDetail(c.arguments);
                return (
                    <div
                        key={i}
                        style={{ display: "flex", alignItems: "center", gap: "7px", fontSize: "11.5px" }}
                    >
                        <span
                            style={{
                                color: c.ok ? "var(--st-verify)" : "var(--st-redline)",
                                fontSize: "11px",
                                width: "11px",
                                textAlign: "center",
                            }}
                        >
                            {c.ok ? "✓" : "✕"}
                        </span>
                        <span style={{ color: "var(--st-graphite)" }}>
                            {CHECK_LABELS[c.name] ?? c.name}
                        </span>
                        {detail && (
                            <span
                                className="of-num"
                                style={{
                                    fontSize: "10px",
                                    color: "var(--st-pencil)",
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                    whiteSpace: "nowrap",
                                    maxWidth: "45%",
                                }}
                            >
                                {detail}
                            </span>
                        )}
                    </div>
                );
            })}
        </div>
    );
}

/** Minimal inline markdown: **bold** only. The narrative is generated by us,
 *  so the input set is known — a full markdown renderer would be weight for
 *  nothing. */
function RichText({ text }: { text: string }) {
    const parts = text.split(/(\*\*[^*]+\*\*)/g);
    return (
        <>
            {parts.map((p, i) =>
                p.startsWith("**") && p.endsWith("**") ? (
                    <strong key={i} style={{ color: "var(--st-ink)", fontWeight: 650 }}>
                        {p.slice(2, -2)}
                    </strong>
                ) : (
                    <span key={i}>{p}</span>
                ),
            )}
        </>
    );
}

/** The engineering account of the design — what it understood, how it built
 *  it, why, and what was actually proved. */
function Narrative({ narrative }: { narrative: DesignNarrative }) {
    return (
        <div style={{ marginTop: "8px", display: "flex", flexDirection: "column", gap: "12px" }}>
            {narrative.sections.map((sec) => (
                <div key={sec.title}>
                    <div className="of-label" style={{ marginBottom: "4px" }}>
                        {sec.title}
                    </div>
                    <div style={{ fontSize: "12.5px", lineHeight: 1.65, color: "var(--st-graphite)" }}>
                        <RichText text={sec.body} />
                    </div>
                    {sec.items && sec.items.length > 0 && (
                        <ul style={{ margin: "6px 0 0", paddingLeft: "16px", display: "flex", flexDirection: "column", gap: "3px" }}>
                            {sec.items.map((it, i) => (
                                <li key={i} style={{ fontSize: "12px", lineHeight: 1.55, color: "var(--st-graphite)" }}>
                                    <RichText text={it} />
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            ))}
        </div>
    );
}

/** A collapsed drawer of machine-readable detail. The Blueprint and the raw
 *  derivation stay reachable — they are the reproducible record and the first
 *  thing to reach for when a part is wrong — but working notes are not an
 *  explanation, so they are not what a user is shown first. */
function Drawer({ label, text }: { label: string; text: string }) {
    const [open, setOpen] = useState(false);
    if (!text.trim()) return null;

    return (
        <div style={{ marginTop: "6px" }}>
            <button
                onClick={() => setOpen(!open)}
                className="of-label"
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "5px",
                    background: "transparent",
                    border: "none",
                    padding: 0,
                    cursor: "pointer",
                }}
            >
                {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                {label}
            </button>
            {open && (
                <pre
                    className="studio-scroll of-num"
                    style={{
                        margin: "5px 0 0",
                        padding: "8px 10px",
                        maxHeight: "240px",
                        overflowY: "auto",
                        background: "var(--st-raise)",
                        border: "1px solid var(--st-rule)",
                        borderRadius: "5px",
                        fontSize: "10px",
                        lineHeight: 1.55,
                        color: "var(--st-pencil)",
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                    }}
                >
                    {text.trim()}
                </pre>
            )}
        </div>
    );
}

function VariableChips({ variables }: { variables: Record<string, number> }) {
    const entries = Object.entries(variables ?? {});
    if (!entries.length) return null;
    return (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", marginTop: "8px" }}>
            {entries.map(([k, v]) => (
                <span
                    key={k}
                    className="of-num"
                    style={{
                        fontSize: "10px",
                        padding: "2.5px 7px",
                        borderRadius: "3px",
                        background: "var(--st-raise)",
                        border: "1px solid var(--st-rule)",
                        color: "var(--st-graphite)",
                    }}
                >
                    {k}&nbsp;<span style={{ color: "var(--st-ink)" }}>{v}</span>
                </span>
            ))}
        </div>
    );
}

function Exports({ files }: { files: DesignOutcome["files"] }) {
    // FCStd leads: it is the only one of the four that reopens as a parametric
    // model, so it is the download an engineer actually wants and the others
    // are what they hand to someone else.
    const entries = (
        [
            ["FCStd", files.fcstd],
            ["STEP", files.step],
            ["STL", files.stl],
            ["GLB", files.glb],
        ] as const
    ).filter(([, u]) => u);
    if (!entries.length) return null;
    return (
        <div style={{ display: "flex", gap: "6px", marginTop: "8px", flexWrap: "wrap" }}>
            {entries.map(([name, url]) => (
                <a
                    key={name}
                    href={fullUrl(url as string)}
                    download
                    style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "5px",
                        padding: "5px 10px",
                        borderRadius: "5px",
                        fontSize: "11px",
                        fontWeight: 600,
                        background: "var(--st-raise)",
                        border: "1px solid var(--st-rule)",
                        color: "var(--st-ink)",
                        textDecoration: "none",
                    }}
                >
                    <Download size={10} />
                    {name}
                </a>
            ))}
        </div>
    );
}

/** Turns a refine answer into a build without retyping the brief.
 *
 *  What it sends is the user's own request plus the assistant's specification,
 *  because that is what was agreed — sending only the last question would drop
 *  every number the conversation just settled. */
function BuildThis({ brief }: { brief: string }) {
    const buildThis = useStudioStore((s) => s.buildThis);
    const busy = useStudioStore((s) => s.busy);
    return (
        <button
            onClick={() => void buildThis(brief)}
            disabled={busy}
            style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                marginTop: "10px",
                padding: "6px 11px",
                borderRadius: "6px",
                border: "1px solid var(--st-blue-edge)",
                background: "var(--st-blue-wash)",
                color: "var(--st-blue)",
                fontSize: "11.5px",
                fontWeight: 700,
                cursor: busy ? "default" : "pointer",
                opacity: busy ? 0.5 : 1,
            }}
            title="Build the part this conversation has specified"
        >
            <Hammer size={12} />
            Build this
        </button>
    );
}

function Message({ msg, priorUser }: { msg: StudioMessage; priorUser: string }) {
    if (msg.role === "user") {
        return (
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <div
                    style={{
                        maxWidth: "88%",
                        padding: "8px 11px",
                        borderRadius: "9px 9px 2px 9px",
                        background: "var(--st-blue-wash)",
                        border: "1px solid var(--st-blue-edge)",
                        color: "var(--st-ink)",
                        fontSize: "13px",
                        lineHeight: 1.5,
                        whiteSpace: "pre-wrap",
                    }}
                >
                    {msg.content}
                </div>
            </div>
        );
    }

    // Refine answers get the build action; build answers already are one.
    const offersBuild = msg.mode === "refine" && !msg.streaming && !!msg.content && !msg.error;

    return (
        <div>
            <div style={{ display: "flex", alignItems: "center", gap: "7px", marginBottom: "7px" }}>
                <AgentAvatar />
                <span style={{ fontSize: "12.5px", fontWeight: 600, color: "var(--st-ink)" }}>Orion</span>
                <ModelBadge model={msg.model} />
                <LensTag lens={msg.lens} />
                {msg.design && (
                    <span className="of-num" style={{ marginLeft: "auto", fontSize: "10px", color: "var(--st-pencil)" }}>
                        {(msg.design.generationTimeMs / 1000).toFixed(1)}s
                    </span>
                )}
            </div>

            <div style={{ paddingLeft: "29px" }}>
                <Steps steps={msg.steps} />
                <Checks checks={msg.checks} />

                {msg.narrative && (
                    <>
                        <div
                            className="of-report-head"
                            style={{ fontSize: "16px", color: "var(--st-ink)", marginTop: "8px", lineHeight: 1.3 }}
                        >
                            {msg.narrative.headline}
                        </div>
                        <Narrative narrative={msg.narrative} />
                    </>
                )}

                {msg.content && (
                    <p style={{ margin: "8px 0 0", fontSize: "13px", lineHeight: 1.65, color: "var(--st-ink)", whiteSpace: "pre-wrap" }}>
                        {msg.content}
                    </p>
                )}

                {msg.error && (
                    <div
                        style={{
                            marginTop: "8px",
                            padding: "9px 11px",
                            borderRadius: "6px",
                            background: "var(--st-raise)",
                            border: "1px solid var(--st-redline)",
                            color: "var(--st-redline)",
                            fontSize: "12px",
                            lineHeight: 1.5,
                            display: "flex",
                            gap: "7px",
                        }}
                    >
                        <AlertCircle size={13} style={{ flexShrink: 0, marginTop: "2px" }} />
                        <span>{msg.error}</span>
                    </div>
                )}

                {offersBuild && <BuildThis brief={`${priorUser}\n\n${msg.content}`.trim()} />}

                {msg.design && (
                    <div style={{ marginTop: "10px", display: "flex", flexDirection: "column", gap: "8px" }}>
                        <VerificationCard report={msg.design.verification} />
                        <VariableChips variables={msg.design.variables} />
                        <Exports files={msg.design.files} />
                        <div>
                            <Drawer
                                label="Blueprint JSON"
                                text={msg.design.blueprint ? JSON.stringify(msg.design.blueprint, null, 2) : ""}
                            />
                            <Drawer label="Raw model output" text={msg.thinking} />
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

/* ────────────────────────── composer controls ────────────────────────── */

function ModeSwitch() {
    const mode = useStudioStore((s) => s.mode);
    const setMode = useStudioStore((s) => s.setMode);

    const options: { id: StudioMode; label: string; hint: string }[] = [
        { id: "refine", label: "Refine", hint: "Talk the specification through — no geometry is built" },
        { id: "build", label: "Build", hint: "Design and build the part now" },
    ];

    return (
        <div
            role="radiogroup"
            aria-label="Assistant mode"
            style={{
                display: "flex",
                padding: "2px",
                background: "var(--st-raise)",
                border: "1px solid var(--st-rule)",
                borderRadius: "6px",
            }}
        >
            {options.map((o) => (
                <button
                    key={o.id}
                    role="radio"
                    aria-checked={mode === o.id}
                    onClick={() => setMode(o.id)}
                    title={o.hint}
                    style={{
                        padding: "3px 11px",
                        borderRadius: "4px",
                        border: "none",
                        background: mode === o.id ? "var(--st-blue)" : "transparent",
                        color: mode === o.id ? "#12100B" : "var(--st-graphite)",
                        fontSize: "11px",
                        fontWeight: 700,
                        cursor: "pointer",
                    }}
                >
                    {o.label}
                </button>
            ))}
        </div>
    );
}

function LensPicker() {
    const lens = useStudioStore((s) => s.lens);
    const setLens = useStudioStore((s) => s.setLens);
    const mode = useStudioStore((s) => s.mode);
    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const close = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
        };
        if (open) document.addEventListener("mousedown", close);
        return () => document.removeEventListener("mousedown", close);
    }, [open]);

    const current = LENSES.find((l) => l.id === lens) ?? LENSES[0];

    return (
        <div ref={ref} style={{ position: "relative" }}>
            <button
                onClick={() => setOpen(!open)}
                aria-haspopup="listbox"
                aria-expanded={open}
                // Stated rather than hidden: a lens shapes the conversation, and
                // the design path is deliberately left alone, so switching it in
                // Build mode would promise something that does not happen.
                title={
                    mode === "build"
                        ? "Lenses shape the review, not the build — switch to Refine to use one"
                        : current.hint
                }
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "5px",
                    padding: "4px 8px",
                    borderRadius: "6px",
                    border: `1px solid ${lens !== "modeling" ? "var(--st-blue-edge)" : "var(--st-rule)"}`,
                    background: lens !== "modeling" ? "var(--st-blue-wash)" : "var(--st-raise)",
                    color: lens !== "modeling" ? "var(--st-blue)" : "var(--st-graphite)",
                    fontSize: "11px",
                    fontWeight: 600,
                    cursor: "pointer",
                    opacity: mode === "build" ? 0.55 : 1,
                }}
            >
                {current.label}
                <ChevronDown size={11} />
            </button>
            {open && (
                <div
                    role="listbox"
                    className="of-enter"
                    style={{
                        position: "absolute",
                        bottom: "30px",
                        left: 0,
                        width: "232px",
                        background: "var(--st-sheet)",
                        border: "1px solid var(--st-rule)",
                        borderRadius: "8px",
                        padding: "5px",
                        zIndex: 300,
                        boxShadow: "var(--st-shadow)",
                    }}
                >
                    {LENSES.map((l) => (
                        <button
                            key={l.id}
                            role="option"
                            aria-selected={l.id === lens}
                            onClick={() => {
                                setLens(l.id);
                                setOpen(false);
                            }}
                            className="of-row"
                            style={{
                                display: "flex",
                                alignItems: "flex-start",
                                gap: "7px",
                                width: "100%",
                                padding: "6px 8px",
                                borderRadius: "5px",
                                border: "none",
                                background: "transparent",
                                cursor: "pointer",
                                textAlign: "left",
                            }}
                        >
                            <Check
                                size={11}
                                style={{
                                    marginTop: "2px",
                                    flexShrink: 0,
                                    color: l.id === lens ? "var(--st-blue)" : "transparent",
                                }}
                            />
                            <span style={{ minWidth: 0 }}>
                                <span
                                    style={{
                                        display: "block",
                                        fontSize: "12px",
                                        fontWeight: 600,
                                        color: l.id === lens ? "var(--st-ink)" : "var(--st-graphite)",
                                    }}
                                >
                                    {l.label}
                                </span>
                                <span style={{ display: "block", fontSize: "10.5px", color: "var(--st-pencil)", lineHeight: 1.35 }}>
                                    {l.hint}
                                </span>
                            </span>
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

/* ────────────────────────── panel ────────────────────────── */

const STARTERS = [
    "A clevis mount, base 48×32, 16 tall, 12 mm gap, 9.5 mm pivot bore",
    "Bearing housing for a 6004 bearing, bolted on a 62 mm PCD",
    "NEMA 17 motor mount, 6 mm plate, 22 mm pilot bore",
];

export default function AssistantPanel() {
    const messages = useStudioStore((s) => s.messages);
    const busy = useStudioStore((s) => s.busy);
    const send = useStudioStore((s) => s.send);
    const mode = useStudioStore((s) => s.mode);
    const hasPart = useStudioStore((s) => !!s.part);

    const [value, setValue] = useState("");
    const [health, setHealth] = useState<StudioHealth | null>(null);
    const scrollRef = useRef<HTMLDivElement>(null);
    const areaRef = useRef<HTMLTextAreaElement>(null);

    useEffect(() => {
        fetchStudioHealth().then(setHealth);
    }, []);

    useEffect(() => {
        if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }, [messages]);

    useEffect(() => {
        if (areaRef.current) {
            areaRef.current.style.height = "22px";
            areaRef.current.style.height = Math.min(areaRef.current.scrollHeight, 130) + "px";
        }
    }, [value]);

    const submit = () => {
        if (!value.trim() || busy) return;
        send(value);
        setValue("");
    };

    return (
        <div
            style={{
                // Fills the panel column rather than defining it. The width,
                // the left rule and the sheet background moved to the tab
                // container in Workspace when this became one of two panels
                // sharing that column — kept here as well, they drew a second
                // border inside the first.
                width: "100%",
                flex: 1,
                display: "flex",
                flexDirection: "column",
                height: "100%",
                minHeight: 0,
            }}
        >
            {/* header */}
            <div
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "9px",
                    padding: "8px 11px",
                    borderBottom: "1px solid var(--st-rule)",
                    flexShrink: 0,
                }}
            >
                <span className="of-label" style={{ color: "var(--st-graphite)" }}>
                    AI engineer
                </span>
                <div style={{ marginLeft: "auto" }}>
                    <ModeSwitch />
                </div>
                {health && (
                    <span
                        title={
                            `model: ${health.model} (${health.provider})` +
                            (health.endpoint ? ` @ ${health.endpoint}` : "") +
                            `\nbuilder: ${health.builder} (${health.builder_mode})`
                        }
                        className="of-num"
                        style={{ display: "flex", alignItems: "center", gap: "5px", fontSize: "9.5px" }}
                    >
                        {/* Which model is actually live. Stated up front so a
                            demo can never imply our model when it is not. */}
                        <span style={{ color: health.serving_our_model ? "var(--st-verify)" : "var(--st-caution)" }}>
                            {health.serving_our_model ? "orionflow" : "fallback"}
                        </span>
                        <span style={{ color: health.builder === "freecad" ? "var(--st-pencil)" : "var(--st-redline)" }}>
                            {health.builder === "freecad" ? "kernel ✓" : "no kernel"}
                        </span>
                    </span>
                )}
            </div>

            {/* messages */}
            <div
                ref={scrollRef}
                className="studio-scroll"
                style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "16px 14px" }}
            >
                {messages.length === 0 ? (
                    <div style={{ paddingTop: "14px" }}>
                        <AgentAvatar size={38} />
                        <p className="of-report-head" style={{ margin: "14px 0 8px", fontSize: "20px", color: "var(--st-ink)", lineHeight: 1.25 }}>
                            Describe your design in plain English.
                        </p>
                        <p style={{ margin: 0, fontSize: "12.5px", lineHeight: 1.65, color: "var(--st-graphite)" }}>
                            The AI engineer helps you plan dimensions, materials and
                            manufacturability before you build. Start in <strong style={{ color: "var(--st-ink)" }}>Refine</strong> to
                            settle the numbers, then press <strong style={{ color: "var(--st-ink)" }}>Build this</strong> — or
                            switch to <strong style={{ color: "var(--st-ink)" }}>Build</strong> and go straight to a model.
                        </p>
                        <div style={{ marginTop: "16px", display: "flex", flexDirection: "column", gap: "6px" }}>
                            {STARTERS.map((s) => (
                                <button
                                    key={s}
                                    onClick={() => setValue(s)}
                                    style={{
                                        textAlign: "left",
                                        padding: "8px 10px",
                                        borderRadius: "6px",
                                        background: "var(--st-raise)",
                                        border: "1px solid var(--st-rule)",
                                        color: "var(--st-graphite)",
                                        fontSize: "12px",
                                        lineHeight: 1.45,
                                        cursor: "pointer",
                                    }}
                                    onMouseEnter={(e) => {
                                        e.currentTarget.style.color = "var(--st-ink)";
                                        e.currentTarget.style.borderColor = "var(--st-blue)";
                                    }}
                                    onMouseLeave={(e) => {
                                        e.currentTarget.style.color = "var(--st-graphite)";
                                        e.currentTarget.style.borderColor = "var(--st-rule)";
                                    }}
                                >
                                    {s}
                                </button>
                            ))}
                        </div>
                    </div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
                        {messages.map((m, i) => (
                            <Message
                                key={m.id}
                                msg={m}
                                priorUser={messages[i - 1]?.role === "user" ? messages[i - 1].content : ""}
                            />
                        ))}
                    </div>
                )}
            </div>

            {/* composer */}
            <div style={{ padding: "10px 11px 11px", borderTop: "1px solid var(--st-rule)", flexShrink: 0 }}>
                <div
                    style={{
                        background: "var(--st-raise)",
                        border: "1px solid var(--st-rule)",
                        borderRadius: "9px",
                        padding: "9px 9px 8px 11px",
                        display: "flex",
                        flexDirection: "column",
                        gap: "8px",
                    }}
                >
                    <div style={{ display: "flex", alignItems: "flex-end", gap: "8px" }}>
                        <textarea
                            ref={areaRef}
                            value={value}
                            onChange={(e) => setValue(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === "Enter" && !e.shiftKey) {
                                    e.preventDefault();
                                    submit();
                                }
                            }}
                            rows={1}
                            placeholder={
                                mode === "refine"
                                    ? hasPart
                                        ? "Ask about this part, or refine it…"
                                        : "Describe what you need and we'll pin down the numbers…"
                                    : "Describe the part to build…"
                            }
                            style={{
                                flex: 1,
                                background: "transparent",
                                border: "none",
                                outline: "none",
                                resize: "none",
                                padding: 0,
                                color: "var(--st-ink)",
                                fontSize: "13px",
                                lineHeight: "22px",
                                minHeight: "22px",
                                maxHeight: "130px",
                                fontFamily: "inherit",
                            }}
                        />
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "7px" }}>
                        <LensPicker />
                        <button
                            onClick={submit}
                            disabled={!value.trim() || busy}
                            title={mode === "refine" ? "Ask (Enter)" : "Build (Enter)"}
                            style={{
                                marginLeft: "auto",
                                width: "28px",
                                height: "28px",
                                borderRadius: "6px",
                                border: "none",
                                flexShrink: 0,
                                background: value.trim() && !busy ? "var(--st-blue)" : "var(--st-rule)",
                                color: value.trim() && !busy ? "#12100B" : "var(--st-pencil)",
                                cursor: value.trim() && !busy ? "pointer" : "default",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                            }}
                        >
                            {busy ? <Loader2 size={13} className="of-spin" /> : <ArrowUp size={14} />}
                        </button>
                    </div>
                </div>
                <div style={{ marginTop: "6px", fontSize: "10.5px", color: "var(--st-pencil)", lineHeight: 1.45 }}>
                    {mode === "refine"
                        ? "Refine settles dimensions and manufacturability. Nothing is built until you say so."
                        : hasPart
                          ? "A new description builds a new part. Questions are answered from this part's Blueprint and its verification report."
                          : "Build derives the geometry, predicts what it should measure, then checks the kernel agrees."}
                </div>
            </div>
        </div>
    );
}
