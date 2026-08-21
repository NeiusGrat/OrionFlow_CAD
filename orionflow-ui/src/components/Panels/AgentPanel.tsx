import { useEffect, useMemo, useRef, useState } from "react";
import {
    ArrowUp,
    ChevronDown,
    ChevronRight,
    ClipboardCheck,
    Download,
    Loader2,
    AlertTriangle,
    Hammer,
    X,
} from "lucide-react";
import Markdown from "./Markdown";
import SessionPanel from "./SessionPanel";
import VerificationCard from "./VerificationCard";
import {
    useStudioStore,
    type StudioMessage,
    type DesignOutcome,
    type AgentAction,
    type ToolCheck,
} from "../../store/studioStore";
import { useEditStore } from "../../store/editStore";
import { route, INTENT_VERB, type AgentIntent } from "../../lib/intent";
import {
    fetchStudioHealth,
    fullUrl,
    LENSES,
    type StudioHealth,
    type StudioStep,
    type DesignNarrative,
    type Lens,
} from "../../services/studioApi";

/**
 * Orion — one agent, one conversation.
 *
 * This replaces four separate surfaces: an Assistant tab with a Refine/Build
 * switch, a Reviewed-build tab, and a Selection tab. The user no longer
 * declares which of those they want before speaking; they say the thing, and
 * the router in `lib/intent.ts` decides. What the router decided is shown
 * beneath the composer *before* Enter is pressed, so the one risk of inferring
 * intent — silently doing the wrong thing — is answered by never doing it
 * silently.
 *
 * The transcript distinguishes two kinds of turn on purpose. Prose is a claim;
 * a chip is a change. `SELECTED · 2 holes on the left` and
 * `EDITED · plate_t 8 → 13 mm` are things that happened to the model, and they
 * read as a record of work when you scroll back through a session.
 */

/* ────────────────────────── small parts ────────────────────────── */

function Dot({ tone, live }: { tone: string; live?: boolean }) {
    return (
        <span
            className={live ? "of-live" : undefined}
            style={{
                width: "5px",
                height: "5px",
                borderRadius: "50%",
                background: tone,
                flexShrink: 0,
                display: "inline-block",
            }}
        />
    );
}

const TONE: Record<AgentAction["tone"], string> = {
    ok: "var(--st-verify)",
    fail: "var(--st-redline)",
    info: "var(--st-caution)",
};

/** One thing that happened to the model. */
function ActionChip({ action }: { action: AgentAction }) {
    return (
        <span className="of-chip" title={`${action.verb} — ${action.what}`}>
            <span className="of-chip__verb" style={{ color: TONE[action.tone] }}>
                {action.verb}
            </span>
            <span className="of-chip__what of-num">{action.what}</span>
            {action.note && <span className="of-chip__note">{action.note}</span>}
        </span>
    );
}

function Actions({ actions }: { actions: AgentAction[] }) {
    if (!actions.length) return null;
    return (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "5px", margin: "9px 0 3px" }}>
            {actions.map((a, i) => (
                <ActionChip key={i} action={a} />
            ))}
        </div>
    );
}

/** What each tool call means in plain words. An unfamiliar name falls back to
 *  itself rather than to a vague "checked something" — still a true statement. */
const CHECK_LABELS: Record<string, string> = {
    list_objects: "what the part is made of",
    inspect_topology: "the built topology",
    expand_topology: "one shape in full",
    get_parameters: "a feature's dimensions",
    get_featuregraph: "how the part was built",
    get_model_tier: "how the part can be edited",
    measure: "the built geometry",
    lookup_standard: "a standard",
    lookup_mechanical_knowledge: "mechanical data",
    lookup_nasa_requirement: "a NASA requirement",
    resolve_design_context: "the design context",
    calculate_sheet_metal_bend: "a bend allowance",
    check_sheet_metal_dfm: "sheet-metal DFM",
    lookup_robotics_knowledge: "robotics data",
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

/**
 * What the agent went and checked before answering.
 *
 * Shown rather than summarised away: an answer that measured the part and one
 * that recalled a number look identical in prose, and only this tells them
 * apart. A failed call stays on the list — a lookup that found nothing is a
 * reason to trust the answer less, not something to hide.
 */
function Checks({ checks }: { checks: ToolCheck[] }) {
    if (!checks.length) return null;
    return (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "5px", margin: "8px 0 3px" }}>
            {checks.map((c, i) => {
                const detail = checkDetail(c.arguments);
                return (
                    <span className="of-chip" key={i} title={c.name}>
                        <span
                            className="of-chip__verb"
                            style={{ color: c.ok ? "var(--st-verify)" : "var(--st-redline)" }}
                        >
                            {c.ok ? "read" : "missed"}
                        </span>
                        <span className="of-chip__what">{CHECK_LABELS[c.name] ?? c.name}</span>
                        {detail && <span className="of-chip__note">{detail}</span>}
                    </span>
                );
            })}
        </div>
    );
}

/** The live progress list — every row a stage the server actually reported
 *  reaching. Nothing is on a timer, so a stage that stalls looks stalled
 *  instead of animating towards a result that is not coming. */
function Steps({ steps }: { steps: StudioStep[] }) {
    if (!steps.length) return null;
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: "6px", margin: "4px 0 2px" }}>
            {steps.map((s) => {
                const tone =
                    s.status === "done"
                        ? "var(--st-verify)"
                        : s.status === "fail"
                          ? "var(--st-redline)"
                          : "var(--st-ink)";
                return (
                    <div key={s.id}>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "12px" }}>
                            {s.status === "active" ? (
                                <Loader2 size={10} className="of-spin" style={{ color: tone, flexShrink: 0 }} />
                            ) : (
                                <Dot tone={tone} />
                            )}
                            <span
                                className={s.status === "active" ? "of-shimmer" : undefined}
                                style={{
                                    color: s.status === "active" ? "var(--st-ink)" : "var(--st-graphite)",
                                }}
                            >
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
                                        maxWidth: "52%",
                                        overflow: "hidden",
                                        textOverflow: "ellipsis",
                                        whiteSpace: "nowrap",
                                    }}
                                >
                                    {s.detail}
                                </span>
                            )}
                        </div>
                        {s.status !== "active" && s.items.length > 0 && (
                            <div style={{ paddingLeft: "13px", marginTop: "3px" }}>
                                {s.items.slice(0, 8).map((it, i) => (
                                    <div
                                        key={i}
                                        className="of-num"
                                        style={{
                                            fontSize: "10.5px",
                                            color: "var(--st-pencil)",
                                            lineHeight: 1.55,
                                            whiteSpace: "nowrap",
                                            overflow: "hidden",
                                            textOverflow: "ellipsis",
                                        }}
                                    >
                                        {it}
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

/** Which model answered. A fallback is always named — a demo that quietly
 *  degrades to a general model is worse than one that stops, because nobody can
 *  tell which system produced the result. */
function ModelBadge({ model }: { model: string }) {
    if (!model) return null;
    const compiled = model.startsWith("compiled:");
    const readBy = compiled ? model.slice("compiled:".length) : "";
    const ours = model === "orionflow" || compiled;
    return (
        <span
            className="of-label"
            title={
                compiled
                    ? `Blueprint compiled deterministically in Python — ${readBy} only read the request into named fields, and authored no geometry`
                    : ours
                      ? "OrionFlow fine-tuned model"
                      : `Fallback model: ${model}`
            }
            style={{ color: ours ? "var(--st-pencil)" : "var(--st-caution)", letterSpacing: "0.1em" }}
        >
            {compiled ? "compiled" : ours ? "orionflow" : "fallback"}
        </span>
    );
}

function LensTag({ lens }: { lens: Lens }) {
    if (lens === "modeling") return null;
    const label = LENSES.find((l) => l.id === lens)?.label ?? lens;
    return (
        <span className="of-label" style={{ letterSpacing: "0.1em" }}>
            {label}
        </span>
    );
}

/** The engineering account of the design — what it understood, how it built it,
 *  why, and what was actually proved. */
function Narrative({ narrative }: { narrative: DesignNarrative }) {
    return (
        <div style={{ marginTop: "10px", display: "flex", flexDirection: "column", gap: "13px" }}>
            {narrative.sections.map((sec) => (
                <div key={sec.title}>
                    <div className="of-label" style={{ marginBottom: "5px" }}>
                        {sec.title}
                    </div>
                    <Markdown text={sec.body} />
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
                                    style={{ fontSize: "12px", lineHeight: 1.6, color: "var(--st-graphite)" }}
                                >
                                    <Markdown text={it} />
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
 *  derivation stay reachable — they are the reproducible record — but working
 *  notes are not an explanation, so they are not shown first. */
function Drawer({ label, text }: { label: string; text: string }) {
    const [open, setOpen] = useState(false);
    if (!text.trim()) return null;
    return (
        <div style={{ marginTop: "7px" }}>
            <button
                onClick={() => setOpen(!open)}
                className="of-label"
                style={{ display: "flex", alignItems: "center", gap: "5px", background: "transparent", border: "none", padding: 0, cursor: "pointer" }}
            >
                {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                {label}
            </button>
            {open && (
                <pre
                    className="studio-scroll of-num"
                    style={{
                        margin: "6px 0 0",
                        padding: "9px 11px",
                        maxHeight: "240px",
                        overflowY: "auto",
                        background: "var(--st-raise)",
                        border: "1px solid var(--st-rule)",
                        borderRadius: "var(--st-r)",
                        fontSize: "10px",
                        lineHeight: 1.6,
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
        <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", marginTop: "9px" }}>
            {entries.map(([k, v]) => (
                <span
                    key={k}
                    className="of-num"
                    style={{
                        fontSize: "10px",
                        padding: "3px 7px",
                        borderRadius: "var(--st-r-sm)",
                        background: "var(--st-raise)",
                        border: "1px solid var(--st-rule)",
                        color: "var(--st-pencil)",
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
        <div style={{ display: "flex", gap: "5px", marginTop: "9px", flexWrap: "wrap" }}>
            {entries.map(([name, url]) => (
                <a key={name} href={fullUrl(url as string)} download className="of-btn" style={{ padding: "5px 10px", fontSize: "11px" }}>
                    <Download size={10} />
                    {name}
                </a>
            ))}
        </div>
    );
}

/** Turns a specified brief into a build without retyping it. */
function BuildThis({ brief }: { brief: string }) {
    const buildThis = useStudioStore((s) => s.buildThis);
    const busy = useStudioStore((s) => s.busy);
    return (
        <button
            onClick={() => void buildThis(brief)}
            disabled={busy}
            className="of-btn"
            style={{ marginTop: "11px", fontSize: "11.5px" }}
            title="Build the part this conversation has specified"
        >
            <Hammer size={11} />
            Build this
        </button>
    );
}

/** A question the agent needs settled. Rendered as buttons, resolved in place. */
function Choice({ msg }: { msg: StudioMessage }) {
    const resolve = useStudioStore((s) => s.resolveChoice);
    const busy = useStudioStore((s) => s.busy);
    const choice = msg.choice;
    if (!choice) return null;

    return (
        <div style={{ marginTop: "10px" }}>
            <div className="of-label" style={{ marginBottom: "6px" }}>
                {choice.question}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "5px" }}>
                {choice.options.map((o) => {
                    const picked = choice.chosen === o.id;
                    const settled = !!choice.chosen;
                    return (
                        <button
                            key={o.id}
                            disabled={settled || busy}
                            onClick={() => void resolve(msg.id, o.id)}
                            className="of-row"
                            style={{
                                display: "flex",
                                alignItems: "baseline",
                                gap: "8px",
                                width: "100%",
                                padding: "7px 10px",
                                textAlign: "left",
                                borderRadius: "var(--st-r)",
                                border: `1px solid ${picked ? "var(--st-blue-edge)" : "var(--st-rule)"}`,
                                background: picked ? "var(--st-blue-wash)" : "var(--st-raise)",
                                color: settled && !picked ? "var(--st-pencil)" : "var(--st-ink)",
                                cursor: settled ? "default" : "pointer",
                                opacity: settled && !picked ? 0.5 : 1,
                            }}
                        >
                            <span style={{ fontSize: "12px", fontWeight: 500 }}>{o.label}</span>
                            <span className="of-num" style={{ fontSize: "10px", color: "var(--st-pencil)", marginLeft: "auto" }}>
                                {o.hint}
                            </span>
                        </button>
                    );
                })}
            </div>
        </div>
    );
}

/* ────────────────────────── one turn ────────────────────────── */

function Message({ msg, priorUser }: { msg: StudioMessage; priorUser: string }) {
    if (msg.role === "user") {
        return (
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <div
                    style={{
                        maxWidth: "86%",
                        padding: "9px 12px",
                        borderRadius: "var(--st-r-lg) var(--st-r-lg) var(--st-r-xs) var(--st-r-lg)",
                        background: "var(--st-blue-wash)",
                        border: "1px solid var(--st-rule)",
                        color: "var(--st-ink)",
                        fontSize: "13px",
                        lineHeight: 1.55,
                        whiteSpace: "pre-wrap",
                    }}
                >
                    {msg.content}
                </div>
            </div>
        );
    }

    // A specified part that was never built is worth an explicit offer; a build
    // answer already is one.
    const offersBuild =
        msg.intent === "ask" && !msg.streaming && !!msg.content && !msg.error && !msg.design;

    const working = msg.streaming && !msg.content && !msg.steps.length && !msg.actions.length;

    return (
        <div className="of-rise">
            {/* attribution row */}
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                <span
                    className="of-label"
                    style={{ color: "var(--st-ink)", letterSpacing: "0.16em", fontWeight: 600 }}
                >
                    Orion
                </span>
                <span
                    className="of-label"
                    title={msg.routedBecause ? `Routed here because ${msg.routedBecause}` : undefined}
                    style={{
                        padding: "1px 5px",
                        border: "1px solid var(--st-rule)",
                        borderRadius: "var(--st-r-xs)",
                        color: "var(--st-pencil)",
                    }}
                >
                    {msg.intent}
                </span>
                <LensTag lens={msg.lens} />
                <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "8px" }}>
                    <ModelBadge model={msg.model} />
                    {msg.design && (
                        <span className="of-num" style={{ fontSize: "10px", color: "var(--st-pencil)" }}>
                            {(msg.design.generationTimeMs / 1000).toFixed(1)}s
                        </span>
                    )}
                </div>
            </div>

            <div style={{ paddingLeft: "1px" }}>
                {working && (
                    <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "12.5px" }}>
                        <Loader2 size={11} className="of-spin" style={{ color: "var(--st-pencil)" }} />
                        <span className="of-shimmer">{INTENT_VERB[msg.intent]}…</span>
                    </div>
                )}

                <Steps steps={msg.steps} />
                <Checks checks={msg.checks} />
                <Actions actions={msg.actions} />

                {msg.narrative && (
                    <>
                        <div
                            className="of-report-head"
                            style={{ fontSize: "17px", color: "var(--st-ink)", marginTop: "10px" }}
                        >
                            {msg.narrative.headline}
                        </div>
                        <Narrative narrative={msg.narrative} />
                    </>
                )}

                {msg.content && (
                    <div style={{ marginTop: msg.narrative ? "10px" : "2px" }}>
                        <Markdown text={msg.content} />
                        {msg.streaming && <span className="of-caret" aria-hidden />}
                    </div>
                )}

                <Choice msg={msg} />

                {/* The reviewed route, rendered where the conversation is
                    rather than in a tab of its own. It reads the live session
                    from its own store, so approving here is the same act it
                    always was — it just no longer lives somewhere else. */}
                {msg.showsSession && (
                    <div
                        style={{
                            marginTop: "10px",
                            border: "1px solid var(--st-rule)",
                            borderRadius: "var(--st-r-lg)",
                            background: "var(--st-sheet)",
                            overflow: "hidden",
                        }}
                    >
                        <SessionPanel />
                    </div>
                )}

                {msg.error && (
                    <div
                        style={{
                            marginTop: "10px",
                            padding: "10px 12px",
                            borderRadius: "var(--st-r)",
                            background: "var(--st-raise)",
                            borderLeft: "2px solid var(--st-redline)",
                            border: "1px solid var(--st-rule)",
                            borderLeftWidth: "2px",
                            borderLeftColor: "var(--st-redline)",
                            fontSize: "12.5px",
                            lineHeight: 1.6,
                        }}
                    >
                        <div style={{ display: "flex", gap: "8px", color: "var(--st-redline)" }}>
                            <AlertTriangle size={13} style={{ flexShrink: 0, marginTop: "2px" }} />
                            <span>{msg.error}</span>
                        </div>
                        {/* A failure that does not say what to try next is a
                            dead end, and a dead end in a conversation is worse
                            than an error in a form. */}
                        {msg.suggestion && (
                            <div style={{ marginTop: "7px", paddingLeft: "21px", color: "var(--st-graphite)" }}>
                                {msg.suggestion}
                            </div>
                        )}
                    </div>
                )}

                {!msg.error && msg.suggestion && (
                    <div style={{ marginTop: "8px", fontSize: "12px", color: "var(--st-graphite)" }}>
                        {msg.suggestion}
                    </div>
                )}

                {offersBuild && <BuildThis brief={`${priorUser}\n\n${msg.content}`.trim()} />}

                {msg.design && (
                    <div style={{ marginTop: "11px", display: "flex", flexDirection: "column", gap: "9px" }}>
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

/* ────────────────────────── composer ────────────────────────── */

/** What the agent is currently pointing at, carried into the next message.
 *
 *  Shown above the input rather than only in the viewport, because "make this
 *  10 mm deeper" is only unambiguous if both sides can see what "this" is. */
function SelectionChip() {
    const face = useEditStore((s) => s.selectedFace);
    const feature = useEditStore((s) => s.selectedFeature);
    const agentRefs = useEditStore((s) => s.agentRefs);
    const note = useEditStore((s) => s.agentSelectionNote);
    const clear = useEditStore((s) => s.clear);

    const label = face
        ? `${feature ?? "face"} · ${face.ref}`
        : agentRefs.length
          ? note || `${agentRefs.length} faces`
          : null;
    if (!label) return null;

    return (
        <div
            className="of-enter"
            style={{ display: "flex", alignItems: "center", gap: "7px", marginBottom: "7px" }}
        >
            <span className="of-chip" style={{ minWidth: 0 }}>
                <span className="of-chip__verb" style={{ color: "var(--st-ink)" }}>
                    in context
                </span>
                <span className="of-chip__what of-num">{label}</span>
            </span>
            <button
                onClick={clear}
                title="Clear the selection"
                className="of-btn of-btn--quiet"
                style={{ padding: "3px", borderRadius: "var(--st-r-sm)" }}
            >
                <X size={11} />
            </button>
        </div>
    );
}

const STARTERS = [
    "A clevis mount, base 48×32, 16 tall, 12 mm gap, 9.5 mm pivot bore",
    "Bearing housing for a 6004 bearing, bolted on a 62 mm PCD",
    "NEMA 17 motor mount, 6 mm plate, 22 mm pilot bore",
];

/** What the next message will do, worked out from the same router that will
 *  run it. Not a guess about the router — it *is* the router. */
function IntentPreview({ value }: { value: string }) {
    const part = useStudioStore((s) => s.part);
    const canSelect = useEditStore((s) => !!s.topology?.faces?.length);

    const routed = useMemo(() => {
        if (!value.trim()) return null;
        return route(value, {
            hasPart: !!part,
            canSelect,
            hasVariables: Object.keys(part?.variables ?? {}).length > 0,
        });
    }, [value, part, canSelect]);

    if (!routed) return null;

    const COST: Record<AgentIntent, string> = {
        build: "builds new geometry",
        modify: "rebuilds this part",
        select: "highlights only — no rebuild",
        review: "reads, changes nothing",
        ask: "reads, changes nothing",
    };

    return (
        <span
            className="of-label"
            style={{ display: "inline-flex", alignItems: "center", gap: "6px", minWidth: 0 }}
            title={`Routed here because ${routed.because}`}
        >
            <span style={{ color: "var(--st-ink)" }}>{routed.intent}</span>
            <span style={{ opacity: 0.65, letterSpacing: "0.04em", textTransform: "none", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {COST[routed.intent]}
            </span>
        </span>
    );
}

/**
 * Build now, or stop at a plan and wait to be read.
 *
 * Not a mode the user has to understand before they can speak — the router
 * still decides what the sentence is, and this only changes what happens when
 * the answer is "a build". Off by default; a request that wants the ceremony
 * usually knows it.
 */
function PlanFirstToggle() {
    const on = useStudioStore((s) => s.planFirst);
    const setOn = useStudioStore((s) => s.setPlanFirst);
    return (
        <button
            onClick={() => setOn(!on)}
            aria-pressed={on}
            title={
                on
                    ? "Builds will stop at a plan for you to approve"
                    : "Builds run straight through. Turn this on to approve the plan first."
            }
            className="of-label"
            style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "5px",
                padding: "3px 7px",
                borderRadius: "var(--st-r-sm)",
                border: `1px solid ${on ? "var(--st-blue-edge)" : "var(--st-rule)"}`,
                background: on ? "var(--st-blue-wash)" : "transparent",
                color: on ? "var(--st-ink)" : "var(--st-pencil)",
                cursor: "pointer",
                flexShrink: 0,
            }}
        >
            <ClipboardCheck size={10} />
            Plan first
        </button>
    );
}

/* ────────────────────────── the panel ────────────────────────── */

export default function AgentPanel() {
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

    // Follow the conversation, but only once there is one. On a short screen
    // the empty state is taller than the panel, and scrolling it to the bottom
    // on mount cut off the heading that says what this thing is — the first
    // thing a new user needs and the last thing they should have to scroll up
    // for.
    useEffect(() => {
        if (!messages.length) return;
        if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }, [messages]);

    useEffect(() => {
        if (areaRef.current) {
            areaRef.current.style.height = "22px";
            areaRef.current.style.height = Math.min(areaRef.current.scrollHeight, 148) + "px";
        }
    }, [value]);

    const submit = () => {
        if (!value.trim() || busy) return;
        void send(value);
        setValue("");
    };

    return (
        <div style={{ width: "100%", flex: 1, display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
            {/* ── header ── */}
            <div
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "9px",
                    padding: "0 13px",
                    height: "38px",
                    flexShrink: 0,
                    borderBottom: "1px solid var(--st-rule)",
                }}
            >
                <Dot tone={busy ? "var(--st-caution)" : "var(--st-verify)"} live={busy} />
                <span className="of-label" style={{ color: "var(--st-ink)", letterSpacing: "0.18em" }}>
                    Orion
                </span>
                {health && (
                    <span
                        className="of-label"
                        title={
                            `model: ${health.model} (${health.provider})` +
                            (health.endpoint ? ` @ ${health.endpoint}` : "") +
                            `\nbuilder: ${health.builder} (${health.builder_mode})`
                        }
                        style={{ marginLeft: "auto", display: "flex", gap: "9px", letterSpacing: "0.09em" }}
                    >
                        <span style={{ color: health.serving_our_model ? "var(--st-pencil)" : "var(--st-caution)" }}>
                            {health.serving_our_model ? "orionflow" : "fallback"}
                        </span>
                        <span style={{ color: health.builder === "freecad" ? "var(--st-pencil)" : "var(--st-redline)" }}>
                            {health.builder === "freecad" ? "kernel" : "no kernel"}
                        </span>
                    </span>
                )}
            </div>

            {/* ── transcript ── */}
            <div
                ref={scrollRef}
                className="studio-scroll"
                style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "20px 15px 8px" }}
            >
                {messages.length === 0 ? (
                    <div style={{ paddingTop: "6px" }}>
                        <p
                            className="of-report-head"
                            style={{ margin: "0 0 10px", fontSize: "23px", color: "var(--st-ink)" }}
                        >
                            Describe the part.
                        </p>
                        <p style={{ margin: 0, fontSize: "12.5px", lineHeight: 1.7, color: "var(--st-graphite)" }}>
                            One conversation for all of it — build a part, change a
                            dimension, select a feature, or ask for a manufacturability
                            review. You never have to pick a mode; say what you want and
                            I will work out which it is.
                        </p>

                        <div className="of-label" style={{ margin: "22px 0 8px" }}>
                            Try one
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: "5px" }}>
                            {STARTERS.map((s, i) => (
                                <button
                                    key={s}
                                    onClick={() => setValue(s)}
                                    className="of-row"
                                    style={{
                                        display: "flex",
                                        alignItems: "flex-start",
                                        gap: "10px",
                                        textAlign: "left",
                                        padding: "9px 11px",
                                        borderRadius: "var(--st-r)",
                                        background: "transparent",
                                        border: "1px solid var(--st-rule)",
                                        color: "var(--st-graphite)",
                                        fontSize: "12px",
                                        lineHeight: 1.5,
                                        cursor: "pointer",
                                    }}
                                >
                                    <span className="of-bracket" style={{ marginTop: "2px" }}>
                                        [{String(i + 1).padStart(2, "0")}]
                                    </span>
                                    <span>{s}</span>
                                </button>
                            ))}
                        </div>
                    </div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
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

            {/* ── composer ── */}
            <div style={{ padding: "10px 13px 12px", flexShrink: 0 }}>
                <SelectionChip />
                <div
                    style={{
                        background: "var(--st-raise)",
                        border: "1px solid var(--st-rule)",
                        borderRadius: "var(--st-r-lg)",
                        boxShadow: "var(--st-shadow-lift)",
                        padding: "10px 10px 8px 12px",
                        display: "flex",
                        flexDirection: "column",
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
                                ? "Change it, ask about it, select a feature, or describe a new part…"
                                : "Describe the part you need…"
                        }
                        style={{
                            width: "100%",
                            background: "transparent",
                            border: "none",
                            outline: "none",
                            resize: "none",
                            padding: 0,
                            color: "var(--st-ink)",
                            fontSize: "13px",
                            lineHeight: "22px",
                            minHeight: "22px",
                            maxHeight: "148px",
                            fontFamily: "inherit",
                        }}
                    />
                    <div style={{ display: "flex", alignItems: "center", gap: "9px", minWidth: 0 }}>
                        <PlanFirstToggle />
                        <IntentPreview value={value} />
                        <button
                            onClick={submit}
                            disabled={!value.trim() || busy}
                            title="Send (Enter)"
                            style={{
                                marginLeft: "auto",
                                width: "27px",
                                height: "27px",
                                borderRadius: "var(--st-r)",
                                border: "none",
                                flexShrink: 0,
                                background: value.trim() && !busy ? "var(--st-accent)" : "var(--st-rule)",
                                color: value.trim() && !busy ? "var(--st-on-accent)" : "var(--st-pencil)",
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
                <div style={{ marginTop: "7px", fontSize: "10.5px", color: "var(--st-pencil)", lineHeight: 1.5 }}>
                    Selections and dimension changes never call the model. Building does,
                    and derives the geometry, predicts what it should measure, then checks
                    the kernel agrees.
                </div>
            </div>
        </div>
    );
}
