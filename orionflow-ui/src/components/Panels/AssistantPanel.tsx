import { useEffect, useRef, useState } from "react";
import {
    ArrowUp,
    ChevronDown,
    ChevronRight,
    Download,
    Loader2,
    Sparkles,
    AlertCircle,
} from "lucide-react";
import OrionFlowLogo from "../OrionFlowLogo";
import VerificationCard from "./VerificationCard";
import { useStudioStore, type StudioMessage, type DesignOutcome } from "../../store/studioStore";
import {
    fetchStudioHealth,
    fullUrl,
    type StudioHealth,
    type StudioStep,
    type DesignNarrative,
} from "../../services/studioApi";

/* ────────────────────────── bits ────────────────────────── */

function AgentAvatar({ size = 22 }: { size?: number }) {
    return (
        <div
            style={{
                width: size,
                height: size,
                borderRadius: Math.round(size / 4),
                background: "var(--studio-accent)",
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
    const ours = model === "orionflow";
    return (
        <span
            title={ours ? "OrionFlow fine-tuned model" : `Fallback model: ${model}`}
            style={{
                fontSize: "9.5px",
                fontWeight: 700,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                padding: "2px 6px",
                borderRadius: "4px",
                color: ours ? "var(--studio-accent)" : "var(--studio-warn)",
                background: ours ? "var(--studio-accent-dim)" : "rgba(217,164,65,0.14)",
                border: `1px solid ${ours ? "rgba(138,165,230,0.3)" : "rgba(217,164,65,0.3)"}`,
            }}
        >
            {ours ? "OrionFlow" : "Fallback"}
        </span>
    );
}

/** The live progress list.
 *
 *  Every row is a stage the server actually reported reaching, with the real
 *  thing it found — the part class it recognised, the features it is building,
 *  the checks it ran. Nothing here is on a timer, so a stage that stalls looks
 *  stalled instead of animating towards a result that is not coming.
 */
function Steps({ steps }: { steps: StudioStep[] }) {
    if (!steps.length) return null;
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: "5px", margin: "2px 0 4px" }}>
            {steps.map((s) => {
                const color =
                    s.status === "done"
                        ? "var(--studio-ok)"
                        : s.status === "fail"
                          ? "var(--studio-err)"
                          : "var(--studio-accent)";
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
                            <span style={{ color: s.status === "active" ? "var(--studio-text)" : "var(--studio-text-dim)" }}>
                                {s.label}
                            </span>
                            {s.detail && (
                                <span
                                    style={{
                                        marginLeft: "auto",
                                        fontFamily: "var(--font-mono)",
                                        fontSize: "10px",
                                        color: "var(--studio-text-faint)",
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
                                        style={{
                                            fontSize: "10.5px",
                                            fontFamily: "var(--font-mono)",
                                            color: "var(--studio-text-faint)",
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

/** Minimal inline markdown: **bold** only. The narrative is generated by us,
 *  so the input set is known — a full markdown renderer would be weight for
 *  nothing. */
function RichText({ text }: { text: string }) {
    const parts = text.split(/(\*\*[^*]+\*\*)/g);
    return (
        <>
            {parts.map((p, i) =>
                p.startsWith("**") && p.endsWith("**") ? (
                    <strong key={i} style={{ color: "var(--studio-text)", fontWeight: 650 }}>
                        {p.slice(2, -2)}
                    </strong>
                ) : (
                    <span key={i}>{p}</span>
                )
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
                    <div
                        style={{
                            fontSize: "10px",
                            fontWeight: 700,
                            letterSpacing: "0.09em",
                            textTransform: "uppercase",
                            color: "var(--studio-text-faint)",
                            marginBottom: "4px",
                        }}
                    >
                        {sec.title}
                    </div>
                    <div
                        style={{
                            fontSize: "12.5px",
                            lineHeight: 1.65,
                            color: "var(--studio-text-dim)",
                        }}
                    >
                        <RichText text={sec.body} />
                    </div>
                    {sec.items && sec.items.length > 0 && (
                        <ul
                            style={{
                                margin: "6px 0 0",
                                paddingLeft: "16px",
                                display: "flex",
                                flexDirection: "column",
                                gap: "3px",
                            }}
                        >
                            {sec.items.map((it, i) => (
                                <li
                                    key={i}
                                    style={{
                                        fontSize: "12px",
                                        lineHeight: 1.55,
                                        color: "var(--studio-text-dim)",
                                    }}
                                >
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

/** A collapsed drawer of machine-readable detail.
 *
 *  The Blueprint and the model's raw derivation stay exactly as they are —
 *  they are the reproducible record and the first thing to reach for when a
 *  part is wrong. They are just no longer the thing a user is shown first:
 *  working notes are not an explanation, and raw JSON makes a mechanical
 *  engineering system read as a code generator.
 */
function Drawer({ label, text }: { label: string; text: string }) {
    const [open, setOpen] = useState(false);
    if (!text.trim()) return null;

    return (
        <div style={{ marginTop: "6px" }}>
            <button
                onClick={() => setOpen(!open)}
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "5px",
                    background: "transparent",
                    border: "none",
                    padding: 0,
                    cursor: "pointer",
                    color: "var(--studio-text-faint)",
                    fontSize: "10px",
                    fontWeight: 600,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                }}
            >
                {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                {label}
            </button>
            {open && (
                <pre
                    className="studio-scroll"
                    style={{
                        margin: "5px 0 0",
                        padding: "8px 10px",
                        maxHeight: "240px",
                        overflowY: "auto",
                        background: "var(--studio-panel-2)",
                        border: "1px solid var(--studio-border)",
                        borderRadius: "6px",
                        fontFamily: "var(--font-mono)",
                        fontSize: "10px",
                        lineHeight: 1.55,
                        color: "var(--studio-text-faint)",
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
                    style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: "10px",
                        padding: "2.5px 7px",
                        borderRadius: "4px",
                        background: "var(--studio-panel-2)",
                        border: "1px solid var(--studio-border)",
                        color: "var(--studio-text-dim)",
                    }}
                >
                    {k}&nbsp;<span style={{ color: "var(--studio-text)" }}>{v}</span>
                </span>
            ))}
        </div>
    );
}

function Exports({ files }: { files: DesignOutcome["files"] }) {
    const entries = (
        [
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
                        borderRadius: "6px",
                        fontSize: "11px",
                        fontWeight: 600,
                        background: "var(--studio-panel-2)",
                        border: "1px solid var(--studio-border)",
                        color: "var(--studio-text)",
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

function Message({ msg }: { msg: StudioMessage }) {
    if (msg.role === "user") {
        return (
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <div
                    style={{
                        maxWidth: "88%",
                        padding: "8px 11px",
                        borderRadius: "10px 10px 2px 10px",
                        background: "var(--studio-accent-dim)",
                        border: "1px solid rgba(138,165,230,0.25)",
                        color: "var(--studio-text)",
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

    return (
        <div>
            <div style={{ display: "flex", alignItems: "center", gap: "7px", marginBottom: "7px" }}>
                <AgentAvatar />
                <span style={{ fontSize: "12.5px", fontWeight: 600, color: "var(--studio-text)" }}>
                    Orion
                </span>
                <ModelBadge model={msg.model} />
                {msg.design && (
                    <span
                        style={{
                            marginLeft: "auto",
                            fontSize: "10px",
                            color: "var(--studio-text-faint)",
                            fontFamily: "var(--font-mono)",
                        }}
                    >
                        {(msg.design.generationTimeMs / 1000).toFixed(1)}s
                    </span>
                )}
            </div>

            <div style={{ paddingLeft: "29px" }}>
                <Steps steps={msg.steps} />

                {msg.narrative && (
                    <>
                        <div
                            style={{
                                fontSize: "13px",
                                fontWeight: 650,
                                color: "var(--studio-text)",
                                marginTop: "8px",
                            }}
                        >
                            {msg.narrative.headline}
                        </div>
                        <Narrative narrative={msg.narrative} />
                    </>
                )}

                {msg.content && (
                    <p
                        style={{
                            margin: "8px 0 0",
                            fontSize: "13px",
                            lineHeight: 1.6,
                            color: "var(--studio-text)",
                            whiteSpace: "pre-wrap",
                        }}
                    >
                        {msg.content}
                    </p>
                )}

                {msg.error && (
                    <div
                        style={{
                            marginTop: "8px",
                            padding: "9px 11px",
                            borderRadius: "8px",
                            background: "var(--studio-panel-2)",
                            border: "1px solid var(--studio-err)",
                            color: "var(--studio-err)",
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

                {msg.design && (
                    <div style={{ marginTop: "10px", display: "flex", flexDirection: "column", gap: "8px" }}>
                        <VerificationCard report={msg.design.verification} />
                        <VariableChips variables={msg.design.variables} />
                        <Exports files={msg.design.files} />
                        {/* Kept verbatim and reachable: the Blueprint is the
                            reproducible record, and the raw completion is what
                            to diff when a part comes out wrong. */}
                        <div>
                            <Drawer
                                label="Blueprint JSON"
                                text={
                                    msg.design.blueprint
                                        ? JSON.stringify(msg.design.blueprint, null, 2)
                                        : ""
                                }
                            />
                            <Drawer label="Raw model output" text={msg.thinking} />
                        </div>
                    </div>
                )}
            </div>
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
        <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
            {/* header */}
            <div
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    padding: "10px 12px",
                    borderBottom: "1px solid var(--studio-border)",
                    flexShrink: 0,
                }}
            >
                <Sparkles size={13} color="var(--studio-accent)" />
                <span style={{ fontSize: "12px", fontWeight: 700, color: "var(--studio-text)" }}>
                    Design assistant
                </span>
                {health && (
                    <span
                        title={
                            `model: ${health.model} (${health.provider})` +
                            // Redacted by the server for anonymous callers.
                            (health.endpoint ? ` @ ${health.endpoint}` : "") +
                            `\nbuilder: ${health.builder} (${health.builder_mode})`
                        }
                        style={{
                            marginLeft: "auto",
                            display: "flex",
                            alignItems: "center",
                            gap: "6px",
                            fontSize: "10px",
                            fontFamily: "var(--font-mono)",
                            color: "var(--studio-text-faint)",
                        }}
                    >
                        {/* Which model is actually live. Stated up front so a
                            demo can never imply our model when it is not. */}
                        <span
                            style={{
                                color: health.serving_our_model
                                    ? "var(--studio-ok)"
                                    : "var(--studio-warn)",
                            }}
                        >
                            {health.serving_our_model ? "orionflow" : "fallback"}
                        </span>
                        <span
                            style={{
                                color:
                                    health.builder === "freecad"
                                        ? "var(--studio-text-faint)"
                                        : "var(--studio-err)",
                            }}
                        >
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
                    <div style={{ paddingTop: "18px" }}>
                        <AgentAvatar size={40} />
                        <p
                            style={{
                                margin: "14px 0 6px",
                                fontSize: "15px",
                                fontWeight: 600,
                                color: "var(--studio-text)",
                            }}
                        >
                            Describe the part you need
                        </p>
                        <p
                            style={{
                                margin: 0,
                                fontSize: "12.5px",
                                lineHeight: 1.6,
                                color: "var(--studio-text-dim)",
                            }}
                        >
                            I derive the geometry, predict what it should measure, then build
                            it and check the kernel agrees. You will see the derivation and
                            every check that ran — including the ones that fail.
                        </p>
                        <div style={{ marginTop: "16px", display: "flex", flexDirection: "column", gap: "6px" }}>
                            {STARTERS.map((s) => (
                                <button
                                    key={s}
                                    onClick={() => setValue(s)}
                                    style={{
                                        textAlign: "left",
                                        padding: "8px 10px",
                                        borderRadius: "7px",
                                        background: "var(--studio-panel-2)",
                                        border: "1px solid var(--studio-border)",
                                        color: "var(--studio-text-dim)",
                                        fontSize: "12px",
                                        lineHeight: 1.45,
                                        cursor: "pointer",
                                    }}
                                    onMouseEnter={(e) => {
                                        e.currentTarget.style.color = "var(--studio-text)";
                                        e.currentTarget.style.borderColor = "var(--studio-accent)";
                                    }}
                                    onMouseLeave={(e) => {
                                        e.currentTarget.style.color = "var(--studio-text-dim)";
                                        e.currentTarget.style.borderColor = "var(--studio-border)";
                                    }}
                                >
                                    {s}
                                </button>
                            ))}
                        </div>
                    </div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
                        {messages.map((m) => (
                            <Message key={m.id} msg={m} />
                        ))}
                    </div>
                )}
            </div>

            {/* composer */}
            <div style={{ padding: "12px", borderTop: "1px solid var(--studio-border)", flexShrink: 0 }}>
                <div
                    style={{
                        background: "var(--studio-panel-2)",
                        border: "1px solid var(--studio-border)",
                        borderRadius: "10px",
                        padding: "10px 10px 10px 12px",
                        display: "flex",
                        alignItems: "flex-end",
                        gap: "8px",
                    }}
                >
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
                            hasPart
                                ? "Ask about this part, or describe the next one…"
                                : "Describe a part…"
                        }
                        style={{
                            flex: 1,
                            background: "transparent",
                            border: "none",
                            outline: "none",
                            resize: "none",
                            color: "var(--studio-text)",
                            fontSize: "13px",
                            lineHeight: "22px",
                            minHeight: "22px",
                            maxHeight: "130px",
                            fontFamily: "inherit",
                        }}
                    />
                    <button
                        onClick={submit}
                        disabled={!value.trim() || busy}
                        style={{
                            width: "30px",
                            height: "30px",
                            borderRadius: "7px",
                            border: "none",
                            flexShrink: 0,
                            background: value.trim() && !busy ? "var(--studio-accent)" : "var(--studio-border)",
                            color: value.trim() && !busy ? "#fff" : "var(--studio-text-faint)",
                            cursor: value.trim() && !busy ? "pointer" : "default",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                        }}
                    >
                        {busy ? <Loader2 size={14} className="of-spin" /> : <ArrowUp size={15} />}
                    </button>
                </div>
                {hasPart && (
                    <div
                        style={{
                            marginTop: "7px",
                            fontSize: "10.5px",
                            color: "var(--studio-text-faint)",
                            lineHeight: 1.4,
                        }}
                    >
                        Questions are answered from this part's Blueprint and its verification
                        report — a new description builds a new part.
                    </div>
                )}
            </div>
        </div>
    );
}
