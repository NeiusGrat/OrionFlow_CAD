import { useState, useRef, useEffect } from "react";
import { useDesignStore } from "../../store/designStore";
import { useChatStore } from "../../store/chatStore";
import { useOFLStore } from "../../store/oflStore";
import OrionFlowLogo from "../OrionFlowLogo";
import { Box, ArrowUp } from "lucide-react";

interface ChatPanelProps {
    onGenerate: (prompt: string, image?: File) => void;
}

/** Official mark on the brand-violet tile — the agent's avatar. */
function AgentAvatar({ size = 24 }: { size?: number }) {
    return (
        <div style={{
            width: `${size}px`,
            height: `${size}px`,
            borderRadius: `${Math.round(size / 4)}px`,
            background: "linear-gradient(135deg, #8AA5E6, #8AA5E6)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
        }}>
            <OrionFlowLogo size={Math.round(size * 0.62)} theme="mono" />
        </div>
    );
}

/** Pipeline stages surfaced while the agent works — mirrors the real
 *  backend flow: intent → OFL code → B-rep build → validate/export. */
const AGENT_STAGES = [
    "Parsing engineering intent",
    "Writing OFL code",
    "Building B-rep geometry",
    "Validating & exporting",
];

function AgentWorking() {
    const [stage, setStage] = useState(0);
    const [elapsed, setElapsed] = useState(0);

    useEffect(() => {
        const t0 = Date.now();
        const timer = setInterval(() => {
            const secs = (Date.now() - t0) / 1000;
            setElapsed(secs);
            // advance a stage roughly every 4s, hold on the last one
            setStage(Math.min(Math.floor(secs / 4), AGENT_STAGES.length - 1));
        }, 500);
        return () => clearInterval(timer);
    }, []);

    return (
        <div style={{ paddingLeft: "32px" }}>
            {AGENT_STAGES.map((label, i) => (
                <div
                    key={label}
                    style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                        padding: "3px 0",
                        fontSize: "12.5px",
                        color: i < stage ? "#7C7364" : i === stage ? "#D8CFBF" : "#3f3f46",
                        transition: "color 0.3s ease",
                    }}
                >
                    <span style={{
                        width: "6px",
                        height: "6px",
                        borderRadius: "50%",
                        flexShrink: 0,
                        background: i < stage ? "#22c55e" : i === stage ? "#8AA5E6" : "#3f3f46",
                        animation: i === stage ? "pulse 1.4s ease-in-out infinite" : "none",
                    }} />
                    {label}
                    {i < stage && <span style={{ fontSize: "11px", color: "#22c55e" }}>✓</span>}
                </div>
            ))}
            <div style={{ fontSize: "11px", color: "#4A4133", marginTop: "6px" }}>
                {elapsed.toFixed(0)}s
            </div>
        </div>
    );
}

/** One-click CAD operations the agent applies to the current part. */
const QUICK_OPS = [
    "Chamfer all edges 1 mm",
    "Fillet vertical edges 3 mm",
    "Shell to 2 mm walls, open top",
    "Add 4 corner holes for M4 bolts",
];

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
            width: "100%",
            flex: 1,
            minHeight: 0,
            background: "transparent",
            display: "flex",
            flexDirection: "column",
        }}>
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
                        <div style={{ marginBottom: "20px" }}>
                            <AgentAvatar size={56} />
                        </div>
                        <p style={{
                            fontSize: "16px",
                            fontWeight: 600,
                            color: "#fff",
                            marginBottom: "8px",
                        }}>
                            Orion Agent
                        </p>
                        <p style={{
                            fontSize: "14px",
                            color: "#7C7364",
                            lineHeight: 1.5,
                        }}>
                            Describe a part to generate — then ask for CAD operations:
                            fillets, shells, holes, patterns.
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
                                    {msg.role === "user" ? (
                                        <div style={{
                                            width: "24px",
                                            height: "24px",
                                            borderRadius: "6px",
                                            background: "#241F18",
                                            display: "flex",
                                            alignItems: "center",
                                            justifyContent: "center",
                                        }}>
                                            <span style={{ fontSize: "11px", fontWeight: 600, color: "#A79D8B" }}>Y</span>
                                        </div>
                                    ) : (
                                        <AgentAvatar />
                                    )}
                                    <span style={{
                                        fontSize: "13px",
                                        fontWeight: 500,
                                        color: msg.role === "user" ? "#A79D8B" : "#fff",
                                    }}>
                                        {msg.role === "user" ? "You" : "Orion Agent"}
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
                                    color: "#D8CFBF",
                                    margin: 0,
                                    paddingLeft: "32px",
                                    whiteSpace: "pre-line",
                                }}>
                                    {msg.content}
                                </p>

                                {/* Model Badge */}
                                {msg.partVersion && (
                                    <div style={{
                                        marginTop: "12px",
                                        marginLeft: "32px",
                                        padding: "8px 12px",
                                        background: "rgba(138, 165, 230, 0.1)",
                                        border: "1px solid rgba(138, 165, 230, 0.2)",
                                        borderRadius: "8px",
                                        display: "inline-flex",
                                        alignItems: "center",
                                        gap: "8px",
                                    }}>
                                        <Box size={14} style={{ color: "#A8BDEE" }} />
                                        <span style={{ fontSize: "13px", color: "#A8BDEE" }}>
                                            Model v{msg.partVersion}
                                        </span>
                                    </div>
                                )}
                            </div>
                        ))}

                        {/* Agent working — live pipeline stepper */}
                        {isGenerating && (
                            <div>
                                <div style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "8px",
                                    marginBottom: "8px",
                                }}>
                                    <AgentAvatar />
                                    <span style={{ fontSize: "13px", fontWeight: 500, color: "#fff" }}>
                                        Orion Agent
                                    </span>
                                </div>
                                <AgentWorking />
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Input Area */}
            <div style={{ padding: "16px" }}>
                {/* Quick CAD operations on the current part */}
                {current && useOFLStore.getState().oflCode && !isGenerating && (
                    <div style={{
                        display: "flex",
                        gap: "6px",
                        flexWrap: "wrap",
                        marginBottom: "10px",
                    }}>
                        {QUICK_OPS.map((op) => (
                            <button
                                key={op}
                                onClick={() => onGenerate(op)}
                                style={{
                                    fontSize: "11px",
                                    color: "#A79D8B",
                                    background: "#18181b",
                                    border: "1px solid #241F18",
                                    borderRadius: "999px",
                                    padding: "4px 10px",
                                    cursor: "pointer",
                                    transition: "all 0.15s",
                                }}
                                onMouseEnter={(e) => {
                                    e.currentTarget.style.color = "#D8CFBF";
                                    e.currentTarget.style.borderColor = "#8AA5E6";
                                }}
                                onMouseLeave={(e) => {
                                    e.currentTarget.style.color = "#A79D8B";
                                    e.currentTarget.style.borderColor = "#241F18";
                                }}
                            >
                                {op}
                            </button>
                        ))}
                    </div>
                )}
                {/* Input Box */}
                <div style={{
                    background: "#18181b",
                    border: "1px solid #241F18",
                    borderRadius: "12px",
                    padding: "12px",
                    display: "flex",
                    alignItems: "flex-end",
                    gap: "8px",
                }}>
                    {/* Textarea */}
                    <textarea
                        ref={textareaRef}
                        placeholder="Message Orion Agent…"
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
                            background: canSend ? "#8AA5E6" : "#241F18",
                            border: "none",
                            color: canSend ? "#fff" : "#4A4133",
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
