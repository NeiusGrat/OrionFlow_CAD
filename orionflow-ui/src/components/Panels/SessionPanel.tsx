/**
 * The reviewed route: prompt, plan, approval, build.
 *
 * The chat panel beside this designs and builds in one go, which is the right
 * shape when you already know what you want. This is the other one — the design
 * stops at a plan and waits to be read, because the server will not build
 * anything nobody approved.
 *
 * The timeline at the bottom is the session's own event log, not a transcript
 * assembled here. That matters: a build outlives the request that started it, so
 * the only honest account of what happened is the one the server appended as it
 * happened, replayed from a cursor.
 */

import { useEffect, useState } from "react";
import PlanReview from "./PlanReview";
import { useSessionStore } from "../../store/sessionStore";

const EVENT_LABEL: Record<string, string> = {
    session_created: "Design started",
    questions_required: "More information needed",
    plan_created: "Plan proposed",
    approval_required: "Waiting for approval",
    approval_received: "Approved",
    rejected: "Rejected",
    revision_created: "Revision created",
    build_started: "Build started",
    build_completed: "Build finished",
    validation_completed: "Checks run",
    final_review_ready: "Ready for review",
    completed: "Accepted",
    failed: "Failed",
    cancelled: "Cancelled",
};

function Timeline() {
    const events = useSessionStore((s) => s.events);
    if (!events.length) return null;
    return (
        <div
            style={{
                borderTop: "1px solid var(--st-rule)",
                padding: "10px 12px",
                maxHeight: "180px",
                overflowY: "auto",
            }}
        >
            <div
                style={{
                    fontSize: "10px",
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    color: "var(--st-pencil)",
                    marginBottom: "6px",
                }}
            >
                Timeline
            </div>
            {events.map((e) => (
                <div
                    key={e.seq}
                    style={{
                        fontSize: "11px",
                        display: "flex",
                        gap: "8px",
                        marginBottom: "3px",
                    }}
                >
                    <span
                        style={{
                            color: "var(--st-pencil)",
                            fontFamily: "var(--st-mono, monospace)",
                        }}
                    >
                        {e.seq}
                    </span>
                    <span>{EVENT_LABEL[e.type] ?? e.type}</span>
                    {e.data?.error && (
                        <span style={{ color: "var(--st-redline)" }}>{e.data.error}</span>
                    )}
                </div>
            ))}
        </div>
    );
}

export default function SessionPanel() {
    const session = useSessionStore((s) => s.session);
    const busy = useSessionStore((s) => s.busy);
    const error = useSessionStore((s) => s.error);
    const { start, close } = useSessionStore.getState();
    const [prompt, setPrompt] = useState("");

    // A session left open in another tab, or from before a refresh, is not
    // resumed automatically: the id would have to be persisted and a stale one
    // reads as a 404 on load. Starting fresh is the honest default; the list
    // route exists for picking an earlier one up deliberately.
    useEffect(() => () => close(), [close]);

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
            {!session && (
                <div style={{ padding: "12px" }}>
                    <div
                        style={{
                            fontSize: "10px",
                            letterSpacing: "0.08em",
                            textTransform: "uppercase",
                            color: "var(--st-pencil)",
                            marginBottom: "8px",
                        }}
                    >
                        Describe the part
                    </div>
                    <textarea
                        value={prompt}
                        onChange={(e) => setPrompt(e.target.value)}
                        placeholder="A 120 × 80 × 10 mm mounting plate with four M6 clearance holes"
                        rows={4}
                        style={{
                            width: "100%",
                            background: "var(--st-void)",
                            color: "var(--st-ink)",
                            border: "1px solid var(--st-rule)",
                            fontFamily: "inherit",
                            fontSize: "12px",
                            padding: "8px",
                            marginBottom: "8px",
                        }}
                    />
                    <button
                        disabled={!!busy || !prompt.trim()}
                        onClick={() => void start(prompt)}
                        style={{
                            padding: "6px 12px",
                            fontSize: "12px",
                            fontFamily: "inherit",
                            background: "var(--st-blue)",
                            color: "var(--st-sheet)",
                            border: "1px solid var(--st-blue)",
                            cursor: busy || !prompt.trim() ? "default" : "pointer",
                            opacity: busy || !prompt.trim() ? 0.45 : 1,
                        }}
                    >
                        {busy === "creating" ? "Working out the plan…" : "Plan it"}
                    </button>
                    {error && (
                        <div
                            style={{
                                marginTop: "10px",
                                fontSize: "12px",
                                color: "var(--st-redline)",
                            }}
                        >
                            {error.message}
                        </div>
                    )}
                    <p
                        style={{
                            marginTop: "14px",
                            fontSize: "11px",
                            color: "var(--st-pencil)",
                            lineHeight: 1.5,
                        }}
                    >
                        Nothing is built until you approve the plan. You can reject it, ask
                        for changes, or approve and build — and every revision is kept.
                    </p>
                </div>
            )}

            {session && (
                <>
                    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                        <PlanReview />
                    </div>
                    <Timeline />
                    <div style={{ padding: "8px 12px", borderTop: "1px solid var(--st-rule)" }}>
                        <button
                            onClick={close}
                            style={{
                                fontSize: "11px",
                                background: "transparent",
                                color: "var(--st-pencil)",
                                border: "1px solid var(--st-rule)",
                                padding: "4px 10px",
                                fontFamily: "inherit",
                                cursor: "pointer",
                            }}
                        >
                            Start another
                        </button>
                    </div>
                </>
            )}
        </div>
    );
}
