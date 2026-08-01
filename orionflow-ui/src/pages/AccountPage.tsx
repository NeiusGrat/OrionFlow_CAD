import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowLeft, Check, Loader2 } from "lucide-react";
import OrionFlowLogo, { OrionFlowWordmark } from "../components/OrionFlowLogo";
import { useAuthStore } from "../store/authStore";
import { useUIStore } from "../store/uiStore";
import { useLibraryStore } from "../store/libraryStore";
import {
    fetchSubscription,
    fetchUsage,
    type Subscription,
    type UsageLimit,
} from "../services/billingApi";

/**
 * Account, settings and plan.
 *
 * One page with three sections rather than three routes: they are all short,
 * and a user who came here to check their remaining generations should not
 * have to navigate to find out what plan those generations are on.
 *
 * Every number is read from the server. Where something is not wired up yet —
 * changing plan in-app, for instance — it says so and gives the route that
 * works, instead of showing a button that does nothing.
 */

const TABS = [
    { id: "profile", label: "Profile" },
    { id: "settings", label: "Settings" },
    { id: "billing", label: "Billing" },
] as const;

type Tab = (typeof TABS)[number]["id"];

function Row({ label, value }: { label: string; value: React.ReactNode }) {
    return (
        <div
            style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                gap: "16px",
                padding: "10px 0",
                borderBottom: "1px solid var(--st-rule-soft)",
            }}
        >
            <span style={{ fontSize: "12.5px", color: "var(--st-graphite)" }}>{label}</span>
            <span
                className="of-num"
                style={{ fontSize: "12.5px", color: "var(--st-ink)", textAlign: "right", minWidth: 0 }}
            >
                {value}
            </span>
        </div>
    );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
    return (
        <section
            style={{
                background: "var(--st-sheet)",
                border: "1px solid var(--st-rule)",
                borderRadius: "10px",
                padding: "16px 18px 8px",
                marginBottom: "16px",
            }}
        >
            <h2 className="of-label" style={{ marginBottom: "8px" }}>
                {title}
            </h2>
            {children}
        </section>
    );
}

export default function AccountPage() {
    const [params, setParams] = useSearchParams();
    const tab = (params.get("tab") as Tab) || "profile";

    const user = useAuthStore((s) => s.user);
    const theme = useUIStore((s) => s.theme);
    const setTheme = useUIStore((s) => s.setTheme);
    const startTour = useUIStore((s) => s.startTour);
    const designs = useLibraryStore((s) => s.designs);
    const hydrate = useLibraryStore((s) => s.hydrate);

    const [usage, setUsage] = useState<UsageLimit | null>(null);
    const [sub, setSub] = useState<Subscription | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        hydrate();
        Promise.all([fetchUsage(), fetchSubscription()]).then(([u, s]) => {
            setUsage(u);
            setSub(s);
            setLoading(false);
        });
    }, [hydrate]);

    const limit = usage?.limit ?? 0;
    const used = usage?.used ?? 0;
    const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;

    return (
        <div
            className="studio-scroll"
            style={{
                width: "100%",
                height: "100vh",
                overflowY: "auto",
                background: "var(--st-void)",
                color: "var(--st-ink)",
            }}
        >
            <div
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                    height: "40px",
                    padding: "0 14px",
                    background: "var(--st-sheet)",
                    borderBottom: "1px solid var(--st-rule)",
                }}
            >
                <OrionFlowLogo size={19} />
                <OrionFlowWordmark size={12.5} />
                <Link
                    to="/"
                    style={{
                        marginLeft: "auto",
                        display: "flex",
                        alignItems: "center",
                        gap: "6px",
                        fontSize: "12px",
                        color: "var(--st-graphite)",
                        textDecoration: "none",
                    }}
                >
                    <ArrowLeft size={13} />
                    Back to the studio
                </Link>
            </div>

            <div style={{ maxWidth: "640px", margin: "0 auto", padding: "28px 20px 60px" }}>
                <h1 className="of-report-head" style={{ fontSize: "28px", marginBottom: "3px" }}>
                    {user?.name || "Your account"}
                </h1>
                <p style={{ fontSize: "13px", color: "var(--st-pencil)", marginBottom: "20px" }}>
                    {user?.email}
                </p>

                <div style={{ display: "flex", gap: "3px", marginBottom: "18px", borderBottom: "1px solid var(--st-rule)" }}>
                    {TABS.map((t) => (
                        <button
                            key={t.id}
                            onClick={() => setParams(t.id === "profile" ? {} : { tab: t.id })}
                            style={{
                                padding: "8px 14px",
                                background: "transparent",
                                border: "none",
                                borderBottom: `2px solid ${tab === t.id ? "var(--st-blue)" : "transparent"}`,
                                color: tab === t.id ? "var(--st-ink)" : "var(--st-pencil)",
                                fontSize: "12.5px",
                                fontWeight: 600,
                                cursor: "pointer",
                                marginBottom: "-1px",
                            }}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>

                {loading && (
                    <div style={{ display: "flex", gap: "8px", alignItems: "center", color: "var(--st-pencil)", fontSize: "12.5px" }}>
                        <Loader2 size={13} className="of-spin" />
                        Loading your account…
                    </div>
                )}

                {!loading && tab === "profile" && (
                    <>
                        <Card title="Account">
                            <Row label="Name" value={user?.name || "—"} />
                            <Row label="Email" value={user?.email || "—"} />
                            <Row label="Plan" value={sub?.plan.display_name || "Free"} />
                        </Card>
                        <Card title="Work">
                            <Row label="Saved projects" value={designs.length} />
                            <Row
                                label="Generations this month"
                                value={limit > 0 ? `${used} of ${limit}` : String(used)}
                            />
                        </Card>
                    </>
                )}

                {!loading && tab === "settings" && (
                    <>
                        <Card title="Appearance">
                            <div style={{ display: "flex", gap: "9px", padding: "4px 0 14px" }}>
                                {(["dark", "light"] as const).map((t) => (
                                    <button
                                        key={t}
                                        onClick={() => setTheme(t)}
                                        style={{
                                            flex: 1,
                                            padding: "12px",
                                            borderRadius: "8px",
                                            border: `1px solid ${theme === t ? "var(--st-blue)" : "var(--st-rule)"}`,
                                            background: theme === t ? "var(--st-blue-wash)" : "var(--st-raise)",
                                            color: "var(--st-ink)",
                                            fontSize: "12.5px",
                                            fontWeight: 600,
                                            cursor: "pointer",
                                            display: "flex",
                                            alignItems: "center",
                                            justifyContent: "center",
                                            gap: "7px",
                                        }}
                                    >
                                        {theme === t && <Check size={13} style={{ color: "var(--st-blue)" }} />}
                                        {t === "dark" ? "Dark — drawing sheet" : "Light — vellum"}
                                    </button>
                                ))}
                            </div>
                        </Card>
                        <Card title="Help">
                            <div style={{ padding: "4px 0 14px" }}>
                                <button
                                    onClick={startTour}
                                    style={{
                                        padding: "7px 14px",
                                        borderRadius: "7px",
                                        border: "1px solid var(--st-rule)",
                                        background: "var(--st-raise)",
                                        color: "var(--st-ink)",
                                        fontSize: "12.5px",
                                        fontWeight: 600,
                                        cursor: "pointer",
                                    }}
                                >
                                    Replay the studio tour
                                </button>
                            </div>
                        </Card>
                    </>
                )}

                {!loading && tab === "billing" && (
                    <>
                        <Card title="Plan">
                            <Row label="Current plan" value={sub?.plan.display_name || "Free"} />
                            <Row label="Status" value={sub?.status || "active"} />
                            {sub && (
                                <Row
                                    label="Renews"
                                    value={new Date(sub.current_period_end).toLocaleDateString()}
                                />
                            )}
                        </Card>
                        <Card title="Usage this month">
                            <div style={{ padding: "6px 0 16px" }}>
                                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "7px" }}>
                                    <span style={{ fontSize: "12.5px", color: "var(--st-graphite)" }}>
                                        Generations
                                    </span>
                                    <span className="of-num" style={{ fontSize: "12.5px", color: "var(--st-ink)" }}>
                                        {used} / {limit || "—"} · {pct}%
                                    </span>
                                </div>
                                <div style={{ height: "5px", background: "var(--st-rule)", borderRadius: "3px", overflow: "hidden" }}>
                                    <div
                                        style={{
                                            width: `${pct}%`,
                                            height: "100%",
                                            background: pct >= 90 ? "var(--st-redline)" : "var(--st-verify)",
                                        }}
                                    />
                                </div>
                                {usage && !usage.allowed && usage.message && (
                                    <p style={{ marginTop: "10px", fontSize: "12px", color: "var(--st-redline)", lineHeight: 1.5 }}>
                                        {usage.message}
                                    </p>
                                )}
                            </div>
                        </Card>
                        <p style={{ fontSize: "12px", color: "var(--st-pencil)", lineHeight: 1.6 }}>
                            Changing plan is not available in the studio yet. Email{" "}
                            <a href="mailto:hello@orionflow.in" style={{ color: "var(--st-blue)" }}>
                                hello@orionflow.in
                            </a>{" "}
                            and we will move you over.
                        </p>
                    </>
                )}
            </div>
        </div>
    );
}
