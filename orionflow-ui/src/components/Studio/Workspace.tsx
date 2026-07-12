import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
    Layers,
    Shapes,
    Download,
    LogOut,
    ChevronDown,
    ChevronRight,
    Maximize2,
    Box,
    Command,
    ArrowUp,
    Grid3x3,
} from "lucide-react";
import Viewer from "../Viewer/Viewer";
import ChatPanel from "../Panels/ChatPanel";
import OFLCodePanel from "../Panels/OFLCodePanel";
import OrionFlowLogo from "../OrionFlowLogo";
import { useDesignStore } from "../../store/designStore";
import { useOFLStore } from "../../store/oflStore";
import { useAuthStore } from "../../store/authStore";
import { fetchExamples, loadExampleIntoStudio, type ExampleEntry } from "../../lib/examples";

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
                borderColor: active ? "rgba(79,140,255,0.4)" : "transparent",
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
            {/* Studio brand — single, compact */}
            <div style={{ display: "flex", alignItems: "center", gap: "8px", paddingRight: "10px" }}>
                <OrionFlowLogo size={20} />
                <span style={{ fontSize: "13px", fontWeight: 700, letterSpacing: "-0.01em", color: "var(--studio-text)" }}>
                    OrionFlow
                </span>
                <span
                    style={{
                        fontSize: "9.5px",
                        fontWeight: 700,
                        letterSpacing: "0.12em",
                        color: "var(--studio-accent)",
                        background: "var(--studio-accent-dim)",
                        border: "1px solid rgba(79,140,255,0.3)",
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
            <ExportMenu />
            <ToolButton
                icon={<LogOut size={13} strokeWidth={2.2} />}
                label="Sign out"
                onClick={() => {
                    logout();
                    navigate("/auth");
                }}
            />
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

function ModelTree() {
    const current = useDesignStore((s) => s.current);
    const creations = useDesignStore((s) => s.creations);
    const setCurrent = useDesignStore((s) => s.setCurrent);
    const parameters = useOFLStore((s) => s.parameters);

    return (
        <div>
            {creations.length === 0 && (
                <div style={{ padding: "4px 14px 8px", fontSize: "12px", color: "var(--studio-text-faint)" }}>
                    No parts yet — describe one below.
                </div>
            )}
            {creations.map((c) => {
                const active = current?.id === c.id;
                return (
                    <div key={c.id}>
                        <button
                            onClick={() => setCurrent(c.id)}
                            style={{
                                width: "100%",
                                display: "flex",
                                alignItems: "center",
                                gap: "8px",
                                padding: "6px 14px",
                                background: active ? "var(--studio-accent-dim)" : "transparent",
                                border: "none",
                                borderLeft: `2px solid ${active ? "var(--studio-accent)" : "transparent"}`,
                                color: active ? "var(--studio-text)" : "var(--studio-text-dim)",
                                fontSize: "12px",
                                textAlign: "left",
                                cursor: "pointer",
                                whiteSpace: "nowrap",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                            }}
                            title={c.prompt}
                        >
                            <Box size={13} strokeWidth={2} style={{ flexShrink: 0 }} />
                            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                                {c.prompt.slice(0, 42) || "Untitled"}
                            </span>
                        </button>
                        {active && parameters.length > 0 && (
                            <div style={{ padding: "2px 0 4px 34px" }}>
                                {parameters.map((p) => (
                                    <div
                                        key={p.name}
                                        style={{
                                            display: "flex",
                                            justifyContent: "space-between",
                                            padding: "2.5px 12px 2.5px 0",
                                            fontSize: "11px",
                                            fontFamily: "var(--font-mono)",
                                            color: "var(--studio-text-faint)",
                                        }}
                                    >
                                        <span>{p.name}</span>
                                        <span style={{ color: "var(--studio-text-dim)" }}>{p.value}</span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                );
            })}
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

function LeftDock() {
    return (
        <div
            className="studio-scroll"
            style={{
                width: "232px",
                flexShrink: 0,
                background: "var(--studio-panel)",
                borderRight: "1px solid var(--studio-border)",
                overflowY: "auto",
            }}
        >
            <Section icon={<Layers size={12} />} title="Model">
                <ModelTree />
            </Section>
            <Section icon={<Shapes size={12} />} title="Examples" defaultOpen={false}>
                <ExamplesList />
            </Section>
        </div>
    );
}

/* ────────────────────────── Right dock ────────────────────────── */

function RightDock({ onGenerate }: { onGenerate: (prompt: string) => void }) {
    const [tab, setTab] = useState<"copilot" | "code">("copilot");
    const oflCode = useOFLStore((s) => s.oflCode);

    return (
        <div
            style={{
                width: "348px",
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
                        { id: "copilot", label: "Copilot" },
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
                {tab === "copilot" ? (
                    <ChatPanel onGenerate={onGenerate} />
                ) : (
                    <OFLCodePanel />
                )}
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
                <span>K2 Think · Groq fallback</span>
                <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                    <Command size={10} />K to command
                </span>
            </span>
        </div>
    );
}

/* ────────────────────────── Command bar (empty state) ────────────────────────── */

const STARTERS = [
    "NEMA 17 motor mount, 6 mm plate",
    "Flange, 100 mm OD, 6× M8 on 75 PCD",
    "Enclosure 100×64×25, 2.5 mm walls",
];

function CommandBar() {
    const [value, setValue] = useState("");
    const inputRef = useRef<HTMLInputElement>(null);
    const isGenerating = useDesignStore((s) => s.isGenerating);

    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
                e.preventDefault();
                inputRef.current?.focus();
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, []);

    const submit = () => {
        if (!value.trim() || isGenerating) return;
        window.dispatchEvent(new CustomEvent("generate-request", { detail: { prompt: value } }));
        setValue("");
    };

    return (
        <div
            style={{
                position: "absolute",
                inset: 0,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                zIndex: 40,
                pointerEvents: "none",
            }}
        >
            <div style={{ pointerEvents: "auto", width: "min(560px, 82%)" }}>
                <div
                    style={{
                        fontSize: "13px",
                        fontWeight: 600,
                        color: "var(--studio-text-dim)",
                        textAlign: "center",
                        marginBottom: "14px",
                        letterSpacing: "0.01em",
                    }}
                >
                    Describe a part to machine it into existence
                </div>
                <div
                    style={{
                        display: "flex",
                        alignItems: "center",
                        background: "rgba(26, 28, 32, 0.92)",
                        backdropFilter: "blur(8px)",
                        border: "1px solid var(--studio-border)",
                        borderRadius: "10px",
                        padding: "4px 4px 4px 14px",
                        boxShadow: "0 16px 48px rgba(0,0,0,0.5)",
                    }}
                >
                    <input
                        ref={inputRef}
                        id="of-command-input"
                        value={value}
                        onChange={(e) => setValue(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && submit()}
                        placeholder="Mounting plate 120×80×6 with four M5 corner holes…"
                        autoFocus
                        style={{
                            flex: 1,
                            background: "transparent",
                            border: "none",
                            outline: "none",
                            color: "var(--studio-text)",
                            fontSize: "13.5px",
                            padding: "10px 0",
                        }}
                    />
                    <button
                        onClick={submit}
                        disabled={!value.trim() || isGenerating}
                        style={{
                            width: "36px",
                            height: "36px",
                            borderRadius: "7px",
                            border: "none",
                            background: value.trim() ? "var(--studio-accent)" : "var(--studio-panel-2)",
                            color: value.trim() ? "#fff" : "var(--studio-text-faint)",
                            cursor: value.trim() ? "pointer" : "default",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                        }}
                    >
                        <ArrowUp size={16} />
                    </button>
                </div>
                <div style={{ display: "flex", gap: "8px", justifyContent: "center", marginTop: "14px", flexWrap: "wrap" }}>
                    {STARTERS.map((s) => (
                        <button
                            key={s}
                            onClick={() => setValue(s)}
                            style={{
                                fontSize: "11px",
                                color: "var(--studio-text-dim)",
                                background: "rgba(32, 35, 41, 0.85)",
                                border: "1px solid var(--studio-border-soft)",
                                borderRadius: "999px",
                                padding: "5px 12px",
                                cursor: "pointer",
                            }}
                            onMouseEnter={(e) => (e.currentTarget.style.color = "var(--studio-text)")}
                            onMouseLeave={(e) => (e.currentTarget.style.color = "var(--studio-text-dim)")}
                        >
                            {s}
                        </button>
                    ))}
                </div>
            </div>
        </div>
    );
}

/* ────────────────────────── Workspace ────────────────────────── */

export default function Workspace({ onGenerate }: { onGenerate: (prompt: string) => void }) {
    const current = useDesignStore((s) => s.current);
    const isGenerating = useDesignStore((s) => s.isGenerating);

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
                    {!current && !isGenerating && <CommandBar />}
                </div>
                <RightDock onGenerate={onGenerate} />
            </div>
            <BottomBar />
        </div>
    );
}
