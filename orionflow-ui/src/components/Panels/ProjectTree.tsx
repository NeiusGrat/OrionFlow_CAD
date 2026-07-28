import { useEffect, useRef, useState } from "react";
import { Box, Save, Trash2, Pencil, Check, X, Loader2, FolderOpen } from "lucide-react";
import { useLibraryStore } from "../../store/libraryStore";
import { useStudioStore } from "../../store/studioStore";

/** The user's saved parts: open, rename, delete, and save the current one.
 *  Deleting is confirmed inline rather than with a modal — the row itself
 *  turns into the confirmation, so the thing being destroyed stays visible. */
export default function ProjectTree() {
    const designs = useLibraryStore((s) => s.designs);
    const loading = useLibraryStore((s) => s.loading);
    const saving = useLibraryStore((s) => s.saving);
    const error = useLibraryStore((s) => s.error);
    const activeId = useLibraryStore((s) => s.activeId);
    const hydrate = useLibraryStore((s) => s.hydrate);
    const saveCurrent = useLibraryStore((s) => s.saveCurrent);
    const rename = useLibraryStore((s) => s.rename);
    const remove = useLibraryStore((s) => s.remove);
    const open = useLibraryStore((s) => s.open);
    const clearError = useLibraryStore((s) => s.clearError);

    const hasPart = useStudioStore((s) => !!s.part);

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
        <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
            <div
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "9px 12px 7px",
                    color: "var(--studio-text-dim)",
                    fontSize: "11px",
                    fontWeight: 700,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                }}
            >
                <FolderOpen size={12} />
                Parts
                <button
                    onClick={() => saveCurrent()}
                    disabled={!hasPart || saving}
                    title={hasPart ? "Save the current part" : "Design a part first"}
                    style={{
                        marginLeft: "auto",
                        display: "flex",
                        alignItems: "center",
                        gap: "4px",
                        padding: "3px 8px",
                        borderRadius: "5px",
                        border: "1px solid var(--studio-border)",
                        background: hasPart ? "var(--studio-accent-dim)" : "transparent",
                        color: hasPart ? "var(--studio-accent)" : "var(--studio-text-faint)",
                        fontSize: "10px",
                        fontWeight: 700,
                        letterSpacing: "0.05em",
                        cursor: hasPart && !saving ? "pointer" : "default",
                        textTransform: "none",
                    }}
                >
                    {saving ? <Loader2 size={10} className="of-spin" /> : <Save size={10} />}
                    {activeId ? "Update" : "Save"}
                </button>
            </div>

            {error && (
                <div
                    style={{
                        margin: "0 10px 8px",
                        padding: "7px 9px",
                        borderRadius: "6px",
                        border: "1px solid var(--studio-err)",
                        background: "var(--studio-panel-2)",
                        color: "var(--studio-err)",
                        fontSize: "11px",
                        display: "flex",
                        gap: "6px",
                        alignItems: "flex-start",
                    }}
                >
                    <span style={{ flex: 1 }}>{error}</span>
                    <button
                        onClick={clearError}
                        style={{
                            background: "transparent",
                            border: "none",
                            color: "var(--studio-err)",
                            cursor: "pointer",
                            padding: 0,
                        }}
                    >
                        <X size={11} />
                    </button>
                </div>
            )}

            {loading && (
                <div style={{ padding: "4px 14px 10px", fontSize: "11.5px", color: "var(--studio-text-faint)" }}>
                    Loading…
                </div>
            )}

            {!loading && designs.length === 0 && (
                <div
                    style={{
                        padding: "2px 14px 10px",
                        fontSize: "11.5px",
                        color: "var(--studio-text-faint)",
                        lineHeight: 1.5,
                    }}
                >
                    Nothing saved yet. Build a part, then press Save.
                </div>
            )}

            <div style={{ paddingBottom: "6px" }}>
                {designs.map((d) => {
                    const active = activeId === d.id;
                    const isEditing = editing === d.id;
                    const isConfirming = confirming === d.id;

                    if (isConfirming) {
                        return (
                            <div
                                key={d.id}
                                style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "8px",
                                    padding: "7px 12px",
                                    background: "rgba(222,136,113,0.10)",
                                    borderLeft: "2px solid var(--studio-err)",
                                    fontSize: "11.5px",
                                    color: "var(--studio-text)",
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
                                        background: "var(--studio-err)",
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
                                    style={{
                                        border: "none",
                                        background: "transparent",
                                        color: "var(--studio-text-dim)",
                                        cursor: "pointer",
                                        fontSize: "10.5px",
                                    }}
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
                                background: active ? "var(--studio-accent-dim)" : "transparent",
                                borderLeft: `2px solid ${active ? "var(--studio-accent)" : "transparent"}`,
                            }}
                        >
                            <Box
                                size={12}
                                style={{ flexShrink: 0, color: active ? "var(--studio-accent)" : "var(--studio-text-faint)" }}
                            />

                            {isEditing ? (
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
                                            background: "var(--studio-panel-2)",
                                            border: "1px solid var(--studio-accent)",
                                            borderRadius: "4px",
                                            color: "var(--studio-text)",
                                            fontSize: "12px",
                                            padding: "2px 6px",
                                            outline: "none",
                                            fontFamily: "inherit",
                                        }}
                                    />
                                    <button
                                        onClick={() => commitRename(d.id)}
                                        style={iconBtn}
                                        title="Save name"
                                    >
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
                                            color: active ? "var(--studio-text)" : "var(--studio-text-dim)",
                                            fontSize: "12px",
                                            whiteSpace: "nowrap",
                                            overflow: "hidden",
                                            textOverflow: "ellipsis",
                                        }}
                                    >
                                        {d.name}
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
                                    <button
                                        onClick={() => setConfirming(d.id)}
                                        style={iconBtn}
                                        title="Delete"
                                    >
                                        <Trash2 size={11} />
                                    </button>
                                </>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

const iconBtn: React.CSSProperties = {
    background: "transparent",
    border: "none",
    color: "var(--studio-text-faint)",
    cursor: "pointer",
    padding: "2px",
    display: "flex",
    alignItems: "center",
    flexShrink: 0,
};
