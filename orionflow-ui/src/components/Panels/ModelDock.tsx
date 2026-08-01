import { ChevronDown, ChevronRight, FolderOpen, ListTree, SlidersHorizontal } from "lucide-react";
import FeatureHistoryTree from "./FeatureHistoryTree";
import ParametersPanel from "./ParametersPanel";
import ProjectsPanel from "./ProjectsPanel";
import { useStudioStore } from "../../store/studioStore";
import { useLibraryStore } from "../../store/libraryStore";
import { useUIStore } from "../../store/uiStore";

/**
 * The left dock — the model side of the studio.
 *
 * Laid out as a CAD combo view: independent sections that stay open together,
 * because an engineer tuning a dimension wants to watch the feature it belongs
 * to at the same time. Each header carries a count, so a collapsed section
 * still reports what is inside it.
 *
 * The demo examples list used to live over on the right. It is gone: a browse
 * list of somebody else's parts is the least useful thing that can occupy a
 * permanent panel in a tool you have your own work open in.
 */

function Section({
    id,
    icon,
    title,
    count,
    children,
}: {
    id: string;
    icon: React.ReactNode;
    title: string;
    count?: number | string;
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
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "7px",
                    width: "100%",
                    flexShrink: 0,
                    padding: "8px 11px",
                    background: "transparent",
                    border: "none",
                    color: "var(--st-graphite)",
                    fontSize: "10px",
                    fontWeight: 700,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    cursor: "pointer",
                }}
            >
                {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                {icon}
                <span style={{ flex: 1, textAlign: "left" }}>{title}</span>
                {count !== undefined && count !== 0 && (
                    <span className="of-num" style={{ fontSize: "9.5px", color: "var(--st-pencil)", letterSpacing: 0 }}>
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

    return (
        <div
            style={{
                width: "268px",
                flexShrink: 0,
                display: "flex",
                flexDirection: "column",
                minHeight: 0,
                background: "var(--st-sheet)",
                borderRight: "1px solid var(--st-rule)",
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
            <Section id="projects" icon={<FolderOpen size={12} />} title="Projects" count={projects}>
                <ProjectsPanel />
            </Section>
        </div>
    );
}
