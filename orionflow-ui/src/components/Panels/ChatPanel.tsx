import { useState, useRef, useEffect } from "react";
import { useDesignStore } from "../../store/designStore";
import { useChatStore } from "../../store/chatStore";
import {
    X,
    Box,
    ArrowUp,
    Paperclip,
    Sparkles,
    ChevronDown,
    Hexagon
} from "lucide-react";

interface ChatPanelProps {
    onGenerate: (prompt: string, image?: File) => void;
}

// Unit selector component
function UnitSelector({ value, onChange }: { value: string; onChange: (v: string) => void }) {
    const [isOpen, setIsOpen] = useState(false);
    const units = ["mm", "cm", "in"];

    return (
        <div style={{ position: "relative" }}>
            <button
                onClick={() => setIsOpen(!isOpen)}
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "4px",
                    padding: "6px 10px",
                    background: "var(--color-bg-element)",
                    border: "1px solid var(--color-border)",
                    borderRadius: "var(--radius-sm)",
                    color: "var(--color-text-secondary)",
                    fontSize: "12px",
                    fontFamily: "var(--font-mono)",
                    fontWeight: 500,
                }}
            >
                {value}
                <ChevronDown size={12} />
            </button>

            {isOpen && (
                <div style={{
                    position: "absolute",
                    bottom: "100%",
                    right: 0,
                    marginBottom: "4px",
                    background: "var(--slate-850)",
                    border: "1px solid var(--color-border)",
                    borderRadius: "var(--radius-md)",
                    padding: "4px",
                    minWidth: "70px",
                    boxShadow: "var(--shadow-lg)",
                    zIndex: 100,
                    animation: "slideInUp 0.15s var(--ease-out-expo)",
                }}>
                    {units.map((unit) => (
                        <button
                            key={unit}
                            onClick={() => {
                                onChange(unit);
                                setIsOpen(false);
                            }}
                            style={{
                                display: "block",
                                width: "100%",
                                padding: "8px 12px",
                                background: value === unit ? "var(--color-bg-element)" : "transparent",
                                border: "none",
                                borderRadius: "var(--radius-sm)",
                                color: value === unit ? "var(--color-text-primary)" : "var(--color-text-secondary)",
                                fontSize: "12px",
                                fontFamily: "var(--font-mono)",
                                textAlign: "left",
                                cursor: "pointer",
                            }}
                        >
                            {unit}
                            {value === unit && (
                                <span style={{ float: "right", color: "var(--copper-500)" }}>✓</span>
                            )}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

export default function ChatPanel({ onGenerate }: ChatPanelProps) {
    const current = useDesignStore((state) => state.current);
    const isGenerating = useDesignStore((state) => state.isGenerating);
    const conversations = useChatStore((state) => state.conversations);
    const chatHistory = current ? (conversations.get(current.id) || []) : [];

    const [inputValue, setInputValue] = useState("");
    const [selectedImage, setSelectedImage] = useState<File | null>(null);
    const [imagePreview, setImagePreview] = useState<string | null>(null);
    const [unit, setUnit] = useState("mm");

    const scrollRef = useRef<HTMLDivElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [chatHistory, isGenerating]);

    const handleSend = () => {
        if ((!inputValue.trim() && !selectedImage) || isGenerating) return;
        onGenerate(inputValue, selectedImage || undefined);
        setInputValue("");
        setSelectedImage(null);
        setImagePreview(null);
    };

    const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        if (file.size > 3 * 1024 * 1024) {
            alert("Image must be less than 3MB");
            return;
        }
        setSelectedImage(file);
        setImagePreview(URL.createObjectURL(file));
    };

    const removeImage = () => {
        setSelectedImage(null);
        if (imagePreview) {
            URL.revokeObjectURL(imagePreview);
            setImagePreview(null);
        }
    };

    const canSend = (inputValue.trim() || selectedImage) && !isGenerating;

    return (
        <div style={{
            width: "400px",
            background: "var(--slate-950)",
            borderLeft: "1px solid var(--color-border)",
            display: "flex",
            flexDirection: "column",
            height: "100%",
            flexShrink: 0,
            position: "relative",
        }}>
            {/* Header */}
            <div style={{
                padding: "16px 20px",
                borderBottom: "1px solid var(--color-border)",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                background: "var(--slate-900)",
            }}>
                <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                    <div style={{
                        width: "36px",
                        height: "36px",
                        borderRadius: "var(--radius-md)",
                        background: "linear-gradient(135deg, var(--copper-500) 0%, var(--copper-400) 100%)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        boxShadow: "0 0 16px var(--copper-glow)",
                    }}>
                        <Hexagon size={18} color="var(--slate-950)" strokeWidth={2.5} fill="var(--slate-950)" />
                    </div>
                    <div>
                        <div style={{
                            fontSize: "15px",
                            fontWeight: 700,
                            letterSpacing: "-0.02em",
                            display: "flex",
                            alignItems: "center",
                            gap: "6px",
                        }}>
                            <span style={{ color: "var(--color-text-primary)" }}>Orion</span>
                            <span style={{ color: "var(--copper-400)" }}>Flow</span>
                        </div>
                        <div style={{
                            fontSize: "11px",
                            color: "var(--color-text-muted)",
                            fontWeight: 500,
                            marginTop: "2px",
                        }}>
                            AI-Powered CAD
                        </div>
                    </div>
                </div>
                <div style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    padding: "6px 12px",
                    background: "var(--color-bg-element)",
                    borderRadius: "var(--radius-full)",
                    border: "1px solid var(--color-border)",
                }}>
                    <div style={{
                        width: "6px",
                        height: "6px",
                        borderRadius: "var(--radius-full)",
                        background: "#22c55e",
                        boxShadow: "0 0 8px rgba(34, 197, 94, 0.5)",
                    }} />
                    <span style={{
                        fontSize: "11px",
                        fontWeight: 500,
                        color: "var(--color-text-secondary)",
                    }}>
                        Online
                    </span>
                </div>
            </div>

            {/* Messages */}
            <div
                ref={scrollRef}
                style={{
                    flex: 1,
                    overflowY: "auto",
                    padding: "20px",
                }}
            >
                {chatHistory.length === 0 && !isGenerating ? (
                    <div style={{
                        height: "100%",
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        justifyContent: "center",
                        gap: "24px",
                        textAlign: "center",
                        padding: "20px",
                    }}>
                        {/* Hero Icon */}
                        <div style={{
                            width: "80px",
                            height: "80px",
                            borderRadius: "var(--radius-2xl)",
                            background: "linear-gradient(135deg, var(--slate-800) 0%, var(--slate-850) 100%)",
                            border: "1px solid var(--color-border)",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            position: "relative",
                        }}>
                            <Sparkles size={32} style={{ color: "var(--copper-400)" }} />
                            <div style={{
                                position: "absolute",
                                inset: "-1px",
                                borderRadius: "var(--radius-2xl)",
                                background: "linear-gradient(135deg, var(--copper-500), transparent)",
                                opacity: 0.1,
                                pointerEvents: "none",
                            }} />
                        </div>

                        <div>
                            <p style={{
                                fontSize: "16px",
                                fontWeight: 600,
                                color: "var(--color-text-primary)",
                                marginBottom: "8px",
                            }}>
                                What would you like to create?
                            </p>
                            <p style={{
                                fontSize: "13px",
                                color: "var(--color-text-muted)",
                                lineHeight: 1.6,
                                maxWidth: "280px",
                            }}>
                                Describe your CAD model in natural language and I'll generate it for you
                            </p>
                        </div>

                        {/* Quick Prompts */}
                        <div style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: "8px",
                            width: "100%",
                        }}>
                            {[
                                "Create a 20mm cube with filleted edges",
                                "Cylinder with 15mm radius, 30mm height",
                                "L-bracket with mounting holes"
                            ].map((prompt, i) => (
                                <button
                                    key={prompt}
                                    onClick={() => setInputValue(prompt)}
                                    style={{
                                        padding: "14px 16px",
                                        background: "var(--slate-900)",
                                        border: "1px solid var(--color-border)",
                                        borderRadius: "var(--radius-md)",
                                        color: "var(--color-text-secondary)",
                                        fontSize: "13px",
                                        textAlign: "left",
                                        cursor: "pointer",
                                        transition: "all var(--duration-fast) var(--ease-out-quad)",
                                        display: "flex",
                                        alignItems: "center",
                                        gap: "12px",
                                        animation: `slideInUp 0.3s var(--ease-out-expo) ${i * 0.05}s both`,
                                    }}
                                    onMouseEnter={(e) => {
                                        e.currentTarget.style.borderColor = "var(--copper-500)";
                                        e.currentTarget.style.color = "var(--color-text-primary)";
                                        e.currentTarget.style.background = "var(--slate-850)";
                                    }}
                                    onMouseLeave={(e) => {
                                        e.currentTarget.style.borderColor = "var(--color-border)";
                                        e.currentTarget.style.color = "var(--color-text-secondary)";
                                        e.currentTarget.style.background = "var(--slate-900)";
                                    }}
                                >
                                    <Box size={16} style={{ color: "var(--copper-400)", flexShrink: 0 }} />
                                    {prompt}
                                </button>
                            ))}
                        </div>
                    </div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
                        {chatHistory.map((msg, i) => (
                            <div
                                key={msg.id}
                                style={{
                                    animation: `slideInUp 0.3s var(--ease-out-expo) ${i * 0.03}s both`,
                                }}
                            >
                                {/* Role Badge */}
                                <div style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "8px",
                                    marginBottom: "10px",
                                }}>
                                    <div style={{
                                        width: "24px",
                                        height: "24px",
                                        borderRadius: "var(--radius-sm)",
                                        background: msg.role === "user"
                                            ? "var(--slate-700)"
                                            : "linear-gradient(135deg, var(--copper-500), var(--copper-400))",
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                    }}>
                                        {msg.role === "user" ? (
                                            <span style={{ fontSize: "11px", fontWeight: 600 }}>U</span>
                                        ) : (
                                            <Hexagon size={12} color="var(--slate-950)" fill="var(--slate-950)" />
                                        )}
                                    </div>
                                    <span style={{
                                        fontSize: "12px",
                                        fontWeight: 600,
                                        color: msg.role === "user" ? "var(--color-text-muted)" : "var(--copper-400)",
                                        textTransform: "uppercase",
                                        letterSpacing: "0.05em",
                                    }}>
                                        {msg.role === "user" ? "You" : "OrionFlow"}
                                    </span>
                                </div>

                                {/* Image */}
                                {msg.image && (
                                    <img
                                        src={msg.image}
                                        alt="Uploaded"
                                        style={{
                                            maxWidth: "200px",
                                            borderRadius: "var(--radius-md)",
                                            marginBottom: "12px",
                                            border: "1px solid var(--color-border)",
                                        }}
                                    />
                                )}

                                {/* Message */}
                                <p style={{
                                    fontSize: "14px",
                                    lineHeight: 1.7,
                                    color: "var(--color-text-primary)",
                                    margin: 0,
                                    paddingLeft: "32px",
                                }}>
                                    {msg.content}
                                </p>

                                {/* Model Version Badge */}
                                {msg.partVersion && (
                                    <div style={{
                                        marginTop: "12px",
                                        marginLeft: "32px",
                                        padding: "10px 14px",
                                        background: "linear-gradient(135deg, rgba(245, 158, 11, 0.1), rgba(245, 158, 11, 0.05))",
                                        border: "1px solid rgba(245, 158, 11, 0.3)",
                                        borderRadius: "var(--radius-md)",
                                        display: "inline-flex",
                                        alignItems: "center",
                                        gap: "10px",
                                    }}>
                                        <Box size={16} style={{ color: "var(--copper-400)" }} />
                                        <span style={{
                                            fontSize: "13px",
                                            fontWeight: 600,
                                            color: "var(--copper-400)",
                                        }}>
                                            Model v{msg.partVersion} ready
                                        </span>
                                    </div>
                                )}
                            </div>
                        ))}

                        {/* Loading State */}
                        {isGenerating && (
                            <div style={{ animation: "slideInUp 0.3s var(--ease-out-expo)" }}>
                                <div style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "8px",
                                    marginBottom: "10px",
                                }}>
                                    <div style={{
                                        width: "24px",
                                        height: "24px",
                                        borderRadius: "var(--radius-sm)",
                                        background: "linear-gradient(135deg, var(--copper-500), var(--copper-400))",
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                    }}>
                                        <Hexagon size={12} color="var(--slate-950)" fill="var(--slate-950)" />
                                    </div>
                                    <span style={{
                                        fontSize: "12px",
                                        fontWeight: 600,
                                        color: "var(--copper-400)",
                                        textTransform: "uppercase",
                                        letterSpacing: "0.05em",
                                    }}>
                                        OrionFlow
                                    </span>
                                </div>

                                <div style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "12px",
                                    paddingLeft: "32px",
                                }}>
                                    <div style={{ display: "flex", gap: "4px" }}>
                                        {[0, 1, 2].map((i) => (
                                            <div
                                                key={i}
                                                style={{
                                                    width: "8px",
                                                    height: "8px",
                                                    borderRadius: "var(--radius-full)",
                                                    background: "var(--copper-500)",
                                                    animation: `pulse 1.4s ease-in-out ${i * 0.15}s infinite`,
                                                }}
                                            />
                                        ))}
                                    </div>
                                    <span style={{
                                        fontSize: "14px",
                                        color: "var(--color-text-muted)",
                                    }}>
                                        Generating geometry...
                                    </span>
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Input Area */}
            <div style={{
                padding: "16px 20px",
                borderTop: "1px solid var(--color-border)",
                background: "var(--slate-900)",
            }}>
                {/* Image Preview */}
                {imagePreview && (
                    <div style={{
                        position: "relative",
                        display: "inline-block",
                        marginBottom: "12px",
                    }}>
                        <img
                            src={imagePreview}
                            alt="Preview"
                            style={{
                                height: "64px",
                                borderRadius: "var(--radius-md)",
                                objectFit: "cover",
                                border: "1px solid var(--color-border)",
                            }}
                        />
                        <button
                            onClick={removeImage}
                            style={{
                                position: "absolute",
                                top: "-6px",
                                right: "-6px",
                                width: "20px",
                                height: "20px",
                                borderRadius: "var(--radius-full)",
                                background: "var(--slate-800)",
                                border: "1px solid var(--color-border)",
                                color: "var(--color-text-muted)",
                                padding: 0,
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                            }}
                        >
                            <X size={10} />
                        </button>
                    </div>
                )}

                {/* Input Container */}
                <div style={{
                    display: "flex",
                    alignItems: "flex-end",
                    gap: "10px",
                    background: "var(--slate-850)",
                    border: "1px solid var(--color-border)",
                    borderRadius: "var(--radius-lg)",
                    padding: "10px 12px",
                    transition: "all var(--duration-fast) var(--ease-out-quad)",
                }}>
                    {/* Image Upload */}
                    <input
                        type="file"
                        ref={fileInputRef}
                        style={{ display: "none" }}
                        accept="image/*"
                        onChange={handleImageSelect}
                    />
                    <button
                        onClick={() => fileInputRef.current?.click()}
                        disabled={isGenerating}
                        style={{
                            width: "36px",
                            height: "36px",
                            borderRadius: "var(--radius-md)",
                            background: "var(--slate-800)",
                            border: "1px solid var(--color-border)",
                            color: "var(--color-text-muted)",
                            flexShrink: 0,
                            opacity: isGenerating ? 0.5 : 1,
                        }}
                        title="Attach reference image"
                    >
                        <Paperclip size={16} />
                    </button>

                    {/* Text Input */}
                    <input
                        type="text"
                        placeholder="Describe your CAD model..."
                        value={inputValue}
                        onChange={(e) => setInputValue(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleSend()}
                        disabled={isGenerating}
                        style={{
                            flex: 1,
                            background: "transparent",
                            border: "none",
                            outline: "none",
                            color: "var(--color-text-primary)",
                            fontSize: "14px",
                            padding: "8px 0",
                        }}
                    />

                    {/* Unit Selector */}
                    <UnitSelector value={unit} onChange={setUnit} />

                    {/* Send Button */}
                    <button
                        onClick={handleSend}
                        disabled={!canSend}
                        style={{
                            width: "36px",
                            height: "36px",
                            borderRadius: "var(--radius-md)",
                            background: canSend
                                ? "linear-gradient(135deg, var(--copper-500) 0%, var(--copper-400) 100%)"
                                : "var(--slate-800)",
                            border: "none",
                            color: canSend ? "var(--slate-950)" : "var(--color-text-muted)",
                            flexShrink: 0,
                            boxShadow: canSend ? "0 0 20px var(--copper-glow)" : "none",
                        }}
                    >
                        <ArrowUp size={18} strokeWidth={2.5} />
                    </button>
                </div>

                {/* Hint */}
                <div style={{
                    marginTop: "10px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "6px",
                }}>
                    <span style={{
                        fontSize: "11px",
                        color: "var(--color-text-muted)",
                    }}>
                        Press <kbd style={{
                            background: "var(--slate-800)",
                            padding: "2px 6px",
                            borderRadius: "var(--radius-sm)",
                            fontSize: "10px",
                            fontFamily: "var(--font-mono)",
                        }}>Enter</kbd> to send
                    </span>
                </div>
            </div>
        </div>
    );
}
