import { useEffect } from "react";
import {
    ChevronDown,
    ChevronRight,
    FolderOpen,
    ListTree,
    MousePointerClick,
    SlidersHorizontal,
} from "lucide-react";
import FeatureHistoryTree from "./FeatureHistoryTree";
import ParametersPanel from "./ParametersPanel";
import ProjectsPanel from "./ProjectsPanel";
import FeatureEditPanel from "./FeatureEditPanel";
import { useStudioStore } from "../../store/studioStore";
import { useLibraryStore } from "../../store/libraryStore";
import { useEditStore } from "../../store/editStore";
import { useUIStore } from "../../store/uiStore";

/**
 * The left dock — the model side of the studio.
 *
 * Laid out as a CAD combo view: independent sections that stay open together,
 * because an engineer tuning a dimension wants to watch the feature it belongs
 * to at the same time. Each header carries a count, so a collapsed section
 * still reports what is inside it.
 *
 * The inspector is here rather than beside the conversation, which is where it
 * used to live as a "Selection" tab. A picked face is a fact about the model,
 * not a mode of talking to the agent — and putting it on this side means the
 * feature tree, the dimension that drives it and the controls that change it
 * are all in one column, which is the order the work actually happens in.
 */

function Section({
    id,
    icon,
    title,
    count,
    accent,
    children,
}: {
    id: string;
    icon: React.ReactNode;
    title: string;
    count?: number | string;
    /** Marks a section holding something live, like the current selection. */
    accent?: boolean;
    children: React.ReactNode;
}) {
    const open = useUIStore((s) => s.openSections[id] ?? false);
    const toggle = useUIStore((s) => s.toggleSection);

    return (
        <div
            style={{
                borderBottom: "1px solid var(--st-rule)",
                display: "flex",
                flexDirection: "column",
                minHeight: 0,
                // An open section takes its share of the column; a closed one
                // collapses to its header and gives the space back.
                flex: open ? "1 1 auto" : "0 0 auto",
            }}
        >
            <button
                onClick={() => toggle(id)}
                aria-expanded={open}
                className="of-row"
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    width: "100%",
                    flexShrink: 0,
                    padding: "9px 12px",
                    background: "transparent",
                    border: "none",
                    color: accent ? "var(--st-ink)" : "var(--st-graphite)",
                    fontFamily: "var(--font-mono)",
                    fontSize: "9.5px",
                    fontWeight: 600,
                    letterSpacing: "0.13em",
                    textTransform: "uppercase",
                    cursor: "pointer",
                }}
            >
                {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                {icon}
                <span style={{ flex: 1, textAlign: "left" }}>{title}</span>
                {count !== undefined && count !== 0 && (
                    <span
                        className="of-num"
                        style={{
                            fontSize: "9.5px",
                            color: accent ? "var(--st-ink)" : "var(--st-pencil)",
                            letterSpacing: 0,
                        }}
                    >
                        {count}
                    </span>
                )}
            </button>
            {open && (
                <div className="studio-scroll" style={{ overflowY: "auto", minHeight: 0 }}>
                    {children}
                </div>
            )}
        </div>
    );
}

export default function ModelDock() {
    const features = useStudioStore((s) => s.part?.featureTree?.features.length ?? 0);
    const variables = useStudioStore((s) => Object.keys(s.part?.variables ?? {}).length);
    const projects = useLibraryStore((s) => s.designs.length);

    const selectedFace = useEditStore((s) => s.selectedFace?.ref ?? null);
    const selectedFeature = useEditStore((s) => s.selectedFeature);
    const agentRefs = useEditStore((s) => s.agentRefs.length);
    const openSection = useUIStore((s) => s.toggleSection);
    const inspectorOpen = useUIStore((s) => s.openSections.inspector ?? false);

    // A click in the viewport is already the user asking about that feature, so
    // the inspector opens itself rather than making them find it afterwards.
    // Only a new pick does this — closing it while something is still selected
    // sticks, because that is a deliberate act.
    useEffect(() => {
        if (selectedFace && !inspectorOpen) openSection("inspector");
        // `inspectorOpen` is deliberately not a dependency: including it would
        // re-open the section the moment the user closed it.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedFace]);

    const selectionCount = selectedFace ? 1 : agentRefs;

    return (
        <div
            style={{
                width: "100%",
                height: "100%",
                display: "flex",
                flexDirection: "column",
                minHeight: 0,
                background: "var(--st-sheet)",
            }}
        >
            <Section id="tree" icon={<ListTree size={12} />} title="Feature tree" count={features}>
                <FeatureHistoryTree />
            </Section>

            <Section
                id="parameters"
                icon={<SlidersHorizontal size={12} />}
                title="Parameters"
                count={variables}
            >
                <ParametersPanel />
            </Section>

            <Section
                id="inspector"
                icon={<MousePointerClick size={12} />}
                title="Inspector"
                accent={selectionCount > 0}
                count={
                    selectionCount > 1
                        ? selectionCount
                        : selectedFeature
                          ? selectedFeature
                          : undefined
                }
            >
                <FeatureEditPanel />
            </Section>

            <Section id="projects" icon={<FolderOpen size={12} />} title="Projects" count={projects}>
                <ProjectsPanel />
            </Section>
        </div>
    );
}
