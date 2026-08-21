import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Loader2 } from "lucide-react";
import OrionFlowLogo, { OrionFlowWordmark } from "../components/OrionFlowLogo";
import { joinEarlyAccess } from "../services/waitlistApi";
import { useAuthStore } from "../store/authStore";

/**
 * "Try OrionFlow" — the one step between the landing page and the studio.
 *
 * Three fields, because the point of early access is knowing who is testing the
 * product and being able to follow up, and an email alone answers neither. It
 * sits *before* sign-up rather than after for one reason: someone who abandons
 * at the password field has still told us who they are, and that is the lead we
 * would otherwise have lost entirely.
 *
 * Friction is kept to what it costs. Name and company carry through to the
 * sign-up form, so nothing is typed twice — the next screen only asks for a
 * password. And a failure to record the signup does **not** block the journey:
 * someone who wants to try the software must never be held at a form because
 * our lead capture had a bad minute. The error is surfaced, the door stays open.
 */

const FIELDS = [
    {
        id: "name" as const,
        label: "Name",
        placeholder: "Ada Lovelace",
        type: "text",
        autoComplete: "name",
    },
    {
        id: "company" as const,
        label: "Company",
        placeholder: "Where you build things",
        type: "text",
        autoComplete: "organization",
    },
    {
        id: "email" as const,
        label: "Work email",
        placeholder: "you@company.com",
        type: "email",
        autoComplete: "email",
    },
];

export default function StartPage() {
    const navigate = useNavigate();
    const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

    const [form, setForm] = useState({ name: "", company: "", email: "" });
    const [website, setWebsite] = useState(""); // honeypot
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [touched, setTouched] = useState(false);

    // Already signed in — the intake is for people who have not started yet,
    // and making a returning user fill it in again would be asking for
    // something we already know.
    useEffect(() => {
        if (isAuthenticated) navigate("/", { replace: true });
    }, [isAuthenticated, navigate]);

    const valid =
        form.name.trim().length > 1 &&
        form.company.trim().length > 0 &&
        /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email.trim());

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        setTouched(true);
        if (!valid || busy) return;

        setBusy(true);
        setError("");
        try {
            await joinEarlyAccess({ ...form, website, source: "try" });
        } catch (err: any) {
            // Recorded as a warning to the user, not a wall. They came here to
            // use the product.
            setError(`${err?.message ?? "Something went wrong."} Continuing anyway.`);
        } finally {
            setBusy(false);
        }

        const q = new URLSearchParams({
            intent: "signup",
            name: form.name.trim(),
            email: form.email.trim().toLowerCase(),
        });
        navigate(`/auth?${q.toString()}`, { replace: true });
    };

    return (
        <div
            style={{
                minHeight: "100vh",
                width: "100%",
                background: "var(--st-void)",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                padding: "40px 24px",
                position: "relative",
                overflow: "hidden",
            }}
        >
            {/* One soft pool of light, the same device the viewport uses. */}
            <div className="of-stage-light" />

            <div style={{ width: "100%", maxWidth: "392px", position: "relative" }}>
                <div
                    style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "9px",
                        justifyContent: "center",
                        marginBottom: "34px",
                    }}
                >
                    <OrionFlowLogo size={21} />
                    <OrionFlowWordmark size={14} />
                </div>

                <div className="of-label" style={{ marginBottom: "10px" }}>
                    Early access
                </div>
                <h1
                    className="of-report-head"
                    style={{ fontSize: "27px", marginBottom: "10px", color: "var(--st-ink)" }}
                >
                    Put a part into words.
                </h1>
                <p
                    style={{
                        fontSize: "13px",
                        lineHeight: 1.7,
                        color: "var(--st-graphite)",
                        marginBottom: "28px",
                    }}
                >
                    Tell us who you are and the studio opens next. We use this to
                    understand who is testing OrionFlow and to follow up — nothing
                    else, and nothing public.
                </p>

                <form onSubmit={submit} noValidate>
                    {FIELDS.map((f, i) => {
                        const value = form[f.id];
                        const bad = touched && !value.trim();
                        return (
                            <div key={f.id} style={{ marginBottom: "14px" }}>
                                <label
                                    htmlFor={f.id}
                                    className="of-label"
                                    style={{
                                        display: "flex",
                                        alignItems: "center",
                                        gap: "8px",
                                        marginBottom: "6px",
                                    }}
                                >
                                    <span className="of-bracket">
                                        [{String(i + 1).padStart(2, "0")}]
                                    </span>
                                    {f.label}
                                </label>
                                <input
                                    id={f.id}
                                    type={f.type}
                                    value={value}
                                    autoComplete={f.autoComplete}
                                    placeholder={f.placeholder}
                                    maxLength={f.id === "email" ? 320 : 200}
                                    onChange={(e) =>
                                        setForm((s) => ({ ...s, [f.id]: e.target.value }))
                                    }
                                    style={{
                                        borderColor: bad ? "var(--st-redline)" : undefined,
                                    }}
                                />
                            </div>
                        );
                    })}

                    {/* Honeypot. Hidden from people, irresistible to naive bots. */}
                    <input
                        type="text"
                        name="website"
                        value={website}
                        onChange={(e) => setWebsite(e.target.value)}
                        tabIndex={-1}
                        autoComplete="off"
                        aria-hidden="true"
                        style={{
                            position: "absolute",
                            left: "-9999px",
                            width: "1px",
                            height: "1px",
                            opacity: 0,
                        }}
                    />

                    <button
                        type="submit"
                        disabled={busy}
                        className="of-btn of-btn--primary"
                        style={{ width: "100%", padding: "11px", marginTop: "8px", fontSize: "13.5px" }}
                    >
                        {busy ? (
                            <>
                                <Loader2 size={14} className="of-spin" />
                                One moment
                            </>
                        ) : (
                            <>
                                Open the studio
                                <ArrowRight size={14} />
                            </>
                        )}
                    </button>

                    {touched && !valid && !error && (
                        <p style={{ marginTop: "10px", fontSize: "12px", color: "var(--st-caution)" }}>
                            All three fields, and an email we can actually reach you at.
                        </p>
                    )}
                    {error && (
                        <p style={{ marginTop: "10px", fontSize: "12px", color: "var(--st-redline)" }}>
                            {error}
                        </p>
                    )}
                </form>

                <p
                    style={{
                        marginTop: "22px",
                        fontSize: "12px",
                        color: "var(--st-pencil)",
                        textAlign: "center",
                    }}
                >
                    Already have an account?{" "}
                    <a href="/auth" style={{ color: "var(--st-ink)", textDecoration: "underline", textUnderlineOffset: "2px" }}>
                        Sign in
                    </a>
                </p>
            </div>
        </div>
    );
}
