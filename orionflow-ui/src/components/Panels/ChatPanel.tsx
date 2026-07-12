import { useState, useRef, useEffect } from "react";
import { useDesignStore } from "../../store/designStore";
import { useChatStore } from "../../store/chatStore";
import { Box, ArrowUp } from "lucide-react";
import OrionFlowLogo from "../OrionFlowLogo";

interface ChatPanelProps {
    onGenerate: (prompt: string, image?: File) => void;
}

export default function ChatPanel({ onGenerate }: ChatPanelProps) {
    const current = useDesignStore((state) => state.current);
    const isGenerating = useDesignStore((state) => state.isGenerating);
    const conversations = useChatStore((state) => state.conversations);
    const chatHistory = current ? (conversations.get(current.id) || []) : [];

    const [inputValue, setInputValue] = useState("");

    const scrollRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [chatHistory, isGenerating]);

    // Auto-resize textarea
    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = "24px";
            textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + "px";
        }
    }, [inputValue]);

    const handleSend = () => {
        if (!inputValue.trim() || isGenerating) return;
        onGenerate(inputValue);
        setInputValue("");
    };

    const canSend = inputValue.trim() && !isGenerating;

    return (
        <div style={{
            width: "400px",
            background: "#0a0a0a",
            borderLeft: "1px solid #1f1f1f",
            display: "flex",
            flexDirection: "column",
            height: "100%",
            flexShrink: 0,
        }}>
            {/* Header */}
            <div style={{
                padding: "16px 20px",
                borderBottom: "1px solid #1f1f1f",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
            }}>
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <div style={{
                        width: "32px",
                        height: "32px",
                        borderRadius: "8px",
                        background: "linear-gradient(135deg, #3b82f6, #6366f1)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                    }}>
                        <OrionFlowLogo size={18} theme="mono" />
                    </div>
                    <span style={{
                        fontSize: "15px",
                        fontWeight: 600,
                        color: "#fff",
                    }}>
                        OrionFlow
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
                        textAlign: "center",
                        padding: "40px 20px",
                    }}>
                        <div style={{
                            width: "56px",
                            height: "56px",
                            borderRadius: "14px",
                            background: "linear-gradient(135deg, #3b82f6, #6366f1)",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            marginBottom: "20px",
                        }}>
                            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.5">
                                <path d="M12 2L2 7l10 5 10-5-10-5z" />
                                <path d="M2 17l10 5 10-5" />
                                <path d="M2 12l10 5 10-5" />
                            </svg>
                        </div>
                        <p style={{
                            fontSize: "16px",
                            fontWeight: 500,
                            color: "#fff",
                            marginBottom: "8px",
                        }}>
                            How can I help you?
                        </p>
                        <p style={{
                            fontSize: "14px",
                            color: "#71717a",
                            lineHeight: 1.5,
                        }}>
                            Describe a CAD model to generate
                        </p>
                    </div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
                        {chatHistory.map((msg) => (
                            <div key={msg.id}>
                                {/* Role */}
                                <div style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "8px",
                                    marginBottom: "8px",
                                }}>
                                    <div style={{
                                        width: "24px",
                                        height: "24px",
                                        borderRadius: "6px",
                                        background: msg.role === "user" ? "#27272a" : "linear-gradient(135deg, #3b82f6, #6366f1)",
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                    }}>
                                        {msg.role === "user" ? (
                                            <span style={{ fontSize: "11px", fontWeight: 600, color: "#a1a1aa" }}>Y</span>
                                        ) : (
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2">
                                                <path d="M12 2L2 7l10 5 10-5-10-5z" />
                                                <path d="M2 17l10 5 10-5" />
                                                <path d="M2 12l10 5 10-5" />
                                            </svg>
                                        )}
                                    </div>
                                    <span style={{
                                        fontSize: "13px",
                                        fontWeight: 500,
                                        color: msg.role === "user" ? "#a1a1aa" : "#fff",
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
                                            borderRadius: "8px",
                                            marginBottom: "8px",
                                            marginLeft: "32px",
                                        }}
                                    />
                                )}

                                {/* Message */}
                                <p style={{
                                    fontSize: "14px",
                                    lineHeight: 1.6,
                                    color: "#e4e4e7",
                                    margin: 0,
                                    paddingLeft: "32px",
                                }}>
                                    {msg.content}
                                </p>

                                {/* Model Badge */}
                                {msg.partVersion && (
                                    <div style={{
                                        marginTop: "12px",
                                        marginLeft: "32px",
                                        padding: "8px 12px",
                                        background: "rgba(59, 130, 246, 0.1)",
                                        border: "1px solid rgba(59, 130, 246, 0.2)",
                                        borderRadius: "8px",
                                        display: "inline-flex",
                                        alignItems: "center",
                                        gap: "8px",
                                    }}>
                                        <Box size={14} style={{ color: "#60a5fa" }} />
                                        <span style={{ fontSize: "13px", color: "#60a5fa" }}>
                                            Model v{msg.partVersion}
                                        </span>
                                    </div>
                                )}
                            </div>
                        ))}

                        {/* Loading */}
                        {isGenerating && (
                            <div>
                                <div style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "8px",
                                    marginBottom: "8px",
                                }}>
                                    <div style={{
                                        width: "24px",
                                        height: "24px",
                                        borderRadius: "6px",
                                        background: "linear-gradient(135deg, #3b82f6, #6366f1)",
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                    }}>
                                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2">
                                            <path d="M12 2L2 7l10 5 10-5-10-5z" />
                                            <path d="M2 17l10 5 10-5" />
                                            <path d="M2 12l10 5 10-5" />
                                        </svg>
                                    </div>
                                    <span style={{ fontSize: "13px", fontWeight: 500, color: "#fff" }}>
                                        OrionFlow
                                    </span>
                                </div>
                                <div style={{ paddingLeft: "32px", display: "flex", gap: "4px" }}>
                                    {[0, 1, 2].map((i) => (
                                        <div
                                            key={i}
                                            style={{
                                                width: "6px",
                                                height: "6px",
                                                borderRadius: "50%",
                                                background: "#3b82f6",
                                                animation: `pulse 1.4s ease-in-out ${i * 0.15}s infinite`,
                                            }}
                                        />
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Input Area */}
            <div style={{ padding: "16px" }}>
                {/* Input Box */}
                <div style={{
                    background: "#18181b",
                    border: "1px solid #27272a",
                    borderRadius: "12px",
                    padding: "12px",
                    display: "flex",
                    alignItems: "flex-end",
                    gap: "8px",
                }}>
                    {/* Textarea */}
                    <textarea
                        ref={textareaRef}
                        placeholder="Message OrionFlow..."
                        value={inputValue}
                        onChange={(e) => setInputValue(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                                e.preventDefault();
                                handleSend();
                            }
                        }}
                        disabled={isGenerating}
                        rows={1}
                        style={{
                            flex: 1,
                            background: "transparent",
                            border: "none",
                            outline: "none",
                            color: "#fff",
                            fontSize: "14px",
                            lineHeight: "24px",
                            resize: "none",
                            minHeight: "24px",
                            maxHeight: "120px",
                            fontFamily: "inherit",
                        }}
                    />

                    {/* Send */}
                    <button
                        onClick={handleSend}
                        disabled={!canSend}
                        style={{
                            width: "32px",
                            height: "32px",
                            borderRadius: "8px",
                            background: canSend ? "#3b82f6" : "#27272a",
                            border: "none",
                            color: canSend ? "#fff" : "#52525b",
                            cursor: canSend ? "pointer" : "not-allowed",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            flexShrink: 0,
                            transition: "all 0.15s",
                        }}
                    >
                        <ArrowUp size={16} />
                    </button>
                </div>
            </div>
        </div>
    );
}
