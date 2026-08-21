/**
 * The live design session, rendered inside the conversation.
 *
 * This used to be a tab with its own prompt box beside the assistant, which
 * made "design it carefully" a different product from "design it". It is not a
 * different product — it is the same request routed through the approval gate,
 * so the agent starts the session now and this shows what came back.
 *
 * The prompt form that used to be here is gone with the tab: there is one place
 * to describe a part, and it is the composer. Everything else is kept, because
 * it is what the reviewed route is *for* — the plan, the checks that already
 * ran, the approve/reject/revise controls, and the event log.
 *
 * The timeline is the session's own log replayed from a cursor, not a
 * transcript assembled here. That matters: a build outlives the request that
 * started it, so the only honest account of what happened is the one the server
 * appended as it happened.
 */

import { useSessionStore } from "../../store/sessionStore";
import PlanReview from "./PlanReview";

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
            className="studio-scroll"
            style={{
                borderTop: "1px solid var(--st-rule)",
                padding: "10px 12px",
                maxHeight: "168px",
                overflowY: "auto",
            }}
        >
            <div className="of-label" style={{ marginBottom: "7px" }}>
                Timeline
            </div>
            {events.map((e) => (
                <div
                    key={e.seq}
                    style={{
                        fontSize: "11px",
                        display: "flex",
                        gap: "9px",
                        marginBottom: "4px",
                        color: "var(--st-graphite)",
                    }}
                >
                    <span className="of-bracket">[{String(e.seq).padStart(2, "0")}]</span>
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
    const close = useSessionStore((s) => s.close);

    if (!session) return null;

    return (
        <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
            <PlanReview />
            <Timeline />
            <div style={{ padding: "9px 12px", borderTop: "1px solid var(--st-rule)" }}>
                <button onClick={close} className="of-btn of-btn--quiet" style={{ fontSize: "11px" }}>
                    Close this plan
                </button>
            </div>
        </div>
    );
}
