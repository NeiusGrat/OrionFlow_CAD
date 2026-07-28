import { CheckCircle2, AlertTriangle, HelpCircle } from "lucide-react";
import type { VerificationReport } from "../../services/agentApi";

/**
 * The verdict panel.
 *
 * Two rules keep this honest, and they are the whole reason the component
 * exists. A check is rendered only if the backend actually ran it, so an absent
 * row means "not tested" and never "fine". And a refusal leads — the failing
 * guard and its measured value come first, because a user who cannot see WHY a
 * part was rejected will assume the tool is broken and ship the part anyway.
 */

const VERDICT = {
    verified: {
        color: "var(--studio-ok)",
        text: "Verified",
        sub: "every check that ran, passed",
        Icon: CheckCircle2,
    },
    refused: {
        color: "var(--studio-err)",
        text: "Refused",
        sub: "this geometry is not correct as drawn",
        Icon: AlertTriangle,
    },
    unproven: {
        color: "var(--studio-warn)",
        text: "Unproven",
        sub: "nothing failed, but nothing was proved",
        Icon: HelpCircle,
    },
} as const;

export default function VerificationCard({
    report,
    compact = false,
}: {
    report?: VerificationReport | null;
    compact?: boolean;
}) {
    if (!report) return null;

    const v = VERDICT[report.verdict] ?? VERDICT.unproven;
    const m = report.measured ?? {};
    const checks = report.checks ?? [];
    const failed = report.failed ?? [];
    const { Icon } = v;

    return (
        <div
            style={{
                background: "var(--studio-panel-2)",
                border: `1px solid ${v.color}`,
                borderRadius: "8px",
                padding: "10px 11px",
                display: "flex",
                flexDirection: "column",
                gap: "7px",
                fontSize: "12px",
            }}
        >
            <div style={{ display: "flex", alignItems: "center", gap: "7px" }}>
                <Icon size={15} color={v.color} />
                <span
                    style={{
                        fontWeight: 700,
                        fontSize: "13px",
                        letterSpacing: "0.03em",
                        color: v.color,
                    }}
                >
                    {v.text}
                </span>
                <span
                    style={{
                        marginLeft: "auto",
                        fontSize: "10.5px",
                        color: "var(--studio-text-faint)",
                    }}
                >
                    {checks.length} check{checks.length === 1 ? "" : "s"}
                </span>
            </div>
            <div
                style={{
                    color: "var(--studio-text-faint)",
                    fontSize: "11px",
                    marginTop: "-4px",
                }}
            >
                {v.sub}
            </div>

            {/* A refusal leads. */}
            {failed.length > 0 && (
                <div
                    style={{
                        borderLeft: `2px solid ${VERDICT.refused.color}`,
                        paddingLeft: "8px",
                        display: "flex",
                        flexDirection: "column",
                        gap: "4px",
                    }}
                >
                    {failed.map((c) => (
                        <div key={c.id}>
                            <div
                                style={{
                                    color: VERDICT.refused.color,
                                    fontWeight: 600,
                                    fontSize: "11px",
                                }}
                            >
                                {c.label} failed
                            </div>
                            <div style={{ color: "var(--studio-text)", fontSize: "11px" }}>
                                {c.detail}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {!compact && checks.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: "3px" }}>
                    {checks.map((c) => (
                        <div
                            key={c.id}
                            style={{
                                display: "flex",
                                alignItems: "flex-start",
                                gap: "6px",
                                fontSize: "11px",
                            }}
                        >
                            <span
                                style={{
                                    color:
                                        c.status === "pass"
                                            ? "var(--studio-ok)"
                                            : VERDICT.refused.color,
                                    lineHeight: "15px",
                                }}
                            >
                                {c.status === "pass" ? "✓" : "✕"}
                            </span>
                            <span style={{ color: "var(--studio-text)" }}>{c.label}</span>
                            <span
                                style={{
                                    color: "var(--studio-text-faint)",
                                    marginLeft: "auto",
                                    textAlign: "right",
                                    maxWidth: "60%",
                                    fontFamily: "var(--font-mono)",
                                    fontSize: "10px",
                                }}
                            >
                                {c.detail}
                            </span>
                        </div>
                    ))}
                </div>
            )}

            {/* Observations, explicitly not claims of correctness. */}
            {(m.volume_cm3 != null || m.bbox_mm) && (
                <div
                    style={{
                        color: "var(--studio-text-faint)",
                        fontSize: "10.5px",
                        borderTop: "1px solid var(--studio-border)",
                        paddingTop: "6px",
                        fontFamily: "var(--font-mono)",
                    }}
                >
                    measured&nbsp;
                    {m.volume_cm3 != null && <>{m.volume_cm3} cm³ · </>}
                    {m.mass_g != null && <>{m.mass_g} g · </>}
                    {m.bbox_mm?.map((x) => Math.round(x)).join("×")} mm
                </div>
            )}
        </div>
    );
}
