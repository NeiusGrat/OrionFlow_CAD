/**
 * The plan, before it is a part.
 *
 * This panel exists because the approval gate is real: the server will not
 * build a design nobody has read, so there has to be somewhere to read it. What
 * it shows is the whole of what was decided before any geometry existed — the
 * dimensions, the checks that already ran, and the reasoning behind them — and
 * three ways to answer: yes, no, or change this.
 *
 * Two rules it follows strictly.
 *
 * **State comes from the server.** Every control is driven by `session.state`,
 * never by inferring from text or from what the user just clicked. The gate is
 * enforced in backend code and a UI that predicted its own state would sooner
 * or later offer Approve for a design that had already been superseded.
 *
 * **A check that did not run is not a check that passed.** The critique
 * distinguishes pass, fail and unknown, and `unknown` is rendered as its own
 * thing. Collapsing it into a tick would put a mark against something nobody
 * verified, which is the single failure this whole contract exists to prevent.
 */

import { useState } from "react";
import { useSessionStore } from "../../store/sessionStore";
import type { RevisionView, SessionState } from "../../services/sessionsApi";
import { fullUrl } from "../../services/http";

const STATE_LABEL: Record<SessionState, string> = {
    draft: "Starting",
    questions: "Needs more information",
    awaiting_approval: "Awaiting your approval",
    approved: "Approved — ready to build",
    building: "Building",
    built: "Built",
    needs_revision: "Needs revision",
    completed: "Accepted",
    rejected: "Rejected",
    cancelled: "Cancelled",
    failed: "Failed",
};

const STATE_TONE: Record<SessionState, string> = {
    draft: "var(--st-pencil)",
    questions: "var(--st-caution)",
    awaiting_approval: "var(--st-blue)",
    approved: "var(--st-blue)",
    building: "var(--st-blue)",
    built: "var(--st-verify)",
    needs_revision: "var(--st-caution)",
    completed: "var(--st-verify)",
    rejected: "var(--st-redline)",
    cancelled: "var(--st-pencil)",
    failed: "var(--st-redline)",
};

const CHECK_MARK = { pass: "✓", fail: "✕", unknown: "–" } as const;
const CHECK_TONE = {
    pass: "var(--st-verify)",
    fail: "var(--st-redline)",
    unknown: "var(--st-pencil)",
} as const;

const box: React.CSSProperties = {
    border: "1px solid var(--st-rule)",
    background: "var(--st-sheet)",
    padding: "10px 12px",
    marginBottom: "10px",
};

const label: React.CSSProperties = {
    fontSize: "10px",
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    color: "var(--st-pencil)",
    marginBottom: "6px",
};

function Button({
    children,
    onClick,
    tone = "quiet",
    disabled,
}: {
    children: React.ReactNode;
    onClick: () => void;
    tone?: "primary" | "quiet" | "danger";
    disabled?: boolean;
}) {
    const tones = {
        primary: { bg: "var(--st-blue)", fg: "var(--st-sheet)", edge: "var(--st-blue)" },
        quiet: { bg: "transparent", fg: "var(--st-ink)", edge: "var(--st-rule)" },
        danger: { bg: "transparent", fg: "var(--st-redline)", edge: "var(--st-redline)" },
    }[tone];
    return (
        <button
            onClick={onClick}
            disabled={disabled}
            style={{
                padding: "6px 12px",
                fontSize: "12px",
                fontFamily: "inherit",
                background: tones.bg,
                color: tones.fg,
                border: `1px solid ${tones.edge}`,
                cursor: disabled ? "default" : "pointer",
                opacity: disabled ? 0.45 : 1,
            }}
        >
            {children}
        </button>
    );
}

/** What the server refused, and what it means — never a bare sentence. */
function Refusal() {
    const error = useSessionStore((s) => s.error);
    const dismiss = useSessionStore((s) => s.dismissError);
    if (!error) return null;

    // `stale_revision` is the one a user can act on without understanding it:
    // the plan moved, so what is on screen is not what they were deciding
    // about. Everything else is shown with whatever the server attached.
    const advice =
        error.reason === "stale_revision"
            ? "The plan changed while you were reading it. Review the current one."
            : error.reason === "approval_required"
              ? "This design has not been approved yet."
              : error.reason === "blueprint_drifted"
                ? "The design changed after it was approved, so the approval no longer covers it."
                : "";

    return (
        <div
            style={{
                ...box,
                borderColor: "var(--st-redline)",
                background: "var(--st-raise)",
            }}
        >
            <div style={{ ...label, color: "var(--st-redline)" }}>{error.reason}</div>
            <div style={{ fontSize: "12px", marginBottom: advice ? "6px" : 0 }}>
                {error.message}
            </div>
            {advice && (
                <div style={{ fontSize: "11px", color: "var(--st-pencil)" }}>{advice}</div>
            )}
            <div style={{ marginTop: "8px" }}>
                <Button onClick={dismiss}>Dismiss</Button>
            </div>
        </div>
    );
}

function Critique({ revision }: { revision: RevisionView }) {
    const checks = revision.critique?.checks ?? [];
    if (!checks.length) return null;
    return (
        <div style={box}>
            <div style={label}>Checked before building</div>
            {checks.map((c) => (
                <div
                    key={c.id}
                    style={{ display: "flex", gap: "8px", fontSize: "12px", marginBottom: "4px" }}
                >
                    <span style={{ color: CHECK_TONE[c.status] ?? "var(--st-pencil)" }}>
                        {CHECK_MARK[c.status] ?? "–"}
                    </span>
                    <span>
                        {c.label}
                        <span style={{ color: "var(--st-pencil)" }}> — {c.detail}</span>
                    </span>
                </div>
            ))}
            {(revision.critique?.advisories ?? []).map((a, i) => (
                <div
                    key={i}
                    style={{ fontSize: "11px", color: "var(--st-caution)", marginTop: "4px" }}
                >
                    {a}
                </div>
            ))}
        </div>
    );
}

/**
 * The engineering review — separate from the critique, deliberately.
 *
 * The critique grades the model against the contract it wrote for itself. This
 * grades the part against mechanics, which the model was never asked to state.
 * Merging them into one list would let a satisfied precondition sit beside two
 * holes that physically overlap as though they were the same kind of fact.
 */
function Mechanical({ revision }: { revision: RevisionView }) {
    const findings = revision.mechanical?.findings ?? [];
    if (!findings.length) return null;
    return (
        <div style={box}>
            <div style={label}>Geometry review</div>
            {findings.map((f, i) => (
                <div key={i} style={{ display: "flex", gap: "8px", marginBottom: "5px" }}>
                    <span
                        style={{
                            color:
                                f.severity === "blocking"
                                    ? "var(--st-redline)"
                                    : "var(--st-caution)",
                            fontSize: "11px",
                        }}
                    >
                        {f.severity === "blocking" ? "✕" : "!"}
                    </span>
                    <span style={{ fontSize: "12px" }}>{f.message}</span>
                </div>
            ))}
            {(revision.mechanical?.blocking ?? 0) > 0 && (
                <div
                    style={{
                        fontSize: "11px",
                        color: "var(--st-pencil)",
                        marginTop: "6px",
                    }}
                >
                    These were measured from the resolved sketch, before anything was
                    built. A part with them will not come out as dimensioned.
                </div>
            )}
        </div>
    );
}

function Dimensions({ revision }: { revision: RevisionView }) {
    const entries = Object.entries(revision.variables ?? {});
    if (!entries.length) return null;
    return (
        <div style={box}>
            <div style={label}>Dimensions</div>
            <div
                style={{
                    display: "grid",
                    gridTemplateColumns: "1fr auto",
                    gap: "2px 12px",
                    fontSize: "12px",
                    fontFamily: "var(--st-mono, monospace)",
                }}
            >
                {entries.map(([k, v]) => (
                    <>
                        <span key={`${k}-n`} style={{ color: "var(--st-pencil)" }}>
                            {k}
                        </span>
                        <span key={`${k}-v`}>{v}</span>
                    </>
                ))}
            </div>
        </div>
    );
}

function Artifacts({ revision }: { revision: RevisionView }) {
    const files = revision.artifacts ?? {};
    // FCStd first: it is the only download that reopens as a parametric model
    // rather than a finished shape.
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
        <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginBottom: "10px" }}>
            {entries.map(([name, url]) => (
                <a
                    key={name}
                    href={fullUrl(url as string)}
                    download
                    style={{
                        fontSize: "11px",
                        padding: "4px 8px",
                        border: "1px solid var(--st-rule)",
                        color: "var(--st-ink)",
                        textDecoration: "none",
                    }}
                >
                    {name}
                </a>
            ))}
        </div>
    );
}

function History() {
    const history = useSessionStore((s) => s.session?.history ?? []);
    if (history.length < 2) return null;
    return (
        <div style={box}>
            <div style={label}>Revisions</div>
            {history.map((r) => (
                <div key={r.number} style={{ fontSize: "11px", marginBottom: "4px" }}>
                    <span style={{ color: "var(--st-pencil)" }}>#{r.number}</span>{" "}
                    <span>{r.origin}</span>
                    {r.instruction && (
                        <span style={{ color: "var(--st-pencil)" }}> — {r.instruction}</span>
                    )}
                    <span
                        style={{
                            color:
                                r.approval === "approved"
                                    ? "var(--st-verify)"
                                    : r.approval === "rejected"
                                      ? "var(--st-redline)"
                                      : "var(--st-pencil)",
                        }}
                    >
                        {" "}
                        · {r.approval}
                    </span>
                    {/* The reason a person said no is the most valuable line in
                        this panel, so it is never truncated away. */}
                    {r.approval === "rejected" && r.decision_note && (
                        <div style={{ color: "var(--st-redline)", paddingLeft: "12px" }}>
                            {r.decision_note}
                        </div>
                    )}
                </div>
            ))}
        </div>
    );
}

export default function PlanReview() {
    const session = useSessionStore((s) => s.session);
    const busy = useSessionStore((s) => s.busy);
    const { approve, reject, revise, build, accept } = useSessionStore.getState();
    const [note, setNote] = useState("");
    const [instruction, setInstruction] = useState("");

    if (!session) return null;
    const rev = session.revision;
    const state = session.state;

    return (
        <div style={{ padding: "12px", overflowY: "auto", fontSize: "13px" }}>
            <div style={{ ...label, color: STATE_TONE[state], marginBottom: "10px" }}>
                {STATE_LABEL[state]}
                {rev ? ` · revision ${rev.number}` : ""}
            </div>

            <Refusal />

            {/* Questions are the answer when the request did not say enough.
                Inventing the missing number is the failure the reasoning chain
                exists to prevent, so this state offers no way to build. */}
            {state === "questions" && (
                <div style={{ ...box, borderColor: "var(--st-caution)" }}>
                    <div style={label}>Before this can be designed</div>
                    {session.open_questions.map((q, i) => (
                        <div key={i} style={{ marginBottom: "4px" }}>
                            {q}
                        </div>
                    ))}
                </div>
            )}

            {rev && (
                <>
                    <div style={box}>
                        <div style={label}>Plan</div>
                        <div style={{ marginBottom: "6px" }}>{rev.part_class}</div>
                        {Object.entries(rev.design_plan ?? {}).map(([k, v]) => (
                            <div key={k} style={{ fontSize: "12px", marginBottom: "2px" }}>
                                <span style={{ color: "var(--st-pencil)" }}>{k}: </span>
                                {typeof v === "string" ? v : JSON.stringify(v)}
                            </div>
                        ))}
                        <div
                            style={{
                                fontSize: "10px",
                                color: "var(--st-pencil)",
                                marginTop: "8px",
                                fontFamily: "var(--st-mono, monospace)",
                            }}
                        >
                            {/* Shown because it is what the approval binds to. */}
                            {rev.blueprint_hash?.slice(0, 16)}
                        </div>
                    </div>

                    <Dimensions revision={rev} />
                    <Critique revision={rev} />
                    <Mechanical revision={rev} />
                    {rev.build_status === "built" && <Artifacts revision={rev} />}
                    {rev.build_error && (
                        <div style={{ ...box, borderColor: "var(--st-redline)" }}>
                            <div style={{ ...label, color: "var(--st-redline)" }}>
                                The build failed
                            </div>
                            <div style={{ fontSize: "12px" }}>{rev.build_error}</div>
                        </div>
                    )}
                </>
            )}

            <History />

            {state === "awaiting_approval" && rev && (
                <div style={box}>
                    <div style={label}>Your decision</div>
                    <textarea
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                        placeholder="A note — required to reject, optional to approve"
                        rows={2}
                        style={{
                            width: "100%",
                            background: "var(--st-void)",
                            color: "var(--st-ink)",
                            border: "1px solid var(--st-rule)",
                            fontFamily: "inherit",
                            fontSize: "12px",
                            padding: "6px",
                            marginBottom: "8px",
                        }}
                    />
                    <div style={{ display: "flex", gap: "6px" }}>
                        <Button
                            tone="primary"
                            disabled={!!busy}
                            onClick={() => {
                                void approve(note);
                                setNote("");
                            }}
                        >
                            {busy === "approving" ? "Approving…" : "Approve"}
                        </Button>
                        <Button
                            tone="danger"
                            // A rejection with no reason is a lost record: it is
                            // the only field here no synthetic pipeline can
                            // produce, so it is required rather than encouraged.
                            disabled={!!busy || !note.trim()}
                            onClick={() => {
                                void reject(note);
                                setNote("");
                            }}
                        >
                            {busy === "rejecting" ? "Rejecting…" : "Reject"}
                        </Button>
                    </div>
                </div>
            )}

            {state === "approved" && (
                <div style={{ display: "flex", gap: "6px", marginBottom: "10px" }}>
                    <Button tone="primary" disabled={!!busy} onClick={() => void build()}>
                        {busy === "building" ? "Starting…" : "Build it"}
                    </Button>
                </div>
            )}

            {state === "building" && (
                <div style={{ ...box, color: "var(--st-pencil)" }}>
                    FreeCAD is building this revision. It carries on if you close this —
                    the result is collected the next time you look.
                </div>
            )}

            {state === "built" && (
                <div style={{ display: "flex", gap: "6px", marginBottom: "10px" }}>
                    <Button tone="primary" disabled={!!busy} onClick={() => void accept()}>
                        {busy === "accepting" ? "Accepting…" : "Accept this part"}
                    </Button>
                </div>
            )}

            {(state === "awaiting_approval" ||
                state === "built" ||
                state === "needs_revision" ||
                state === "approved" ||
                state === "failed") && (
                <div style={box}>
                    <div style={label}>Ask for a change</div>
                    <textarea
                        value={instruction}
                        onChange={(e) => setInstruction(e.target.value)}
                        placeholder="Make it 80mm wide and add a 6mm chamfer"
                        rows={2}
                        style={{
                            width: "100%",
                            background: "var(--st-void)",
                            color: "var(--st-ink)",
                            border: "1px solid var(--st-rule)",
                            fontFamily: "inherit",
                            fontSize: "12px",
                            padding: "6px",
                            marginBottom: "8px",
                        }}
                    />
                    <Button
                        disabled={!!busy || !instruction.trim()}
                        onClick={() => {
                            void revise(instruction);
                            setInstruction("");
                        }}
                    >
                        {busy === "revising" ? "Revising…" : "Revise"}
                    </Button>
                </div>
            )}
        </div>
    );
}
