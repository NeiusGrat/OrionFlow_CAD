import { useEffect, useState } from "react";
import { Boxes, MessageSquare, PanelLeft, Rows3 } from "lucide-react";
import Viewer from "../Viewer/Viewer";
import AgentPanel from "../Panels/AgentPanel";
import ModelDock from "../Panels/ModelDock";
import TitleBar from "./TitleBar";
import Ribbon from "./Ribbon";
import TitleBlock from "./TitleBlock";
import ToolDialog from "./ToolDialog";
import Onboarding from "./Onboarding";
import { useDesignStore } from "../../store/designStore";
import { useUIStore } from "../../store/uiStore";

/**
 * The workstation.
 *
 *   ┌──────────────────────────────────────────────────────────┐
 *   │ title bar — document, undo/redo, save, export, account   │
 *   ├──────────────────────────────────────────────────────────┤
 *   │ workbench ribbon — solids · modify · pattern · view      │
 *   ├────────────┬───────────────────────────┬─────────────────┤
 *   │ model dock │        viewport           │  Orion          │
 *   │ tree       │        (the hero)         │  one agent,     │
 *   │ parameters │                           │  one thread     │
 *   │ inspector  │                           │                 │
 *   │ projects   │                           │                 │
 *   ├────────────┴───────────────────────────┴─────────────────┤
 *   │ title block — part · units · extent · rev · verdict      │
 *   └──────────────────────────────────────────────────────────┘
 *
 * The tab strip that used to sit over the right column is gone. It offered
 * Assistant, Reviewed build and Selection — three doors into one system, which
 * made the user route their own request before they were allowed to make it.
 * There is one conversation now, and what used to be behind those tabs is
 * either inferred (`lib/intent.ts`), rendered inline in the thread (the plan
 * and its approval), or moved to the side it belongs on: a selected face is a
 * fact about the model, so the inspector lives in the model dock.
 *
 * The viewport is given the leftover width in every layout, and both flanking
 * columns are fixed. That is the whole hierarchy: the part is the subject and
 * the panels are apparatus around it.
 */

/** Which single pane a narrow screen is showing. */
type Pane = "model" | "view" | "agent";

/**
 * The three layouts, by available width.
 *
 * Measured against the window rather than a container query because the
 * workspace is always the full viewport, and a resize listener is one line
 * where a ResizeObserver would be a component.
 */
function useLayout(): "wide" | "medium" | "narrow" {
    const [w, setW] = useState(() =>
        typeof window === "undefined" ? 1440 : window.innerWidth,
    );
    useEffect(() => {
        const on = () => setW(window.innerWidth);
        window.addEventListener("resize", on);
        return () => window.removeEventListener("resize", on);
    }, []);
    return w >= 1280 ? "wide" : w >= 960 ? "medium" : "narrow";
}

/** The pane switcher a narrow screen gets instead of three columns. */
function PaneSwitch({ pane, onChange }: { pane: Pane; onChange: (p: Pane) => void }) {
    const items: [Pane, string, React.ReactNode][] = [
        ["model", "Model", <Rows3 size={13} key="m" />],
        ["view", "Part", <Boxes size={13} key="v" />],
        ["agent", "Orion", <MessageSquare size={13} key="a" />],
    ];
    return (
        <div
            style={{
                display: "flex",
                flexShrink: 0,
                borderTop: "1px solid var(--st-rule)",
                background: "var(--st-sheet)",
            }}
        >
            {items.map(([id, label, icon]) => (
                <button
                    key={id}
                    onClick={() => onChange(id)}
                    aria-pressed={pane === id}
                    style={{
                        flex: 1,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        gap: "7px",
                        padding: "10px 4px",
                        background: "transparent",
                        border: "none",
                        borderTop: `2px solid ${pane === id ? "var(--st-accent)" : "transparent"}`,
                        color: pane === id ? "var(--st-ink)" : "var(--st-pencil)",
                        fontSize: "11.5px",
                        fontWeight: 500,
                        cursor: "pointer",
                    }}
                >
                    {icon}
                    {label}
                </button>
            ))}
        </div>
    );
}

export default function Workspace() {
    const current = useDesignStore((s) => s.current);
    const layout = useLayout();
    const dockOpen = useUIStore((s) => s.dockOpen);
    const toggleDock = useUIStore((s) => s.toggleDock);

    const [pane, setPane] = useState<Pane>("view");

    // On a phone the part is what you came for, so that is what opens. The
    // agent is one tap away rather than in front of the model.
    const stacked = layout === "narrow";

    // Every pane stays mounted and is hidden with `display`, never unmounted.
    // The viewport holds a live WebGL context and a framed camera, and the
    // agent holds a streaming turn; tearing either down on a resize or a tab
    // switch would drop work that is genuinely in flight.
    const show = (p: Pane): React.CSSProperties =>
        stacked && pane !== p ? { display: "none" } : {};

    const dockVisible = stacked ? pane === "model" : dockOpen;
    const agentWidth = layout === "wide" ? 404 : 356;

    return (
        <div
            style={{
                display: "flex",
                flexDirection: "column",
                height: "100vh",
                width: "100vw",
                overflow: "hidden",
                background: "var(--st-void)",
                color: "var(--st-ink)",
            }}
        >
            <TitleBar />
            <Ribbon />

            <div style={{ flex: 1, display: "flex", minHeight: 0, position: "relative" }}>
                {/* ── model side ── */}
                <div
                    style={{
                        ...show("model"),
                        width: stacked ? "100%" : "268px",
                        flexShrink: 0,
                        minHeight: 0,
                        display: dockVisible ? "flex" : "none",
                        flexDirection: "column",
                    }}
                >
                    <ModelDock />
                </div>

                {/* ── the part ── */}
                <div
                    style={{
                        ...show("view"),
                        flex: 1,
                        position: "relative",
                        minWidth: 0,
                        display: stacked && pane !== "view" ? "none" : "block",
                        borderLeft: dockVisible && !stacked ? "1px solid var(--st-rule)" : "none",
                        borderRight: !stacked ? "1px solid var(--st-rule)" : "none",
                    }}
                >
                    <Viewer url={current ? current.files.glb : ""} />
                    {/* A single soft pool of light over the stage. It is what
                        keeps a black panel beside a black viewport from reading
                        as one flat void. */}
                    <div className="of-stage-light" />

                    {/* Collapsing the dock is a viewport control, not a menu
                        item: it exists to give the part more room, so it sits
                        on the part. */}
                    {!stacked && (
                        <button
                            onClick={toggleDock}
                            title={dockOpen ? "Hide the model panel" : "Show the model panel"}
                            aria-pressed={dockOpen}
                            style={{
                                position: "absolute",
                                top: "10px",
                                left: "10px",
                                width: "27px",
                                height: "27px",
                                borderRadius: "var(--st-r)",
                                border: "1px solid var(--st-rule)",
                                background: "var(--st-sheet)",
                                color: dockOpen ? "var(--st-ink)" : "var(--st-pencil)",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                cursor: "pointer",
                                boxShadow: "var(--st-shadow-sm)",
                            }}
                        >
                            <PanelLeft size={13} />
                        </button>
                    )}
                </div>

                {/* ── Orion ── */}
                <div
                    style={{
                        ...show("agent"),
                        width: stacked ? "100%" : `${agentWidth}px`,
                        flexShrink: 0,
                        display: stacked && pane !== "agent" ? "none" : "flex",
                        flexDirection: "column",
                        minHeight: 0,
                        minWidth: 0,
                        background: "var(--st-sheet)",
                    }}
                >
                    <AgentPanel />
                </div>
            </div>

            {stacked && <PaneSwitch pane={pane} onChange={setPane} />}
            <TitleBlock />
            <ToolDialog />
            <Onboarding />
        </div>
    );
}
