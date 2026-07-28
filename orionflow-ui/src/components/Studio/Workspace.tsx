import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
    Shapes,
    Download,
    LogOut,
    ChevronDown,
    ChevronRight,
    Maximize2,
    Box,
    Grid3x3,
    ExternalLink,
    History,
    User,
} from "lucide-react";
import Viewer from "../Viewer/Viewer";
import OFLCodePanel from "../Panels/OFLCodePanel";
import AssistantPanel from "../Panels/AssistantPanel";
import ProjectTree from "../Panels/ProjectTree";
import VerificationCard from "../Panels/VerificationCard";
import OrionFlowLogo, { OrionFlowWordmark } from "../OrionFlowLogo";
import { useDesignStore } from "../../store/designStore";
import { useOFLStore } from "../../store/oflStore";
import { useAuthStore } from "../../store/authStore";
import { useStudioStore } from "../../store/studioStore";
import { useLibraryStore } from "../../store/libraryStore";
import { fetchExamples, loadExampleIntoStudio, type ExampleEntry } from "../../lib/examples";
import { openInFreeCAD } from "../../lib/freecadBridge";

/* ────────────────────────── Top toolbar ────────────────────────── */

function ToolButton({
    icon,
    label,
    onClick,
    active,
}: {
    icon: React.ReactNode;
    label: string;
    onClick: () => void;
    active?: boolean;
}) {
    return (
        <button
            onClick={onClick}
            title={label}
            style={{
                height: "28px",
                padding: "0 10px",
                display: "flex",
                alignItems: "center",
                gap: "6px",
                background: active ? "var(--studio-accent-dim)" : "transparent",
                border: "1px solid",
                borderColor: active ? "rgba(138, 165, 230,0.4)" : "transparent",
                borderRadius: "6px",
                color: active ? "var(--studio-accent)" : "var(--studio-text-dim)",
                fontSize: "12px",
                fontWeight: 500,
                cursor: "pointer",
                transition: "all 0.12s ease",
            }}
            onMouseEnter={(e) => {
                if (!active) {
                    e.currentTarget.style.background = "var(--studio-panel-2)";
                    e.currentTarget.style.color = "var(--studio-text)";
                }
            }}
            onMouseLeave={(e) => {
                if (!active) {
                    e.currentTarget.style.background = "transparent";
                    e.currentTarget.style.color = "var(--studio-text-dim)";
                }
            }}
        >
            {icon}
            <span>{label}</span>
        </button>
    );
}

function ExportMenu() {
    const current = useDesignStore((s) => s.current);
    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const close = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
        };
        if (open) document.addEventListener("mousedown", close);
        return () => document.removeEventListener("mousedown", close);
    }, [open]);

    const files = current?.files;
    const entries = [
        { ext: "STEP", url: files?.step, hint: "B-rep · manufacturing" },
        { ext: "STL", url: files?.stl, hint: "mesh · 3D printing" },
        { ext: "GLB", url: files?.glb, hint: "mesh · web/AR" },
    ].filter((e) => e.url);

    return (
        <div ref={ref} style={{ position: "relative" }}>
            <ToolButton
                icon={<Download size={13} strokeWidth={2.2} />}
                label="Export"
                onClick={() => setOpen(!open)}
                active={open}
            />
            {open && (
                <div
                    style={{
                        position: "absolute",
                        top: "34px",
                        right: 0,
                        minWidth: "210px",
                        background: "var(--studio-panel-2)",
                        border: "1px solid var(--studio-border)",
                        borderRadius: "8px",
                        padding: "6px",
                        zIndex: 300,
                        boxShadow: "0 12px 32px rgba(0,0,0,0.45)",
                    }}
                >
                    {entries.length === 0 && (
                        <div style={{ padding: "10px 12px", fontSize: "12px", color: "var(--studio-text-faint)" }}>
                            Generate a part first
                        </div>
                    )}
                    {entries.map((e) => (
                        <a
                            key={e.ext}
                            href={e.url}
                            download
                            onClick={() => setOpen(false)}
                            style={{
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "space-between",
                                padding: "8px 10px",
                                borderRadius: "6px",
                                textDecoration: "none",
                                color: "var(--studio-text)",
                                fontSize: "12.5px",
                                fontWeight: 600,
                            }}
                            onMouseEnter={(ev) => (ev.currentTarget.style.background = "var(--studio-accent-dim)")}
                            onMouseLeave={(ev) => (ev.currentTarget.style.background = "transparent")}
                        >
                            <span>.{e.ext.toLowerCase()}</span>
                            <span style={{ fontSize: "11px", fontWeight: 400, color: "var(--studio-text-faint)" }}>
                                {e.hint}
                            </span>
                        </a>
                    ))}
                </div>
            )}
        </div>
    );
}

/** Send the current part into a locally running FreeCAD (orion_agent addon).
 *  Falls back to a setup hint + STEP download when the bridge is offline. */
function FreeCADButton() {
    const current = useDesignStore((s) => s.current);
    const [state, setState] = useState<"idle" | "busy" | "ok" | "help">("idle");
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const close = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) setState("idle");
        };
        if (state === "help") document.addEventListener("mousedown", close);
        return () => document.removeEventListener("mousedown", close);
    }, [state]);

    const stepUrl = current?.files.step;

    const handle = async () => {
        if (!stepUrl || state === "busy") return;
        setState("busy");
        const res = await openInFreeCAD(stepUrl, current!.prompt);
        if (res.status === "opened") {
            setState("ok");
            setTimeout(() => setState("idle"), 2500);
        } else {
            setState("help");
        }
    };

    if (!stepUrl) return null;

    return (
        <div ref={ref} style={{ position: "relative" }}>
            <ToolButton
                icon={<ExternalLink size={13} strokeWidth={2.2} />}
                label={state === "busy" ? "Opening…" : state === "ok" ? "Opened ✓" : "FreeCAD"}
                onClick={handle}
                active={state === "help"}
            />
            {state === "help" && (
                <div
                    style={{
                        position: "absolute",
                        top: "34px",
                        right: 0,
                        width: "270px",
                        background: "var(--studio-panel-2)",
                        border: "1px solid var(--studio-border)",
                        borderRadius: "8px",
                        padding: "12px 14px",
                        zIndex: 300,
                        boxShadow: "0 12px 32px rgba(0,0,0,0.45)",
                        fontSize: "12px",
                        color: "var(--studio-text-dim)",
                        lineHeight: 1.55,
                    }}
                >
                    <div style={{ fontWeight: 700, color: "var(--studio-text)", marginBottom: "6px" }}>
                        FreeCAD bridge not detected
                    </div>
                    Start FreeCAD with the OrionFlow addon (<code>orion_agent</code>) — the studio
                    connects to it on <code>127.0.0.1:8765</code> and opens parts side by side.
                    <a
                        href={stepUrl}
                        download
                        onClick={() => setState("idle")}
                        style={{
                            display: "block",
                            marginTop: "10px",
                            color: "var(--studio-accent)",
                            textDecoration: "none",
                            fontWeight: 600,
                        }}
                    >
                        Download .step instead →
                    </a>
                </div>
            )}
        </div>
    );
}

function TopBar() {
    const current = useDesignStore((s) => s.current);
    const isGenerating = useDesignStore((s) => s.isGenerating);
    const triggerViewAction = useDesignStore((s) => s.triggerViewAction);
    const logout = useAuthStore((s) => s.logout);
    const navigate = useNavigate();

    const title = current
        ? current.prompt.length > 64
            ? current.prompt.slice(0, 64) + "…"
            : current.prompt
        : "Untitled part";

    return (
        <div
            style={{
                height: "44px",
                flexShrink: 0,
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "0 10px",
                background: "var(--studio-panel)",
                borderBottom: "1px solid var(--studio-border)",
            }}
        >
            {/* Studio brand — single, compact, official mark */}
            <div style={{ display: "flex", alignItems: "center", gap: "8px", paddingRight: "10px" }}>
                <OrionFlowLogo size={20} />
                <OrionFlowWordmark size={13} />
                <span
                    style={{
                        fontSize: "9.5px",
                        fontWeight: 700,
                        letterSpacing: "0.12em",
                        color: "var(--studio-accent)",
                        background: "var(--studio-accent-dim)",
                        border: "1px solid rgba(138, 165, 230,0.3)",
                        borderRadius: "4px",
                        padding: "2px 6px",
                    }}
                >
                    STUDIO
                </span>
            </div>

            <div style={{ width: "1px", height: "20px", background: "var(--studio-border)" }} />

            {/* Document title */}
            <div
                style={{
                    flex: 1,
                    minWidth: 0,
                    textAlign: "center",
                    fontSize: "12px",
                    color: "var(--studio-text-dim)",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    padding: "0 12px",
                }}
                title={current?.prompt}
            >
                {isGenerating ? "Generating…" : title}
            </div>

            {/* View + export + session */}
            <ToolButton icon={<Box size={13} strokeWidth={2.2} />} label="Iso" onClick={() => triggerViewAction("iso")} />
            <ToolButton icon={<Grid3x3 size={13} strokeWidth={2.2} />} label="Top" onClick={() => triggerViewAction("ortho")} />
            <ToolButton icon={<Maximize2 size={13} strokeWidth={2.2} />} label="Fit" onClick={() => triggerViewAction("reset")} />
            <div style={{ width: "1px", height: "20px", background: "var(--studio-border)" }} />
            <FreeCADButton />
            <ExportMenu />
            <AccountMenu onSignOut={() => { logout(); navigate("/auth"); }} />
        </div>
    );
}

/** Who is signed in, how much they have saved, and the way out. */
function AccountMenu({ onSignOut }: { onSignOut: () => void }) {
    const user = useAuthStore((s) => s.user);
    const savedCount = useLibraryStore((s) => s.designs.length);
    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const close = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
        };
        if (open) document.addEventListener("mousedown", close);
        return () => document.removeEventListener("mousedown", close);
    }, [open]);

    const initial = (user?.name || user?.email || "?").trim().charAt(0).toUpperCase();

    return (
        <div ref={ref} style={{ position: "relative" }}>
            <button
                onClick={() => setOpen(!open)}
                title={user?.email || "Account"}
                style={{
                    width: "26px",
                    height: "26px",
                    borderRadius: "50%",
                    border: `1px solid ${open ? "var(--studio-accent)" : "var(--studio-border)"}`,
                    background: open ? "var(--studio-accent-dim)" : "var(--studio-panel-2)",
                    color: "var(--studio-text)",
                    fontSize: "11px",
                    fontWeight: 700,
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                }}
            >
                {initial}
            </button>
            {open && (
                <div
                    style={{
                        position: "absolute",
                        top: "34px",
                        right: 0,
                        minWidth: "216px",
                        background: "var(--studio-panel-2)",
                        border: "1px solid var(--studio-border)",
                        borderRadius: "8px",
                        padding: "10px",
                        zIndex: 300,
                        boxShadow: "0 12px 32px rgba(0,0,0,0.45)",
                    }}
                >
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <User size={13} style={{ color: "var(--studio-text-faint)" }} />
                        <div style={{ minWidth: 0 }}>
                            {user?.name && (
                                <div style={{ fontSize: "12.5px", fontWeight: 600, color: "var(--studio-text)" }}>
                                    {user.name}
                                </div>
                            )}
                            <div
                                style={{
                                    fontSize: "11px",
                                    color: "var(--studio-text-faint)",
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                }}
                            >
                                {user?.email || "signed in"}
                            </div>
                        </div>
                    </div>
                    <div
                        style={{
                            margin: "9px 0",
                            paddingTop: "9px",
                            borderTop: "1px solid var(--studio-border)",
                            fontSize: "11.5px",
                            color: "var(--studio-text-dim)",
                        }}
                    >
                        {savedCount} part{savedCount === 1 ? "" : "s"} saved
                    </div>
                    <button
                        onClick={onSignOut}
                        style={{
                            width: "100%",
                            display: "flex",
                            alignItems: "center",
                            gap: "7px",
                            padding: "7px 8px",
                            borderRadius: "6px",
                            border: "none",
                            background: "transparent",
                            color: "var(--studio-text-dim)",
                            fontSize: "12px",
                            fontWeight: 600,
                            cursor: "pointer",
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.background = "var(--studio-panel)")}
                        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                    >
                        <LogOut size={12} />
                        Sign out
                    </button>
                </div>
            )}
        </div>
    );
}

/* ────────────────────────── Left dock ────────────────────────── */

function Section({
    icon,
    title,
    children,
    defaultOpen = true,
}: {
    icon: React.ReactNode;
    title: string;
    children: React.ReactNode;
    defaultOpen?: boolean;
}) {
    const [open, setOpen] = useState(defaultOpen);
    return (
        <div style={{ borderBottom: "1px solid var(--studio-border-soft)" }}>
            <button
                onClick={() => setOpen(!open)}
                style={{
                    width: "100%",
                    display: "flex",
                    alignItems: "center",
                    gap: "7px",
                    padding: "9px 12px",
                    background: "transparent",
                    border: "none",
                    color: "var(--studio-text-dim)",
                    fontSize: "11px",
                    fontWeight: 700,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    cursor: "pointer",
                }}
            >
                {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                {icon}
                {title}
            </button>
            {open && <div style={{ paddingBottom: "8px" }}>{children}</div>}
        </div>
    );
}

function ExamplesList() {
    const [examples, setExamples] = useState<ExampleEntry[]>([]);
    useEffect(() => {
        fetchExamples().then(setExamples).catch(() => {});
    }, []);

    return (
        <div>
            {examples.map((ex) => (
                <button
                    key={ex.id}
                    onClick={() => loadExampleIntoStudio(ex)}
                    style={{
                        width: "100%",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: "8px",
                        padding: "5.5px 14px",
                        background: "transparent",
                        border: "none",
                        color: "var(--studio-text-dim)",
                        fontSize: "12px",
                        textAlign: "left",
                        cursor: "pointer",
                    }}
                    onMouseEnter={(e) => {
                        e.currentTarget.style.background = "var(--studio-panel-2)";
                        e.currentTarget.style.color = "var(--studio-text)";
                    }}
                    onMouseLeave={(e) => {
                        e.currentTarget.style.background = "transparent";
                        e.currentTarget.style.color = "var(--studio-text-dim)";
                    }}
                >
                    <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {ex.title}
                    </span>
                    <span style={{ fontSize: "10px", color: "var(--studio-text-faint)", flexShrink: 0 }}>
                        {ex.category}
                    </span>
                </button>
            ))}
        </div>
    );
}

/** The left dock is the primary surface: the saved-parts list sits above the
 *  assistant, which owns the rest of the height. The assistant is where the
 *  work happens — the derivation, the checks, the conversation — so it gets
 *  the space rather than a 348px strip on the far side of the viewport. */
function LeftDock() {
    return (
        <div
            style={{
                width: "412px",
                flexShrink: 0,
                display: "flex",
                flexDirection: "column",
                background: "var(--studio-panel)",
                borderRight: "1px solid var(--studio-border)",
                minHeight: 0,
            }}
        >
            <div
                className="studio-scroll"
                style={{
                    flexShrink: 0,
                    maxHeight: "30%",
                    overflowY: "auto",
                    borderBottom: "1px solid var(--studio-border)",
                }}
            >
                <ProjectTree />
            </div>
            <div style={{ flex: 1, minHeight: 0 }}>
                <AssistantPanel />
            </div>
        </div>
    );
}

/* ────────────────────────── Right dock ────────────────────────── */

/** Read-only properties of the part currently open: what the model named, what
 *  it committed to, and what the kernel measured. */
function PropertiesPanel() {
    const part = useStudioStore((s) => s.part);
    const partPrompt = useStudioStore((s) => s.partPrompt);

    if (!part) {
        return (
            <div className="studio-scroll" style={{ flex: 1, overflowY: "auto" }}>
                <div style={{ padding: "14px", fontSize: "12px", color: "var(--studio-text-faint)", lineHeight: 1.6 }}>
                    No part open. Describe one in the assistant and its variables,
                    measurements and verification will appear here.
                </div>
                <Section icon={<Shapes size={12} />} title="Examples">
                    <ExamplesList />
                </Section>
            </div>
        );
    }

    const variables = Object.entries(part.variables ?? {});

    return (
        <div className="studio-scroll" style={{ flex: 1, overflowY: "auto", padding: "12px" }}>
            <div style={{ fontSize: "13px", fontWeight: 700, color: "var(--studio-text)" }}>
                {(part.partClass || "part").replace(/_/g, " ")}
            </div>
            {partPrompt && (
                <div style={{ marginTop: "4px", fontSize: "11.5px", color: "var(--studio-text-faint)", lineHeight: 1.5 }}>
                    {partPrompt}
                </div>
            )}

            {variables.length > 0 && (
                <>
                    <div style={sectionLabel}>Variables</div>
                    <div
                        style={{
                            border: "1px solid var(--studio-border)",
                            borderRadius: "7px",
                            overflow: "hidden",
                        }}
                    >
                        {variables.map(([k, v], i) => (
                            <div
                                key={k}
                                style={{
                                    display: "flex",
                                    justifyContent: "space-between",
                                    padding: "5px 9px",
                                    fontFamily: "var(--font-mono)",
                                    fontSize: "11px",
                                    background: i % 2 ? "transparent" : "var(--studio-panel-2)",
                                    color: "var(--studio-text-faint)",
                                }}
                            >
                                <span>{k}</span>
                                <span style={{ color: "var(--studio-text)" }}>{v}</span>
                            </div>
                        ))}
                    </div>
                </>
            )}

            {part.stats && (
                <>
                    <div style={sectionLabel}>Measured</div>
                    <div
                        style={{
                            border: "1px solid var(--studio-border)",
                            borderRadius: "7px",
                            padding: "9px",
                            fontFamily: "var(--font-mono)",
                            fontSize: "11px",
                            color: "var(--studio-text-dim)",
                            lineHeight: 1.7,
                        }}
                    >
                        <div>volume&nbsp;&nbsp;{(part.stats.volume_mm3 / 1000).toFixed(3)} cm³</div>
                        {part.stats.bbox_mm?.length === 3 && (
                            <div>extent&nbsp;&nbsp;{part.stats.bbox_mm.map((v) => v.toFixed(1)).join(" × ")} mm</div>
                        )}
                        <div>solid&nbsp;&nbsp;&nbsp;{part.stats.watertight ? "watertight" : "open mesh"}</div>
                    </div>
                </>
            )}

            {part.verification && (
                <>
                    <div style={sectionLabel}>Verification</div>
                    <VerificationCard report={part.verification} />
                </>
            )}
        </div>
    );
}

const sectionLabel: React.CSSProperties = {
    fontSize: "10px",
    fontWeight: 700,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    color: "var(--studio-text-faint)",
    margin: "14px 0 6px",
};

function RightDock() {
    const [tab, setTab] = useState<"properties" | "code">("properties");
    const oflCode = useOFLStore((s) => s.oflCode);

    return (
        <div
            style={{
                width: "300px",
                flexShrink: 0,
                display: "flex",
                flexDirection: "column",
                background: "var(--studio-panel)",
                borderLeft: "1px solid var(--studio-border)",
                minHeight: 0,
            }}
        >
            <div style={{ display: "flex", borderBottom: "1px solid var(--studio-border)", flexShrink: 0 }}>
                {(
                    [
                        { id: "properties", label: "Properties" },
                        { id: "code", label: `Code${oflCode ? "" : " ·"}` },
                    ] as const
                ).map((t) => (
                    <button
                        key={t.id}
                        onClick={() => setTab(t.id)}
                        style={{
                            flex: 1,
                            padding: "10px 0",
                            background: "transparent",
                            border: "none",
                            borderBottom: `2px solid ${tab === t.id ? "var(--studio-accent)" : "transparent"}`,
                            color: tab === t.id ? "var(--studio-text)" : "var(--studio-text-faint)",
                            fontSize: "12px",
                            fontWeight: 600,
                            cursor: "pointer",
                        }}
                    >
                        {t.label}
                    </button>
                ))}
            </div>
            <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                {tab === "properties" ? <PropertiesPanel /> : <OFLCodePanel />}
            </div>
        </div>
    );
}

/* ────────────────────────── Bottom console ────────────────────────── */

function BottomBar() {
    const isGenerating = useDesignStore((s) => s.isGenerating);
    const error = useOFLStore((s) => s.error);
    const ms = useOFLStore((s) => s.generationTimeMs);

    const dotColor = isGenerating
        ? "var(--studio-warn)"
        : error
          ? "var(--studio-err)"
          : "var(--studio-ok)";
    const statusText = isGenerating ? "Working" : error ? "Error" : "Ready";

    return (
        <div
            style={{
                height: "26px",
                flexShrink: 0,
                display: "flex",
                alignItems: "center",
                gap: "14px",
                padding: "0 12px",
                background: "var(--studio-panel)",
                borderTop: "1px solid var(--studio-border)",
                fontSize: "11px",
                color: "var(--studio-text-faint)",
            }}
        >
            <span style={{ display: "flex", alignItems: "center", gap: "6px", color: "var(--studio-text-dim)" }}>
                <span
                    style={{
                        width: "7px",
                        height: "7px",
                        borderRadius: "50%",
                        background: dotColor,
                        boxShadow: `0 0 6px ${dotColor}`,
                    }}
                />
                {statusText}
            </span>
            {error && (
                <span
                    title={error}
                    style={{
                        color: "var(--studio-err)",
                        maxWidth: "44%",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                    }}
                >
                    {error}
                </span>
            )}
            {ms > 0 && !isGenerating && <span>built in {(ms / 1000).toFixed(1)}s</span>}
            <span style={{ marginLeft: "auto", display: "flex", gap: "14px", alignItems: "center" }}>
                <span>mm · centered origin</span>
            </span>
        </div>
    );
}

/* ────────────────────────── Version timeline ────────────────────────── */

/** Every successful generate/edit snapshots a version; clicking a chip
 *  restores that geometry + code — a linear history like CAD undo states. */
function VersionStrip() {
    const current = useDesignStore((s) => s.current);
    const activateVersion = useDesignStore((s) => s.activateVersion);

    const versions = current?.versions;
    if (!current || !versions || versions.length < 2) return null;

    const active = current.activeVersion ?? versions.length - 1;

    return (
        <div
            style={{
                position: "absolute",
                bottom: "12px",
                left: "50%",
                transform: "translateX(-50%)",
                display: "flex",
                alignItems: "center",
                gap: "6px",
                padding: "5px 10px",
                background: "rgba(26, 28, 32, 0.92)",
                backdropFilter: "blur(8px)",
                border: "1px solid var(--studio-border)",
                borderRadius: "999px",
                zIndex: 30,
                maxWidth: "70%",
                overflowX: "auto",
            }}
        >
            <History size={12} style={{ color: "var(--studio-text-faint)", flexShrink: 0 }} />
            {versions.map((v, i) => (
                <button
                    key={i}
                    onClick={() => activateVersion(current.id, i)}
                    title={`${v.label} · ${new Date(v.timestamp).toLocaleTimeString()}`}
                    style={{
                        flexShrink: 0,
                        padding: "3px 10px",
                        borderRadius: "999px",
                        border: "1px solid",
                        borderColor: i === active ? "rgba(138, 165, 230,0.5)" : "transparent",
                        background: i === active ? "var(--studio-accent-dim)" : "transparent",
                        color: i === active ? "var(--studio-accent)" : "var(--studio-text-dim)",
                        fontSize: "11px",
                        fontWeight: 600,
                        cursor: "pointer",
                        whiteSpace: "nowrap",
                    }}
                >
                    v{i + 1}
                </button>
            ))}
        </div>
    );
}

/* ────────────────────────── Workspace ────────────────────────── */

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
                background: "var(--studio-bg)",
                color: "var(--studio-text)",
            }}
        >
            <TopBar />
            <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
                <LeftDock />
                <div style={{ flex: 1, position: "relative", minWidth: 0 }}>
                    <Viewer url={current ? current.files.glb : ""} />
                    <VersionStrip />
                </div>
                <RightDock />
            </div>
            <BottomBar />
        </div>
    );
}
