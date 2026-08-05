import { useEffect, useState } from "react";
import Viewer from "../Viewer/Viewer";
import AssistantPanel from "../Panels/AssistantPanel";
import SessionPanel from "../Panels/SessionPanel";
import FeatureEditPanel from "../Panels/FeatureEditPanel";
import { useEditStore } from "../../store/editStore";
import ModelDock from "../Panels/ModelDock";
import TitleBar from "./TitleBar";
import Ribbon from "./Ribbon";
import TitleBlock from "./TitleBlock";
import ToolDialog from "./ToolDialog";
import Onboarding from "./Onboarding";
import { useDesignStore } from "../../store/designStore";

/**
 * The workstation.
 *
 *   ┌──────────────────────────────────────────────────────────┐
 *   │ title bar — document, undo/redo, save, export, account   │
 *   ├──────────────────────────────────────────────────────────┤
 *   │ workbench ribbon — solids · modify · pattern · view      │
 *   ├────────────┬───────────────────────────┬─────────────────┤
 *   │ model dock │        viewport           │  AI engineer    │
 *   │ tree       │                           │  refine / build │
 *   │ parameters │                           │                 │
 *   │ projects   │                           │                 │
 *   ├────────────┴───────────────────────────┴─────────────────┤
 *   │ title block — part · units · extent · rev · verdict      │
 *   └──────────────────────────────────────────────────────────┘
 *
 * The model is on the left and the conversation on the right, which is the
 * arrangement every CAD package uses and the one the reference images use:
 * what the part *is* stays next to the tree that defines it, and the assistant
 * gets the column it needs for a derivation without pushing the model out of
 * sight.
 */
/**
 * The two ways to design, side by side rather than one replacing the other.
 *
 * `chat` is the one-shot route: describe a part and get geometry. It is live,
 * it is what every existing user knows, and nothing here changes it.
 *
 * `reviewed` is the session route: the design stops at a plan and waits to be
 * approved. It is the better shape for anything load-bearing, but it asks for
 * patience, so it is offered rather than imposed.
 */
/**
 * `edit` is neither: it is the part answering questions about itself. Clicking
 * a face opens it on the feature that authored that face, so the tab is
 * switched to automatically on a pick rather than being somewhere the user has
 * to go looking after they have already pointed at what they meant.
 */
type PanelTab = "chat" | "reviewed" | "edit";

function PanelTabs({
    tab,
    onChange,
}: {
    tab: PanelTab;
    onChange: (t: PanelTab) => void;
}) {
    return (
        <div style={{ display: "flex", borderBottom: "1px solid var(--st-rule)" }}>
            {(
                [
                    ["chat", "Assistant"],
                    ["reviewed", "Reviewed build"],
                    ["edit", "Selection"],
                ] as const
            ).map(([id, text]) => (
                <button
                    key={id}
                    onClick={() => onChange(id)}
                    style={{
                        flex: 1,
                        padding: "8px 6px",
                        fontSize: "11px",
                        letterSpacing: "0.06em",
                        textTransform: "uppercase",
                        fontFamily: "inherit",
                        background: "transparent",
                        color: tab === id ? "var(--st-ink)" : "var(--st-pencil)",
                        border: "none",
                        borderBottom:
                            tab === id
                                ? "2px solid var(--st-blue)"
                                : "2px solid transparent",
                        cursor: "pointer",
                    }}
                >
                    {text}
                </button>
            ))}
        </div>
    );
}

export default function Workspace() {
    const current = useDesignStore((s) => s.current);
    const [tab, setTab] = useState<PanelTab>("chat");

    // A click in the viewport is already the user asking about that feature;
    // making them find the tab afterwards would put a step between the question
    // and the answer. Only a new selection pulls focus, so switching back to
    // the assistant while something is selected sticks.
    const selectedFace = useEditStore((s) => s.selectedFace?.ref ?? null);
    useEffect(() => {
        if (selectedFace) setTab("edit");
    }, [selectedFace]);

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
            <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
                <ModelDock />
                <div style={{ flex: 1, position: "relative", minWidth: 0 }}>
                    <Viewer url={current ? current.files.glb : ""} />
                </div>
                <div
                    style={{
                        width: "392px",
                        flexShrink: 0,
                        display: "flex",
                        flexDirection: "column",
                        minHeight: 0,
                        borderLeft: "1px solid var(--st-rule)",
                        background: "var(--st-sheet)",
                    }}
                >
                    <PanelTabs tab={tab} onChange={setTab} />
                    {/* The assistant is kept mounted rather than unmounted on
                        switch: it holds a live conversation and a streaming
                        turn, and remounting it mid-build would abandon both. */}
                    <div
                        style={{
                            flex: 1,
                            minHeight: 0,
                            display: tab === "chat" ? "flex" : "none",
                            flexDirection: "column",
                        }}
                    >
                        <AssistantPanel />
                    </div>
                    <div
                        style={{
                            flex: 1,
                            minHeight: 0,
                            display: tab === "reviewed" ? "flex" : "none",
                            flexDirection: "column",
                            overflow: "hidden",
                        }}
                    >
                        <SessionPanel />
                    </div>
                    <div
                        style={{
                            flex: 1,
                            minHeight: 0,
                            display: tab === "edit" ? "block" : "none",
                            overflowY: "auto",
                        }}
                    >
                        <FeatureEditPanel />
                    </div>
                </div>
            </div>
            <TitleBlock />
            <ToolDialog />
            <Onboarding />
        </div>
    );
}
