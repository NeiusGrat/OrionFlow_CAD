import { useEffect, useRef, useState } from "react";
import {
    Check,
    Download,
    ExternalLink,
    Loader2,
    Redo2,
    Save,
    Undo2,
} from "lucide-react";
import OrionFlowLogo, { OrionFlowWordmark } from "../OrionFlowLogo";
import AccountMenu from "./AccountMenu";
import { useStudioStore } from "../../store/studioStore";
import { useLibraryStore } from "../../store/libraryStore";
import { useDesignStore } from "../../store/designStore";
import { fullUrl } from "../../services/http";
import { openInFreeCAD } from "../../lib/freecadBridge";

/**
 * The document bar.
 *
 * Undo and redo step through the part's own build history — every entry is a
 * solid that was really built, so stepping back restores geometry rather than
 * replaying a command that might not produce the same thing twice. Ctrl+Z,
 * Ctrl+Shift+Z and Ctrl+S are bound, because a CAD tool that ignores them
 * feels like a web page.
 *
 * Save sits in the corner and says which of the two things it will do: create
 * the project, or update the one that is open.
 */

function BarButton({
    icon,
    label,
    onClick,
    disabled,
    active,
    title,
    tone,
}: {
    icon: React.ReactNode;
    label?: string;
    onClick: () => void;
    disabled?: boolean;
    active?: boolean;
    title: string;
    tone?: string;
}) {
    return (
        <button
            onClick={onClick}
            disabled={disabled}
            title={title}
            style={{
                height: "26px",
                padding: label ? "0 9px" : "0 6px",
                display: "flex",
                alignItems: "center",
                gap: "6px",
                background: active ? "var(--st-blue-wash)" : "transparent",
                border: `1px solid ${active ? "var(--st-blue-edge)" : "transparent"}`,
                borderRadius: "5px",
                color: disabled ? "var(--st-pencil)" : tone || (active ? "var(--st-blue)" : "var(--st-graphite)"),
                fontSize: "11.5px",
                fontWeight: 500,
                cursor: disabled ? "default" : "pointer",
                opacity: disabled ? 0.45 : 1,
                flexShrink: 0,
            }}
            onMouseEnter={(e) => {
                if (!disabled && !active) e.currentTarget.style.background = "var(--st-raise)";
            }}
            onMouseLeave={(e) => {
                if (!active) e.currentTarget.style.background = "transparent";
            }}
        >
            {icon}
            {label && <span>{label}</span>}
        </button>
    );
}

function Divider() {
    return <div style={{ width: "1px", height: "18px", background: "var(--st-rule)", flexShrink: 0 }} />;
}

function ExportMenu() {
    const files = useStudioStore((s) => s.part?.files);
    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const close = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
        };
        if (open) document.addEventListener("mousedown", close);
        return () => document.removeEventListener("mousedown", close);
    }, [open]);

    const entries = [
        { ext: "step", url: files?.step, hint: "B-rep · manufacturing" },
        { ext: "stl", url: files?.stl, hint: "mesh · 3D printing" },
        { ext: "glb", url: files?.glb, hint: "mesh · web and AR" },
    ].filter((e) => e.url);

    return (
        <div ref={ref} style={{ position: "relative" }}>
            <BarButton
                icon={<Download size={13} />}
                label="Export"
                onClick={() => setOpen(!open)}
                active={open}
                disabled={entries.length === 0}
                title={entries.length ? "Download this part" : "Build a part first"}
            />
            {open && (
                <div
                    className="of-enter"
                    style={{
                        position: "absolute",
                        top: "32px",
                        right: 0,
                        minWidth: "212px",
                        background: "var(--st-sheet)",
                        border: "1px solid var(--st-rule)",
                        borderRadius: "8px",
                        padding: "5px",
                        zIndex: 400,
                        boxShadow: "var(--st-shadow)",
                    }}
                >
                    {entries.map((e) => (
                        <a
                            key={e.ext}
                            href={fullUrl(e.url)}
                            download
                            onClick={() => setOpen(false)}
                            className="of-row"
                            style={{
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "space-between",
                                padding: "7px 9px",
                                borderRadius: "5px",
                                textDecoration: "none",
                                color: "var(--st-ink)",
                                fontSize: "12px",
                                fontWeight: 600,
                            }}
                        >
                            <span className="of-num">.{e.ext}</span>
                            <span style={{ fontSize: "10.5px", fontWeight: 400, color: "var(--st-pencil)" }}>
                                {e.hint}
                            </span>
                        </a>
                    ))}
                </div>
            )}
        </div>
    );
}

/** Send the current part into a locally running FreeCAD (orion_agent addon). */
function FreeCADButton() {
    const step = useStudioStore((s) => s.part?.files.step);
    const prompt = useStudioStore((s) => s.partPrompt);
    const [state, setState] = useState<"idle" | "busy" | "ok" | "help">("idle");
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const close = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) setState("idle");
        };
        if (state === "help") document.addEventListener("mousedown", close);
        return () => document.removeEventListener("mousedown", close);
    }, [state]);

    if (!step) return null;
    const url = fullUrl(step);

    const handle = async () => {
        if (state === "busy") return;
        setState("busy");
        const res = await openInFreeCAD(url, prompt);
        if (res.status === "opened") {
            setState("ok");
            setTimeout(() => setState("idle"), 2500);
        } else {
            setState("help");
        }
    };

    return (
        <div ref={ref} style={{ position: "relative" }}>
            <BarButton
                icon={state === "busy" ? <Loader2 size={13} className="of-spin" /> : <ExternalLink size={13} />}
                label={state === "ok" ? "Opened" : "FreeCAD"}
                onClick={handle}
                active={state === "help"}
                title="Open this part in a local FreeCAD"
            />
            {state === "help" && (
                <div
                    className="of-enter"
                    style={{
                        position: "absolute",
                        top: "32px",
                        right: 0,
                        width: "266px",
                        background: "var(--st-sheet)",
                        border: "1px solid var(--st-rule)",
                        borderRadius: "8px",
                        padding: "11px 13px",
                        zIndex: 400,
                        boxShadow: "var(--st-shadow)",
                        fontSize: "11.5px",
                        color: "var(--st-graphite)",
                        lineHeight: 1.55,
                    }}
                >
                    <div style={{ fontWeight: 700, color: "var(--st-ink)", marginBottom: "5px" }}>
                        FreeCAD bridge not detected
                    </div>
                    Start FreeCAD with the OrionFlow addon (<code>orion_agent</code>) — the studio
                    connects on <code>127.0.0.1:8765</code> and opens parts side by side.
                    <a
                        href={url}
                        download
                        onClick={() => setState("idle")}
                        style={{ display: "block", marginTop: "9px", color: "var(--st-blue)", fontWeight: 600 }}
                    >
                        Download the .step instead →
                    </a>
                </div>
            )}
        </div>
    );
}

export default function TitleBar() {
    const undo = useStudioStore((s) => s.undo);
    const redo = useStudioStore((s) => s.redo);
    const cursor = useStudioStore((s) => s.cursor);
    const historyLength = useStudioStore((s) => s.history.length);
    const hasPart = useStudioStore((s) => !!s.part);
    const busy = useStudioStore((s) => s.busy);
    const partPrompt = useStudioStore((s) => s.partPrompt);

    const save = useLibraryStore((s) => s.saveCurrent);
    const saving = useLibraryStore((s) => s.saving);
    const savedAt = useLibraryStore((s) => s.savedAt);
    const activeId = useLibraryStore((s) => s.activeId);
    const designs = useLibraryStore((s) => s.designs);

    const isGenerating = useDesignStore((s) => s.isGenerating);

    const canUndo = cursor > 0;
    const canRedo = cursor >= 0 && cursor < historyLength - 1;

    // Shown for a beat after a save so the press has an outcome. Without it a
    // successful save is indistinguishable from a dead button — which is how
    // this one came to be reported as broken in the first place.
    const [flash, setFlash] = useState(false);
    useEffect(() => {
        if (!savedAt) return;
        setFlash(true);
        const t = setTimeout(() => setFlash(false), 2400);
        return () => clearTimeout(t);
    }, [savedAt]);

    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            const mod = e.metaKey || e.ctrlKey;
            if (!mod) return;
            const key = e.key.toLowerCase();
            if (key === "s") {
                e.preventDefault();
                if (hasPart) void save();
            } else if (key === "z" && !e.shiftKey) {
                e.preventDefault();
                undo();
            } else if ((key === "z" && e.shiftKey) || key === "y") {
                e.preventDefault();
                redo();
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [hasPart, save, undo, redo]);

    const project = designs.find((d) => d.id === activeId);
    const title =
        project?.name ||
        (partPrompt ? (partPrompt.length > 72 ? partPrompt.slice(0, 72) + "…" : partPrompt) : "Untitled part");

    return (
        <div
            style={{
                height: "40px",
                flexShrink: 0,
                display: "flex",
                alignItems: "center",
                gap: "6px",
                padding: "0 9px",
                background: "var(--st-sheet)",
                borderBottom: "1px solid var(--st-rule)",
            }}
        >
            <div style={{ display: "flex", alignItems: "center", gap: "7px", flexShrink: 0 }}>
                <OrionFlowLogo size={19} />
                <OrionFlowWordmark size={12.5} />
            </div>

            <Divider />

            <BarButton
                icon={<Undo2 size={14} />}
                onClick={undo}
                disabled={!canUndo}
                title={canUndo ? "Undo — step back a revision (Ctrl+Z)" : "Nothing to undo"}
            />
            <BarButton
                icon={<Redo2 size={14} />}
                onClick={redo}
                disabled={!canRedo}
                title={canRedo ? "Redo — step forward a revision (Ctrl+Shift+Z)" : "Nothing to redo"}
            />

            <Divider />

            {/* The document name, centred and truncating — the only thing here
                that is allowed to take the leftover width. */}
            <div
                style={{
                    flex: 1,
                    minWidth: 0,
                    textAlign: "center",
                    fontSize: "12px",
                    color: "var(--st-graphite)",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    padding: "0 10px",
                }}
                title={partPrompt}
            >
                {isGenerating || busy ? "Working…" : title}
                {activeId && (
                    <span className="of-num" style={{ fontSize: "10px", color: "var(--st-pencil)" }}>
                        {"  ·  saved"}
                    </span>
                )}
            </div>

            <FreeCADButton />
            <ExportMenu />

            <Divider />

            <BarButton
                icon={
                    saving ? (
                        <Loader2 size={13} className="of-spin" />
                    ) : flash ? (
                        <Check size={13} />
                    ) : (
                        <Save size={13} />
                    )
                }
                label={saving ? "Saving" : flash ? "Saved" : activeId ? "Update" : "Save"}
                onClick={() => void save()}
                disabled={!hasPart || saving}
                active={!saving && !flash && hasPart}
                tone={flash ? "var(--st-verify)" : undefined}
                title={
                    hasPart
                        ? activeId
                            ? "Update this project (Ctrl+S)"
                            : "Save this part as a project (Ctrl+S)"
                        : "Build a part first"
                }
            />

            <AccountMenu />
        </div>
    );
}
