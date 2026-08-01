import Viewer from "../Viewer/Viewer";
import AssistantPanel from "../Panels/AssistantPanel";
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
export default function Workspace() {
    const current = useDesignStore((s) => s.current);

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
                <AssistantPanel />
            </div>
            <TitleBlock />
            <ToolDialog />
            <Onboarding />
        </div>
    );
}
