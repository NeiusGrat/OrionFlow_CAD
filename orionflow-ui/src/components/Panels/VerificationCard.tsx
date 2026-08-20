import { CheckCircle2, AlertTriangle, HelpCircle, FileQuestion } from "lucide-react";
import type { ProvenanceEntry, VerificationReport } from "../../services/agentApi";

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
    // The verdict that separates "the geometry matches its numbers" from "the
    // numbers are right". Both were VERIFIED before, and only the first was
    // ever true of a part whose dimensions nobody supplied.
    unsourced: {
        color: "var(--studio-warn)",
        text: "Unsourced",
        sub: "the geometry is proved; some of its dimensions are not",
        Icon: FileQuestion,
    },
} as const;

/** Which colour a single check row gets. */
const STATUS_COLOR: Record<string, string> = {
    pass: "var(--studio-ok)",
    warn: "var(--studio-warn)",
    fail: "var(--studio-err)",
};

const STATUS_MARK: Record<string, string> = { pass: "✓", warn: "!", fail: "✕" };

/** How each provenance source reads to an engineer. */
const SOURCE_LABEL: Record<string, string> = {
    stated: "you gave it",
    standard: "from a standard",
    derived: "calculated",
    default: "a documented default",
    unsourced: "chosen, not derived",
};

/** The assumption ledger.
 *
 *  Unsourced rows first and in full; everything else collapses to a count.
 *  A reader looking for what to double-check should not have to scan past a
 *  dozen rows of "you gave it" to find the one that says nobody did.
 */
function Ledger({ provenance }: { provenance: Record<string, ProvenanceEntry> }) {
    const entries = Object.entries(provenance);
    if (!entries.length) return null;
    const missing = entries.filter(([, e]) => e.source === "unsourced");
    const counts = new Map<string, number>();
    for (const [, e] of entries) {
        if (e.source !== "unsourced") counts.set(e.source, (counts.get(e.source) ?? 0) + 1);
    }

    return (
        <div
            style={{
                borderTop: "1px solid var(--studio-border)",
                paddingTop: "6px",
                display: "flex",
                flexDirection: "column",
                gap: "3px",
                fontSize: "10.5px",
            }}
        >
            <div style={{ color: "var(--studio-text-faint)" }}>
                where the numbers came from
            </div>
            {missing.map(([name]) => (
                <div key={name} style={{ display: "flex", gap: "6px" }}>
                    <span style={{ color: "var(--studio-warn)", lineHeight: "14px" }}>!</span>
                    <span style={{ color: "var(--studio-text)", fontFamily: "var(--font-mono)" }}>
                        {name}
                    </span>
                    <span style={{ color: "var(--studio-warn)", marginLeft: "auto" }}>
                        {SOURCE_LABEL.unsourced}
                    </span>
                </div>
            ))}
            {counts.size > 0 && (
                <div style={{ color: "var(--studio-text-faint)", paddingLeft: "17px" }}>
                    {[...counts.entries()]
                        .sort((a, b) => b[1] - a[1])
                        .map(([source, n]) => `${n} ${SOURCE_LABEL[source] ?? source}`)
                        .join(" · ")}
                </div>
            )}
        </div>
    );
}

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
                                    color: STATUS_COLOR[c.status] ?? VERDICT.refused.color,
                                    lineHeight: "15px",
                                }}
                            >
                                {STATUS_MARK[c.status] ?? "✕"}
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

            {!compact && report.provenance && <Ledger provenance={report.provenance} />}

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
