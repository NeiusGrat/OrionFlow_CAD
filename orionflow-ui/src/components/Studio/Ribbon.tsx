import { Box, Grid3x3, Maximize2, ChevronUp, ChevronDown } from "lucide-react";
import ToolIcon from "./ToolIcons";
import { TOOL_GROUPS, toolsIn, type ToolSpec } from "../../lib/workbench";
import { useUIStore } from "../../store/uiStore";
import { useStudioStore } from "../../store/studioStore";
import { useDesignStore } from "../../store/designStore";

/**
 * The workbench toolbar.
 *
 * Grouped the way a machinist thinks about the work — what adds material, what
 * modifies it, what repeats it — with the group named underneath, because a
 * toolbar of unlabelled glyphs is a memory test. Views sit on the far right,
 * away from anything that changes the model, so no one reaches for Fit and
 * hits Pocket.
 *
 * Everything here needs a part to act on. Rather than hiding the tools before
 * one exists, they are disabled and say why on hover: an empty workbench that
 * shows what it will be able to do is more useful than an empty strip.
 */

function Tool({ tool, onPick, disabled, reason }: {
    tool: ToolSpec;
    onPick: () => void;
    disabled: boolean;
    reason: string;
}) {
    const blocked = disabled || !!tool.unavailable;
    return (
        <button
            className="of-tool"
            onClick={onPick}
            disabled={blocked}
            title={tool.unavailable || (disabled ? reason : `${tool.label} — ${tool.hint}`)}
        >
            <ToolIcon name={tool.icon} />
            <span>{tool.label}</span>
        </button>
    );
}

function Group({ name, children }: { name: string; children: React.ReactNode }) {
    return (
        <div className="of-tool-group">
            <div style={{ display: "flex", gap: "1px" }}>{children}</div>
            <span
                className="of-label"
                style={{ fontSize: "8px", letterSpacing: "0.13em", paddingBottom: "1px" }}
            >
                {name}
            </span>
        </div>
    );
}

export default function Ribbon() {
    const open = useUIStore((s) => s.ribbonOpen);
    const toggle = useUIStore((s) => s.toggleRibbon);
    const openTool = useUIStore((s) => s.openTool);
    const hasPart = useStudioStore((s) => !!s.part?.blueprint);
    const rebuilding = useStudioStore((s) => s.rebuilding);
    const triggerView = useDesignStore((s) => s.triggerViewAction);

    const reason = !hasPart
        ? "Build a part first — these tools edit the open model"
        : "A rebuild is already running";
    const locked = !hasPart || rebuilding;

    if (!open) {
        return (
            <div
                style={{
                    height: "22px",
                    flexShrink: 0,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    background: "var(--st-sheet)",
                    borderBottom: "1px solid var(--st-rule)",
                }}
            >
                <button
                    onClick={toggle}
                    title="Show the workbench"
                    style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "6px",
                        background: "transparent",
                        border: "none",
                        color: "var(--st-pencil)",
                        fontSize: "10px",
                        fontWeight: 600,
                        letterSpacing: "0.09em",
                        textTransform: "uppercase",
                        cursor: "pointer",
                    }}
                >
                    <ChevronDown size={11} />
                    Workbench
                </button>
            </div>
        );
    }

    return (
        <div
            style={{
                flexShrink: 0,
                display: "flex",
                alignItems: "stretch",
                gap: "0",
                padding: "5px 4px 3px",
                background: "var(--st-sheet)",
                borderBottom: "1px solid var(--st-rule)",
                overflowX: "auto",
            }}
            className="studio-scroll"
        >
            {TOOL_GROUPS.map((g) => (
                <Group key={g} name={g}>
                    {toolsIn(g).map((t) => (
                        <Tool
                            key={t.id}
                            tool={t}
                            disabled={locked}
                            reason={reason}
                            onPick={() => openTool({ kind: t.id, label: t.label })}
                        />
                    ))}
                </Group>
            ))}

            {/* Views change nothing about the model, so they sit apart from
                everything that does. */}
            <div className="of-tool-group" style={{ marginLeft: "auto", borderRight: "none" }}>
                <div style={{ display: "flex", gap: "1px" }}>
                    <button className="of-tool" onClick={() => triggerView("iso")} title="Isometric view">
                        <Box size={19} strokeWidth={1.35} />
                        <span>Iso</span>
                    </button>
                    <button className="of-tool" onClick={() => triggerView("ortho")} title="Top view">
                        <Grid3x3 size={19} strokeWidth={1.35} />
                        <span>Top</span>
                    </button>
                    <button className="of-tool" onClick={() => triggerView("reset")} title="Fit the part in view">
                        <Maximize2 size={19} strokeWidth={1.35} />
                        <span>Fit</span>
                    </button>
                    <button className="of-tool" onClick={toggle} title="Hide the workbench">
                        <ChevronUp size={19} strokeWidth={1.35} />
                        <span>Hide</span>
                    </button>
                </div>
                <span className="of-label" style={{ fontSize: "8px", letterSpacing: "0.13em", paddingBottom: "1px" }}>
                    View
                </span>
            </div>
        </div>
    );
}
