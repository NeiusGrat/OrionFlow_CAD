import { useEffect, useState } from "react";
import { useUIStore } from "../../store/uiStore";

/**
 * The first run.
 *
 * Three cards, each anchored to the part of the workspace it describes, shown
 * once. It points rather than blocks: the panel being described stays visible
 * and usable behind the card, because a tour that greys out the tool it is
 * teaching you about teaches nothing.
 *
 * Only shown on a layout wide enough to have the three columns it points at. On
 * a stacked screen the panes are behind a switcher, so a card pointing at
 * "the column on the right" would be pointing at nothing — and a tour that
 * describes a layout the user cannot see is worse than no tour.
 *
 * Escape and the backdrop both dismiss it, and it can be replayed from the
 * account menu — so skipping carries no cost.
 */

interface Step {
    title: string;
    body: string;
    /** Where the card sits, and which edge it points from. */
    anchor: "right" | "left" | "top";
}

const STEPS: Step[] = [
    {
        title: "One conversation, every operation",
        body: "Build a part, change a dimension, select a feature, or ask for a manufacturability review — all in the same thread. There is no mode to choose: say what you want and Orion works out which it is. The line under the composer tells you what it decided before you press Enter.",
        anchor: "right",
    },
    {
        title: "The model side",
        body: "Every feature in the build history, every dimension the model named, and the inspector for whatever is selected. Changing a parameter rebuilds the part and re-runs its checks — the numbers here are live, not a readout.",
        anchor: "left",
    },
    {
        title: "Manual CAD tools",
        body: "Extrude, pocket, revolve, fillet, chamfer, shell, draft and pattern, for when you would rather do it by hand than describe it. Every dimension you enter becomes a named parameter you can tune afterwards.",
        anchor: "top",
    },
];

const POSITION: Record<Step["anchor"], React.CSSProperties> = {
    right: { top: "108px", right: "424px" },
    left: { top: "108px", left: "286px" },
    top: { top: "108px", left: "50%", transform: "translateX(-50%)" },
};

/** The tour only makes sense on the three-column layout it describes. */
function useWideEnough(): boolean {
    const [wide, setWide] = useState(() =>
        typeof window === "undefined" ? true : window.innerWidth >= 1280,
    );
    useEffect(() => {
        const on = () => setWide(window.innerWidth >= 1280);
        window.addEventListener("resize", on);
        return () => window.removeEventListener("resize", on);
    }, []);
    return wide;
}

export default function Onboarding() {
    const step = useUIStore((s) => s.tourStep);
    const next = useUIStore((s) => s.nextTour);
    const end = useUIStore((s) => s.endTour);
    const seen = useUIStore((s) => s.tourSeen);
    const start = useUIStore((s) => s.startTour);
    const wide = useWideEnough();

    // Offered once, on the first visit, and never again.
    useEffect(() => {
        if (!seen && step === null && wide) start();
    }, [seen, step, start, wide]);

    useEffect(() => {
        if (step === null) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") end();
            if (e.key === "Enter" || e.key === "ArrowRight") next(STEPS.length);
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [step, end, next]);

    if (step === null || !wide) return null;
    const current = STEPS[step];
    // The step counter is persisted and the tour has changed length before, so
    // a stored index can point past the end. Ending is the right reading of
    // "there is no step here" — it is a tour that has already been taken.
    if (!current) {
        end();
        return null;
    }

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
                    width: "312px",
                    padding: "15px 16px 13px",
                    background: "var(--st-sheet)",
                    border: "1px solid var(--st-rule)",
                    borderRadius: "var(--st-r-lg)",
                    boxShadow: "var(--st-shadow)",
                    ...POSITION[current.anchor],
                }}
            >
                <div style={{ display: "flex", alignItems: "center", gap: "9px", marginBottom: "9px" }}>
                    <span className="of-bracket">
                        [{String(step + 1).padStart(2, "0")} / {String(STEPS.length).padStart(2, "0")}]
                    </span>
                    <div style={{ flex: 1, height: "1px", background: "var(--st-rule)" }} />
                </div>
                <h2 style={{ fontSize: "14.5px", fontWeight: 600, color: "var(--st-ink)", marginBottom: "7px" }}>
                    {current.title}
                </h2>
                <p style={{ fontSize: "12.5px", lineHeight: 1.65, color: "var(--st-graphite)", margin: 0 }}>
                    {current.body}
                </p>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "15px" }}>
                    <button onClick={end} className="of-btn of-btn--quiet" style={{ fontSize: "11.5px", padding: "5px 8px" }}>
                        Skip
                    </button>
                    <button
                        onClick={() => next(STEPS.length)}
                        className="of-btn of-btn--primary"
                        style={{ marginLeft: "auto", fontSize: "11.5px", padding: "6px 13px" }}
                    >
                        {step === STEPS.length - 1 ? "Start designing" : "Next"}
                    </button>
                </div>
            </div>
        </>
    );
}
