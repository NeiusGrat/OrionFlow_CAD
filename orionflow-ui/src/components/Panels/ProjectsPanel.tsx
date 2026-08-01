import { useEffect, useRef, useState } from "react";
import { Box, Check, FilePlus2, Loader2, Pencil, Trash2, X } from "lucide-react";
import { useLibraryStore } from "../../store/libraryStore";
import { useStudioStore } from "../../store/studioStore";

/**
 * Projects saved to the cloud.
 *
 * Opening one restores the Blueprint, the geometry, the verification report and
 * the conversation that produced it — the transcript travels with the design
 * row, so reopening a project puts back the reasoning and not just the mesh.
 *
 * Deleting is confirmed inline rather than with a modal: the row itself turns
 * into the confirmation, so the thing being destroyed stays visible while the
 * user decides.
 */

const iconBtn: React.CSSProperties = {
    background: "transparent",
    border: "none",
    color: "var(--st-pencil)",
    cursor: "pointer",
    padding: "2px",
    display: "flex",
    alignItems: "center",
    flexShrink: 0,
};

function when(iso: string): string {
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return "";
    const mins = Math.round((Date.now() - then) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.round(hrs / 24);
    return days < 30 ? `${days}d ago` : new Date(iso).toLocaleDateString();
}

export default function ProjectsPanel() {
    const designs = useLibraryStore((s) => s.designs);
    const loading = useLibraryStore((s) => s.loading);
    const error = useLibraryStore((s) => s.error);
    const activeId = useLibraryStore((s) => s.activeId);
    const hydrate = useLibraryStore((s) => s.hydrate);
    const rename = useLibraryStore((s) => s.rename);
    const remove = useLibraryStore((s) => s.remove);
    const open = useLibraryStore((s) => s.open);
    const detach = useLibraryStore((s) => s.detach);
    const clearError = useLibraryStore((s) => s.clearError);
    const resetStudio = useStudioStore((s) => s.reset);

    const [editing, setEditing] = useState<string | null>(null);
    const [draft, setDraft] = useState("");
    const [confirming, setConfirming] = useState<string | null>(null);
    const inputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        hydrate();
    }, [hydrate]);

    useEffect(() => {
        if (editing) inputRef.current?.focus();
    }, [editing]);

    const commitRename = (id: string) => {
        if (draft.trim()) rename(id, draft);
        setEditing(null);
    };

    return (
        <div>
            {error && (
                <div
                    style={{
                        margin: "6px 10px 8px",
                        padding: "7px 9px",
                        borderRadius: "5px",
                        border: "1px solid var(--st-redline)",
                        background: "var(--st-raise)",
                        color: "var(--st-redline)",
                        fontSize: "11px",
                        display: "flex",
                        gap: "6px",
                        alignItems: "flex-start",
                        lineHeight: 1.45,
                    }}
                >
                    <span style={{ flex: 1 }}>{error}</span>
                    <button onClick={clearError} style={{ ...iconBtn, color: "var(--st-redline)" }} title="Dismiss">
                        <X size={11} />
                    </button>
                </div>
            )}

            <button
                onClick={() => {
                    detach();
                    resetStudio();
                }}
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "7px",
                    width: "100%",
                    padding: "7px 12px",
                    background: "transparent",
                    border: "none",
                    borderBottom: "1px solid var(--st-rule-soft)",
                    color: "var(--st-graphite)",
                    fontSize: "12px",
                    cursor: "pointer",
                    textAlign: "left",
                }}
                className="of-row"
                title="Clear the studio and start a new part"
            >
                <FilePlus2 size={12} />
                New project
            </button>

            {loading && (
                <div style={{ padding: "9px 12px", fontSize: "11.5px", color: "var(--st-pencil)", display: "flex", gap: "7px", alignItems: "center" }}>
                    <Loader2 size={11} className="of-spin" />
                    Loading…
                </div>
            )}

            {!loading && !error && designs.length === 0 && (
                <div style={{ padding: "10px 12px", fontSize: "11.5px", color: "var(--st-pencil)", lineHeight: 1.55 }}>
                    Nothing saved yet. Build a part, then press Save in the top bar —
                    your conversation, features and model come back with it.
                </div>
            )}

            {designs.map((d) => {
                const active = activeId === d.id;

                if (confirming === d.id) {
                    return (
                        <div
                            key={d.id}
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: "8px",
                                padding: "7px 12px",
                                background: "rgba(222,136,113,0.10)",
                                borderLeft: "2px solid var(--st-redline)",
                                fontSize: "11.5px",
                                color: "var(--st-ink)",
                            }}
                        >
                            <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                Delete “{d.name}”?
                            </span>
                            <button
                                onClick={() => {
                                    remove(d.id);
                                    setConfirming(null);
                                }}
                                style={{
                                    border: "none",
                                    background: "var(--st-redline)",
                                    color: "#1B1712",
                                    borderRadius: "4px",
                                    padding: "2px 8px",
                                    fontSize: "10.5px",
                                    fontWeight: 700,
                                    cursor: "pointer",
                                }}
                            >
                                Delete
                            </button>
                            <button
                                onClick={() => setConfirming(null)}
                                style={{ border: "none", background: "transparent", color: "var(--st-graphite)", cursor: "pointer", fontSize: "10.5px" }}
                            >
                                Cancel
                            </button>
                        </div>
                    );
                }

                return (
                    <div
                        key={d.id}
                        className="of-row"
                        style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "7px",
                            padding: "6px 10px 6px 12px",
                            background: active ? "var(--st-blue-wash)" : "transparent",
                            borderLeft: `2px solid ${active ? "var(--st-blue)" : "transparent"}`,
                        }}
                    >
                        <Box size={12} style={{ flexShrink: 0, color: active ? "var(--st-blue)" : "var(--st-pencil)" }} />

                        {editing === d.id ? (
                            <>
                                <input
                                    ref={inputRef}
                                    value={draft}
                                    onChange={(e) => setDraft(e.target.value)}
                                    onKeyDown={(e) => {
                                        if (e.key === "Enter") commitRename(d.id);
                                        if (e.key === "Escape") setEditing(null);
                                    }}
                                    style={{
                                        flex: 1,
                                        minWidth: 0,
                                        background: "var(--st-raise)",
                                        border: "1px solid var(--st-blue)",
                                        borderRadius: "4px",
                                        color: "var(--st-ink)",
                                        fontSize: "12px",
                                        padding: "2px 6px",
                                        outline: "none",
                                        fontFamily: "inherit",
                                    }}
                                />
                                <button onClick={() => commitRename(d.id)} style={iconBtn} title="Save name">
                                    <Check size={11} />
                                </button>
                            </>
                        ) : (
                            <>
                                <button
                                    onClick={() => open(d.id)}
                                    title={d.original_prompt}
                                    style={{
                                        flex: 1,
                                        minWidth: 0,
                                        textAlign: "left",
                                        background: "transparent",
                                        border: "none",
                                        padding: 0,
                                        cursor: "pointer",
                                        color: active ? "var(--st-ink)" : "var(--st-graphite)",
                                        fontSize: "12px",
                                        display: "flex",
                                        flexDirection: "column",
                                        gap: "1px",
                                    }}
                                >
                                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", width: "100%" }}>
                                        {d.name}
                                    </span>
                                    <span className="of-num" style={{ fontSize: "9.5px", color: "var(--st-pencil)" }}>
                                        {when(d.updated_at)}
                                    </span>
                                </button>
                                <button
                                    onClick={() => {
                                        setDraft(d.name);
                                        setEditing(d.id);
                                    }}
                                    style={iconBtn}
                                    title="Rename"
                                >
                                    <Pencil size={11} />
                                </button>
                                <button onClick={() => setConfirming(d.id)} style={iconBtn} title="Delete">
                                    <Trash2 size={11} />
                                </button>
                            </>
                        )}
                    </div>
                );
            })}
        </div>
    );
}
