import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
    CreditCard,
    LogOut,
    MessageSquare,
    Moon,
    Settings,
    Sun,
    User,
} from "lucide-react";
import { useAuthStore } from "../../store/authStore";
import { useStudioStore } from "../../store/studioStore";
import { useUIStore } from "../../store/uiStore";
import { fetchSubscription, fetchUsage, type Subscription, type UsageLimit } from "../../services/billingApi";

/**
 * Who is signed in, what they are on, and how much of it is left.
 *
 * Both meters are real. **Monthly** comes from the same endpoint the
 * generation gate consults, so what this shows and what actually refuses a
 * build can never disagree. **Session** counts the parts actually built in
 * this tab, against the same allowance — it is the number that moves while you
 * work, and it is measured rather than inferred from a baseline that would be
 * wrong for anyone who opened the menu late.
 *
 * When the server cannot say what plan someone is on, the menu says so instead
 * of assuming Free: telling a paying customer they are on the free tier is a
 * support ticket, and a dash is not.
 */

function Meter({ label, used, limit, tone }: { label: string; used: number; limit: number; tone: string }) {
    const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <span className="of-label" style={{ fontSize: "9px" }}>{label}</span>
                <span className="of-num" style={{ fontSize: "10.5px", color: "var(--st-graphite)" }}>
                    {used} / {limit || "—"}
                    <span style={{ color: "var(--st-pencil)" }}>{limit > 0 ? `  ${pct}%` : ""}</span>
                </span>
            </div>
            <div style={{ height: "3px", background: "var(--st-rule)", borderRadius: "2px", overflow: "hidden" }}>
                <div
                    style={{
                        width: `${pct}%`,
                        height: "100%",
                        background: pct >= 90 ? "var(--st-redline)" : tone,
                        transition: "width 0.25s var(--ease-out-quad)",
                    }}
                />
            </div>
        </div>
    );
}

function Item({
    icon,
    label,
    detail,
    onClick,
    tone,
}: {
    icon: React.ReactNode;
    label: string;
    detail?: string;
    onClick: () => void;
    tone?: string;
}) {
    return (
        <button
            onClick={onClick}
            className="of-row"
            style={{
                display: "flex",
                alignItems: "center",
                gap: "9px",
                width: "100%",
                padding: "7px 9px",
                borderRadius: "5px",
                border: "none",
                background: "transparent",
                color: tone || "var(--st-graphite)",
                fontSize: "12px",
                fontWeight: 500,
                cursor: "pointer",
                textAlign: "left",
            }}
        >
            {icon}
            <span style={{ flex: 1 }}>{label}</span>
            {detail && (
                <span className="of-num" style={{ fontSize: "10px", color: "var(--st-pencil)" }}>
                    {detail}
                </span>
            )}
        </button>
    );
}

export default function AccountMenu() {
    const user = useAuthStore((s) => s.user);
    const logout = useAuthStore((s) => s.logout);
    const theme = useUIStore((s) => s.theme);
    const toggleTheme = useUIStore((s) => s.toggleTheme);
    const startTour = useUIStore((s) => s.startTour);
    const navigate = useNavigate();

    const [open, setOpen] = useState(false);
    const [usage, setUsage] = useState<UsageLimit | null>(null);
    const [sub, setSub] = useState<Subscription | null>(null);
    const [loaded, setLoaded] = useState(false);
    const ref = useRef<HTMLDivElement>(null);

    // Every entry in the studio's history is one part that was really built,
    // which is exactly what a generation is charged for.
    const builds = useStudioStore((s) => s.history.length);

    useEffect(() => {
        const close = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
        };
        if (open) document.addEventListener("mousedown", close);
        return () => document.removeEventListener("mousedown", close);
    }, [open]);

    // Refreshed when the menu opens and after each build, so the meter is not
    // stale at the moment somebody looks at it to find out why a build refused.
    useEffect(() => {
        if (!open) return;
        let live = true;
        Promise.all([fetchUsage(), fetchSubscription()]).then(([u, s]) => {
            if (!live) return;
            setUsage(u);
            setSub(s);
            setLoaded(true);
        });
        return () => {
            live = false;
        };
    }, [open, builds]);

    const initial = (user?.name || user?.email || "?").trim().charAt(0).toUpperCase();
    const planName = sub?.plan.display_name || (loaded ? "Free plan" : "—");
    const limit = usage?.limit ?? 0;
    const used = usage?.used ?? 0;

    return (
        <div ref={ref} style={{ position: "relative" }}>
            <button
                onClick={() => setOpen(!open)}
                title={user?.email || "Account"}
                aria-haspopup="menu"
                aria-expanded={open}
                style={{
                    width: "26px",
                    height: "26px",
                    borderRadius: "50%",
                    border: `1px solid ${open ? "var(--st-blue)" : "var(--st-rule)"}`,
                    background: open ? "var(--st-blue-wash)" : "var(--st-raise)",
                    color: "var(--st-ink)",
                    fontSize: "11px",
                    fontWeight: 700,
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                }}
            >
                {initial}
            </button>

            {open && (
                <div
                    role="menu"
                    className="of-enter"
                    style={{
                        position: "absolute",
                        top: "34px",
                        right: 0,
                        width: "252px",
                        background: "var(--st-sheet)",
                        border: "1px solid var(--st-rule)",
                        borderRadius: "9px",
                        padding: "6px",
                        zIndex: 400,
                        boxShadow: "var(--st-shadow)",
                    }}
                >
                    <div style={{ display: "flex", alignItems: "center", gap: "9px", padding: "6px 8px 9px" }}>
                        <div
                            style={{
                                width: "30px",
                                height: "30px",
                                borderRadius: "50%",
                                background: "var(--st-blue-wash)",
                                border: "1px solid var(--st-blue-edge)",
                                color: "var(--st-blue)",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                fontSize: "12px",
                                fontWeight: 700,
                                flexShrink: 0,
                            }}
                        >
                            {initial}
                        </div>
                        <div style={{ minWidth: 0 }}>
                            <div style={{ fontSize: "12.5px", fontWeight: 600, color: "var(--st-ink)", overflow: "hidden", textOverflow: "ellipsis" }}>
                                {user?.name || user?.email || "Signed in"}
                            </div>
                            <div style={{ fontSize: "10.5px", color: "var(--st-pencil)" }}>{planName}</div>
                        </div>
                    </div>

                    <div
                        style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: "9px",
                            padding: "9px 8px",
                            margin: "0 0 5px",
                            borderTop: "1px solid var(--st-rule-soft)",
                            borderBottom: "1px solid var(--st-rule-soft)",
                        }}
                    >
                        <Meter label="Session" used={builds} limit={limit} tone="var(--st-blue)" />
                        <Meter label="Monthly" used={used} limit={limit} tone="var(--st-verify)" />
                        {usage && !usage.allowed && usage.message && (
                            <div style={{ fontSize: "10.5px", color: "var(--st-redline)", lineHeight: 1.4 }}>
                                {usage.message}
                            </div>
                        )}
                    </div>

                    <Item
                        icon={<User size={13} />}
                        label="Profile"
                        detail={user?.email ? user.email.split("@")[0] : undefined}
                        onClick={() => {
                            setOpen(false);
                            navigate("/account");
                        }}
                    />
                    <Item
                        icon={<Settings size={13} />}
                        label="Settings"
                        onClick={() => {
                            setOpen(false);
                            navigate("/account?tab=settings");
                        }}
                    />
                    <Item
                        icon={<CreditCard size={13} />}
                        label="Billing"
                        detail={sub ? sub.status : "free"}
                        onClick={() => {
                            setOpen(false);
                            navigate("/account?tab=billing");
                        }}
                    />
                    <Item
                        icon={<MessageSquare size={13} />}
                        label="Feedback"
                        onClick={() => {
                            setOpen(false);
                            window.open(
                                "mailto:hello@orionflow.in?subject=" +
                                    encodeURIComponent("OrionFlow Studio feedback"),
                                "_blank",
                            );
                        }}
                    />
                    <Item
                        icon={theme === "dark" ? <Sun size={13} /> : <Moon size={13} />}
                        label={theme === "dark" ? "Light mode" : "Dark mode"}
                        onClick={toggleTheme}
                    />
                    <Item
                        icon={<MessageSquare size={13} />}
                        label="Replay the tour"
                        onClick={() => {
                            setOpen(false);
                            startTour();
                        }}
                    />

                    <div style={{ borderTop: "1px solid var(--st-rule-soft)", marginTop: "5px", paddingTop: "5px" }}>
                        <Item
                            icon={<LogOut size={13} />}
                            label="Sign out"
                            tone="var(--st-redline)"
                            onClick={() => {
                                logout();
                                navigate("/auth");
                            }}
                        />
                    </div>
                </div>
            )}
        </div>
    );
}
