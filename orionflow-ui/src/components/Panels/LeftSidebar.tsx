import React, { useState, useRef, useEffect } from "react";
import { useDesignStore } from "../../store/designStore";
import {
    Layers,
    Download,
    ExternalLink,
    Settings,
    X,
    FileDown,
    Box,
    Hexagon,
    ChevronDown
} from "lucide-react";

// ============ Feature Tree Panel ============
function FeatureTreePanel({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
    const current = useDesignStore((s) => s.current);
    const features = current?.featureGraph?.features || [];

    if (!isOpen) return null;

    return (
        <div style={{
            position: "fixed",
            top: 0,
            left: "68px",
            height: "100vh",
            width: "300px",
            background: "var(--slate-900)",
            borderRight: "1px solid var(--color-border)",
            zIndex: 100,
            display: "flex",
            flexDirection: "column",
            animation: "slideInLeft 0.3s var(--ease-out-expo)",
        }}>
            {/* Header */}
            <div style={{
                height: "64px",
                padding: "0 20px",
                borderBottom: "1px solid var(--color-border)",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
            }}>
                <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                    <div style={{
                        width: "32px",
                        height: "32px",
                        borderRadius: "var(--radius-md)",
                        background: "linear-gradient(135deg, var(--copper-500) 0%, var(--copper-400) 100%)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                    }}>
                        <Layers size={16} color="var(--slate-950)" strokeWidth={2.5} />
                    </div>
                    <span style={{ fontWeight: 600, fontSize: "15px", letterSpacing: "-0.01em" }}>
                        Feature Tree
                    </span>
                </div>
                <button
                    onClick={onClose}
                    style={{
                        width: "32px",
                        height: "32px",
                        borderRadius: "var(--radius-md)",
                        background: "var(--color-bg-element)",
                        border: "1px solid var(--color-border)",
                        color: "var(--color-text-muted)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                    }}
                >
                    <X size={14} />
                </button>
            </div>

            {/* Content */}
            <div style={{ flex: 1, overflowY: "auto", padding: "16px" }}>
                {features.length === 0 ? (
                    <div style={{
                        height: "100%",
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        justifyContent: "center",
                        textAlign: "center",
                        padding: "40px 20px",
                    }}>
                        <div style={{
                            width: "64px",
                            height: "64px",
                            borderRadius: "var(--radius-xl)",
                            background: "var(--color-bg-element)",
                            border: "1px solid var(--color-border)",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            marginBottom: "20px",
                        }}>
                            <Box size={28} style={{ color: "var(--color-text-muted)" }} />
                        </div>
                        <p style={{
                            fontSize: "14px",
                            fontWeight: 500,
                            color: "var(--color-text-secondary)",
                            marginBottom: "8px",
                        }}>
                            No features yet
                        </p>
                        <p style={{
                            fontSize: "13px",
                            color: "var(--color-text-muted)",
                            lineHeight: 1.5,
                        }}>
                            Generate a model to see its parametric feature tree
                        </p>
                    </div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                        {features.map((feature: any, index: number) => (
                            <div
                                key={feature.id || index}
                                style={{
                                    padding: "14px 16px",
                                    background: "var(--color-bg-element)",
                                    borderRadius: "var(--radius-md)",
                                    border: "1px solid var(--color-border)",
                                    cursor: "pointer",
                                    transition: "all var(--duration-fast) var(--ease-out-quad)",
                                }}
                                onMouseEnter={(e) => {
                                    e.currentTarget.style.borderColor = "var(--color-border-hover)";
                                    e.currentTarget.style.background = "var(--color-bg-element-hover)";
                                }}
                                onMouseLeave={(e) => {
                                    e.currentTarget.style.borderColor = "var(--color-border)";
                                    e.currentTarget.style.background = "var(--color-bg-element)";
                                }}
                            >
                                <div style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "10px",
                                    marginBottom: feature.params ? "10px" : 0,
                                }}>
                                    <div style={{
                                        width: "8px",
                                        height: "8px",
                                        borderRadius: "var(--radius-full)",
                                        background: index === 0
                                            ? "var(--copper-500)"
                                            : "var(--cyan-500)",
                                        boxShadow: index === 0
                                            ? "0 0 8px var(--copper-glow)"
                                            : "0 0 8px var(--cyan-glow)",
                                    }} />
                                    <span style={{
                                        fontSize: "13px",
                                        fontWeight: 600,
                                        color: "var(--color-text-primary)",
                                        textTransform: "capitalize",
                                    }}>
                                        {feature.type}
                                    </span>
                                    <span style={{
                                        fontSize: "11px",
                                        fontFamily: "var(--font-mono)",
                                        color: "var(--color-text-muted)",
                                        marginLeft: "auto",
                                    }}>
                                        #{index + 1}
                                    </span>
                                </div>
                                {feature.params && (
                                    <div style={{
                                        display: "flex",
                                        flexWrap: "wrap",
                                        gap: "6px",
                                        paddingLeft: "18px",
                                    }}>
                                        {Object.entries(feature.params).slice(0, 4).map(([key, val]) => (
                                            <span
                                                key={key}
                                                style={{
                                                    fontSize: "11px",
                                                    fontFamily: "var(--font-mono)",
                                                    background: "var(--slate-800)",
                                                    padding: "3px 8px",
                                                    borderRadius: "var(--radius-sm)",
                                                    color: "var(--color-text-secondary)",
                                                }}
                                            >
                                                {key}: {String(val)}
                                            </span>
                                        ))}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

// ============ Export Dropdown ============
function ExportDropdown({
    isOpen,
    onClose,
    anchorRef
}: {
    isOpen: boolean;
    onClose: () => void;
    anchorRef: React.RefObject<HTMLButtonElement | null>;
}) {
    const current = useDesignStore((state) => state.current);
    const dropdownRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const handleClickOutside = (e: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node) &&
                anchorRef.current && !anchorRef.current.contains(e.target as Node)) {
                onClose();
            }
        };

        if (isOpen) document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, [isOpen, onClose, anchorRef]);

    if (!isOpen) return null;

    const getDownloadUrl = (format: 'step' | 'stl') => {
        if (!current?.files?.[format]) return null;
        const file = current.files[format];
        if (!file || file === "") return null;
        const filename = file.split(/[/\\]/).pop();
        return `http://127.0.0.1:8000/download/${format}/${filename}`;
    };

    const stepUrl = getDownloadUrl('step');
    const stlUrl = getDownloadUrl('stl');
    const hasFiles = stepUrl || stlUrl;

    const top = anchorRef.current ? anchorRef.current.getBoundingClientRect().top : 150;

    return (
        <div
            ref={dropdownRef}
            style={{
                position: "fixed",
                left: "76px",
                top: `${top}px`,
                background: "var(--slate-900)",
                border: "1px solid var(--color-border)",
                borderRadius: "var(--radius-lg)",
                padding: "8px",
                minWidth: "220px",
                boxShadow: "var(--shadow-lg)",
                zIndex: 200,
                animation: "slideInLeft 0.2s var(--ease-out-expo)",
            }}
        >
            <div style={{
                padding: "10px 12px 8px",
                fontSize: "11px",
                fontWeight: 600,
                color: "var(--color-text-muted)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
            }}>
                Export Format
            </div>

            {!hasFiles ? (
                <div style={{
                    padding: "20px 12px",
                    fontSize: "13px",
                    color: "var(--color-text-muted)",
                    textAlign: "center",
                }}>
                    Generate a model first
                </div>
            ) : (
                <>
                    {stepUrl && (
                        <a
                            href={stepUrl}
                            download
                            onClick={onClose}
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: "14px",
                                padding: "12px 14px",
                                borderRadius: "var(--radius-md)",
                                color: "var(--color-text-primary)",
                                textDecoration: "none",
                                transition: "all var(--duration-fast) var(--ease-out-quad)",
                            }}
                            onMouseEnter={(e) => e.currentTarget.style.background = "var(--color-bg-element)"}
                            onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                        >
                            <div style={{
                                width: "36px",
                                height: "36px",
                                borderRadius: "var(--radius-md)",
                                background: "linear-gradient(135deg, var(--copper-500) 0%, var(--copper-400) 100%)",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                            }}>
                                <FileDown size={18} color="var(--slate-950)" />
                            </div>
                            <div>
                                <div style={{ fontSize: "14px", fontWeight: 600 }}>STEP</div>
                                <div style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "2px" }}>
                                    CAD software compatible
                                </div>
                            </div>
                        </a>
                    )}

                    {stlUrl && (
                        <a
                            href={stlUrl}
                            download
                            onClick={onClose}
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: "14px",
                                padding: "12px 14px",
                                borderRadius: "var(--radius-md)",
                                color: "var(--color-text-primary)",
                                textDecoration: "none",
                                transition: "all var(--duration-fast) var(--ease-out-quad)",
                            }}
                            onMouseEnter={(e) => e.currentTarget.style.background = "var(--color-bg-element)"}
                            onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                        >
                            <div style={{
                                width: "36px",
                                height: "36px",
                                borderRadius: "var(--radius-md)",
                                background: "linear-gradient(135deg, var(--cyan-500) 0%, var(--cyan-400) 100%)",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                            }}>
                                <FileDown size={18} color="var(--slate-950)" />
                            </div>
                            <div>
                                <div style={{ fontSize: "14px", fontWeight: 600 }}>STL</div>
                                <div style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "2px" }}>
                                    3D printing ready
                                </div>
                            </div>
                        </a>
                    )}
                </>
            )}
        </div>
    );
}

// ============ Sidebar Nav Button ============
const NavButton = React.forwardRef<HTMLButtonElement, {
    icon: React.ReactNode;
    label: string;
    onClick: () => void;
    active?: boolean;
    disabled?: boolean;
}>(({ icon, label, onClick, active, disabled }, ref) => (
    <button
        ref={ref}
        onClick={onClick}
        disabled={disabled}
        style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: "6px",
            width: "52px",
            height: "52px",
            background: active ? "var(--color-bg-element)" : "transparent",
            border: active ? "1px solid var(--color-border-hover)" : "1px solid transparent",
            borderRadius: "var(--radius-md)",
            cursor: disabled ? "not-allowed" : "pointer",
            opacity: disabled ? 0.4 : 1,
            color: active ? "var(--color-text-primary)" : "var(--color-text-muted)",
            position: "relative",
            transition: "all var(--duration-fast) var(--ease-out-quad)",
        }}
        onMouseEnter={(e) => {
            if (!disabled && !active) {
                e.currentTarget.style.background = "var(--color-bg-element)";
                e.currentTarget.style.color = "var(--color-text-primary)";
            }
        }}
        onMouseLeave={(e) => {
            if (!active) {
                e.currentTarget.style.background = "transparent";
                e.currentTarget.style.color = "var(--color-text-muted)";
                e.currentTarget.style.borderColor = "transparent";
            }
        }}
        title={label}
    >
        {active && (
            <div style={{
                position: "absolute",
                left: "-8px",
                top: "50%",
                transform: "translateY(-50%)",
                width: "3px",
                height: "20px",
                background: "var(--copper-500)",
                borderRadius: "0 2px 2px 0",
                boxShadow: "0 0 8px var(--copper-glow)",
            }} />
        )}
        {icon}
        <span style={{
            fontSize: "9px",
            fontWeight: 500,
            letterSpacing: "0.02em",
            textTransform: "uppercase",
        }}>
            {label}
        </span>
    </button>
));

// ============ Main Sidebar ============
export default function LeftSidebar() {
    const current = useDesignStore((state) => state.current);
    const [showFeatureTree, setShowFeatureTree] = useState(false);
    const [showExportDropdown, setShowExportDropdown] = useState(false);
    const exportBtnRef = useRef<HTMLButtonElement>(null);

    const handleOpenOnshape = async () => {
        if (!current) return;
        try {
            const response = await fetch(`http://127.0.0.1:8000/api/onshape/create/${current.id}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
            });
            if (response.ok) {
                const data = await response.json();
                if (data.url) window.open(data.url, "_blank");
            }
        } catch (error) {
            console.error("Failed to open in Onshape:", error);
        }
    };

    return (
        <>
            <div style={{
                width: "68px",
                background: "var(--slate-900)",
                borderRight: "1px solid var(--color-border)",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                height: "100%",
                flexShrink: 0,
                zIndex: 30,
                paddingTop: "12px",
            }}>
                {/* Logo */}
                <div style={{
                    width: "44px",
                    height: "44px",
                    borderRadius: "var(--radius-lg)",
                    background: "linear-gradient(135deg, var(--copper-500) 0%, var(--copper-400) 100%)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    marginBottom: "20px",
                    boxShadow: "var(--shadow-glow-accent)",
                    position: "relative",
                }}>
                    <Hexagon size={22} color="var(--slate-950)" strokeWidth={2.5} fill="var(--slate-950)" />
                    <div style={{
                        position: "absolute",
                        inset: "-2px",
                        borderRadius: "var(--radius-lg)",
                        background: "linear-gradient(135deg, var(--copper-400), var(--copper-500))",
                        opacity: 0.4,
                        filter: "blur(8px)",
                        zIndex: -1,
                    }} />
                </div>

                {/* Divider */}
                <div style={{
                    width: "32px",
                    height: "1px",
                    background: "var(--color-border)",
                    marginBottom: "16px",
                }} />

                {/* Nav */}
                <div style={{
                    flex: 1,
                    display: "flex",
                    flexDirection: "column",
                    gap: "4px",
                    padding: "0 8px",
                }}>
                    <NavButton
                        icon={<Layers size={18} strokeWidth={2} />}
                        label="Tree"
                        active={showFeatureTree}
                        onClick={() => setShowFeatureTree(!showFeatureTree)}
                    />

                    <NavButton
                        ref={exportBtnRef}
                        icon={<Download size={18} strokeWidth={2} />}
                        label="Export"
                        active={showExportDropdown}
                        onClick={() => setShowExportDropdown(!showExportDropdown)}
                    />

                    <NavButton
                        icon={<ExternalLink size={18} strokeWidth={2} />}
                        label="Cloud"
                        onClick={handleOpenOnshape}
                        disabled={!current}
                    />
                </div>

                {/* Settings */}
                <div style={{
                    padding: "16px 8px",
                    borderTop: "1px solid var(--color-border)",
                    width: "100%",
                    display: "flex",
                    justifyContent: "center",
                }}>
                    <NavButton
                        icon={<Settings size={18} strokeWidth={2} />}
                        label="Config"
                        onClick={() => {}}
                    />
                </div>
            </div>

            <FeatureTreePanel isOpen={showFeatureTree} onClose={() => setShowFeatureTree(false)} />
            <ExportDropdown isOpen={showExportDropdown} onClose={() => setShowExportDropdown(false)} anchorRef={exportBtnRef} />
        </>
    );
}
