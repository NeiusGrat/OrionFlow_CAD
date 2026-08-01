import { useEffect } from "react";
import { useUIStore } from "../../store/uiStore";

/**
 * The first run.
 *
 * Four cards, each anchored to the part of the workspace it describes, shown
 * once. It points rather than blocks: the panel being described stays visible
 * and usable behind the card, because a tour that greys out the tool it is
 * teaching you about teaches nothing.
 *
 * Escape and the backdrop both dismiss it, and it can be replayed from the
 * account menu — so skipping carries no cost.
 */

interface Step {
    title: string;
    body: string;
    /** Where the card sits, and which edge it points from. */
    anchor: "right" | "left" | "left-lower" | "top";
}

const STEPS: Step[] = [
    {
        title: "Describe your design in plain English",
        body: "The AI engineer helps you plan dimensions, materials and manufacturability before you build. Start in Refine to talk the idea through, then press Build this — or switch to Build mode to generate a 3D model directly.",
        anchor: "right",
    },
    {
        title: "Tree, parameters and projects",
        body: "Track every feature in the design tree, tune live parameters with sliders, and reopen saved work from one panel. Changing a parameter rebuilds the part and re-runs its checks.",
        anchor: "left",
    },
    {
        title: "Manual CAD tools",
        body: "Extrude, pocket, revolve, fillet, chamfer, shell, draft and pattern — the workbench toolbar makes precise manual edits alongside AI generation. Every dimension you enter becomes a named parameter you can tune afterwards.",
        anchor: "top",
    },
    {
        title: "Projects",
        body: "Save your work to the cloud and reopen any project from here. Your conversation, features and model are restored automatically.",
        anchor: "left-lower",
    },
];

const POSITION: Record<Step["anchor"], React.CSSProperties> = {
    right: { top: "104px", right: "406px" },
    left: { top: "104px", left: "282px" },
    "left-lower": { bottom: "56px", left: "282px" },
    top: { top: "104px", left: "50%", transform: "translateX(-50%)" },
};

export default function Onboarding() {
    const step = useUIStore((s) => s.tourStep);
    const next = useUIStore((s) => s.nextTour);
    const end = useUIStore((s) => s.endTour);
    const seen = useUIStore((s) => s.tourSeen);
    const start = useUIStore((s) => s.startTour);

    // Offered once, on the first visit, and never again.
    useEffect(() => {
        if (!seen && step === null) start();
    }, [seen, step, start]);

    useEffect(() => {
        if (step === null) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") end();
            if (e.key === "Enter" || e.key === "ArrowRight") next();
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [step, end, next]);

    if (step === null) return null;
    const current = STEPS[step];
    if (!current) return null;

    return (
        <>
            {/* Dismisses on click but does not dim: the panel being described
                has to stay readable for the description to mean anything. */}
            <div
                onClick={end}
                style={{ position: "fixed", inset: 0, zIndex: 450, background: "transparent" }}
            />
            <div
                key={step}
                className="of-enter"
                role="dialog"
                aria-label={current.title}
                style={{
                    position: "fixed",
                    zIndex: 460,
                    width: "306px",
                    padding: "14px 15px 12px",
                    background: "var(--st-sheet)",
                    border: "1px solid var(--st-blue-edge)",
                    borderRadius: "9px",
                    boxShadow: "var(--st-shadow)",
                    ...POSITION[current.anchor],
                }}
            >
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "7px" }}>
                    {/* A real sequence: the four cards are a walk through the
                        workspace in the order the work happens. */}
                    <span className="of-num" style={{ fontSize: "10px", color: "var(--st-blue)" }}>
                        {step + 1} / {STEPS.length}
                    </span>
                    <div style={{ flex: 1, height: "1px", background: "var(--st-rule)" }} />
                </div>
                <h2 style={{ fontSize: "14px", fontWeight: 650, color: "var(--st-ink)", marginBottom: "6px" }}>
                    {current.title}
                </h2>
                <p style={{ fontSize: "12px", lineHeight: 1.6, color: "var(--st-graphite)", margin: 0 }}>
                    {current.body}
                </p>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "13px" }}>
                    <button
                        onClick={end}
                        style={{
                            background: "transparent",
                            border: "none",
                            color: "var(--st-pencil)",
                            fontSize: "11.5px",
                            cursor: "pointer",
                            padding: 0,
                        }}
                    >
                        Skip
                    </button>
                    <button
                        onClick={next}
                        style={{
                            marginLeft: "auto",
                            padding: "5px 13px",
                            borderRadius: "6px",
                            border: "none",
                            background: "var(--st-blue)",
                            color: "#12100B",
                            fontSize: "11.5px",
                            fontWeight: 700,
                            cursor: "pointer",
                        }}
                    >
                        {step === STEPS.length - 1 ? "Start designing" : "Next"}
                    </button>
                </div>
            </div>
        </>
    );
}
