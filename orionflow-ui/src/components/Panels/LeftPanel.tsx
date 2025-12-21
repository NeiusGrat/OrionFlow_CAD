import { useDesignStore } from "../../store/designStore";
import { Box, Image as ImageIcon, ThumbsUp, ThumbsDown, RefreshCw, Download } from "lucide-react";
import { useState, useRef, useEffect } from "react";

// Helper for Part Card
function PartCard({ version, files, onRegenerate }: { version: number, files?: { glb: string, step: string }, onRegenerate?: () => void }) {
    return (
        <div style={{
            background: "var(--color-bg-element)",
            borderRadius: "12px",
            border: "1px solid var(--color-border)",
            padding: "16px",
            marginTop: "12px",
            width: "100%",
            maxWidth: "340px",
            boxShadow: "0 2px 8px rgba(0,0,0,0.05)"
        }}>
            <div
                style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: "16px",
                    background: "#000000",
                    border: "1px solid #F97316", // Orange border
                    borderRadius: "8px",
                    padding: "12px",
                    cursor: "pointer"
                }}
                onClick={() => {
                    // Logic to 'show' on right side - usually just by being the 'current' one.
                    // We could re-trigger a selection if needed, but standard flow covers it.
                    // Visual feedback mostly.
                }}
            >
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <Box size={18} strokeWidth={2} color="white" />
                    <span style={{ fontWeight: 600, fontSize: "14px", color: "white" }}>OrionFlow Object</span>
                </div>
            </div>

            {/* Actions Row */}
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <button style={{ background: "transparent", border: "none", cursor: "pointer", opacity: 0.5, padding: "4px" }} title="Good Response">
                    <ThumbsUp size={16} />
                </button>
                <button style={{ background: "transparent", border: "none", cursor: "pointer", opacity: 0.5, padding: "4px" }} title="Bad Response">
                    <ThumbsDown size={16} />
                </button>

                <div style={{ width: "1px", height: "16px", background: "var(--color-border)", margin: "0 4px" }}></div>

                <button
                    onClick={onRegenerate}
                    style={{ background: "transparent", border: "none", cursor: "pointer", opacity: 0.5, padding: "4px" }}
                    title="Regenerate Version"
                >
                    <RefreshCw size={16} />
                </button>

                {/* VERSION DOWNLOAD BUTTON */}
                {files?.step && (
                    <a
                        href={files.step}
                        download={`OrionFlow_v${version}.step`}
                        style={{
                            marginLeft: "auto",
                            background: "transparent",
                            border: "1px solid var(--color-border)",
                            borderRadius: "6px",
                            padding: "6px 12px",
                            cursor: "pointer",
                            color: "var(--color-text-primary)",
                            display: "flex", alignItems: "center", gap: "6px",
                            textDecoration: "none",
                            fontSize: "12px",
                            fontWeight: 500
                        }}
                        title="Download STEP"
                    >
                        <Download size={14} />
                        <span>Step</span>
                    </a>
                )}
            </div>
        </div>
    );
}



export default function LeftPanel() {
    const current = useDesignStore((state) => state.current);


    const [inputValue, setInputValue] = useState("");
    const [selectedImage, setSelectedImage] = useState<File | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const scrollRef = useRef<HTMLDivElement>(null);

    // Auto-scroll
    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [current?.history]);



    const handleSend = () => {
        if (!inputValue.trim() && !selectedImage) return;

        // Dispatch Custom Event for App.tsx to catch
        const event = new CustomEvent('generate-request', {
            detail: { prompt: inputValue, image: selectedImage }
        });
        window.dispatchEvent(event);

        setInputValue("");
        setSelectedImage(null);
    };

    const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        if (file.size > 3 * 1024 * 1024) {
            alert("Image must be less than 3MB");
            return;
        }
        setSelectedImage(file);
    };

    return (
        <div style={{
            width: "400px",
            background: "var(--color-bg-panel)",
            borderRight: "1px solid var(--color-border)",
            display: "flex",
            flexDirection: "column",
            height: "100%",
            flexShrink: 0,
            zIndex: 20,
        }}>
            {/* BRAND HEADER */}
            <div style={{
                height: "64px",
                padding: "0 24px",
                borderBottom: "1px solid var(--color-border)",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between"
            }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: "12px" }}>
                    <h1 style={{ fontFamily: "sans-serif", fontWeight: 800, fontSize: "24px", letterSpacing: "-1px" }}>
                        OrionFlow
                    </h1>
                    <span style={{ fontSize: "12px", color: "var(--color-text-muted)", fontWeight: 600, letterSpacing: "0.5px" }}>AI CAD Copilot</span>
                </div>

                {/* No Controls in Header as per Adam Spec */}
            </div>

            {/* MESSAGE LIST */}
            <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "24px", display: "flex", flexDirection: "column", gap: "24px" }}>
                {/* Initial State Prompt if no history */}
                {(!current || !current.history?.length) && (
                    <div style={{ opacity: 0.5, textAlign: "center", marginTop: "40px", fontSize: "14px" }}>
                        Ask me to design something...
                    </div>
                )}

                {current && current.history && current.history.map((msg) => (
                    <div key={msg.id} style={{
                        display: "flex",
                        gap: "16px",
                        paddingBottom: "24px",
                        borderBottom: "1px solid rgba(255,255,255,0.15)", // More visible separator
                        marginBottom: "24px" // Add margin for spacing
                    }}>
                        {/* Avatar */}
                        <div style={{
                            width: "32px", height: "32px", borderRadius: "50%",
                            background: msg.role === 'user'
                                ? "linear-gradient(to bottom right, #FF8C00, #F97316)" // Orange Gradient for User
                                : "#EC4899", // Pink for Adam (Assistant) - keeping this distinct or change? User said "green round box add orange", assuming user avatar.
                            flexShrink: 0,
                            display: "flex", alignItems: "center", justifyContent: "center",
                            color: "white", fontWeight: 700, fontSize: "14px"
                        }}>
                            {msg.role === 'user' ? "" : <Box size={16} />}
                        </div>

                        <div style={{ flex: 1 }}>
                            {/* Message Bubble (?) or just text - Reference uses plain text for user, Card for bot */}
                            {msg.role === 'user' ? (
                                <p style={{ margin: 0, fontSize: "15px", lineHeight: "1.5", fontWeight: 500 }}>
                                    {msg.content}
                                </p>
                            ) : (
                                <div>
                                    <p style={{ margin: "0 0 12px 0", fontSize: "15px", lineHeight: "1.5", color: "var(--color-text-secondary)" }}>
                                        {msg.content}
                                    </p>
                                    {/* Part Card if version exists */}
                                    {msg.partVersion && <PartCard
                                        version={msg.partVersion}
                                        files={msg.files}
                                        onRegenerate={() => {
                                            // Simple regeneration trigger
                                            const event = new CustomEvent('generate-request', {
                                                detail: { prompt: "regenerate" }
                                            });
                                            window.dispatchEvent(event);
                                        }}
                                    />}
                                </div>
                            )}
                        </div>
                    </div>
                ))}
            </div>

            {/* INPUT AREA (Bottom) */}
            <div style={{ padding: "20px" }}>
                <div style={{
                    background: "var(--color-bg-element)",
                    border: "1px solid var(--color-border)",
                    borderRadius: "16px",
                    padding: "16px",
                    display: "flex",
                    flexDirection: "column",
                    gap: "12px",
                    boxShadow: "0 4px 12px rgba(0,0,0,0.1)"
                }}>
                    {/* Blue Border Input Container */}
                    <div style={{
                        border: "1px solid #3b82f6", // Blue border
                        borderRadius: "8px",
                        padding: "8px 12px",
                        background: "rgba(59, 130, 246, 0.05)"
                    }}>
                        <input
                            type="text"
                            placeholder="Orion Copilot"
                            value={inputValue}
                            onChange={(e) => setInputValue(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                            style={{
                                width: "100%",
                                border: "none", background: "transparent", outline: "none",
                                color: "var(--color-text-primary)", fontSize: "15px",
                                padding: "0"
                            }}
                        />
                    </div>

                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div style={{ display: "flex", gap: "8px" }}>
                            <button
                                onClick={() => fileInputRef.current?.click()}
                                style={{ background: "transparent", border: "none", color: "var(--color-text-muted)", cursor: "pointer", padding: "4px" }}
                            >
                                <ImageIcon size={20} />
                            </button>
                            <input
                                type="file"
                                ref={fileInputRef}
                                style={{ display: "none" }}
                                accept="image/*"
                                onChange={handleImageUpload}
                            />
                        </div>

                        <button
                            onClick={handleSend}
                            style={{
                                width: "48px", height: "48px", borderRadius: "12px", // Even Larger button
                                background: inputValue.trim() ? "var(--color-accent)" : "#333",
                                color: "white",
                                border: "none", display: "flex", alignItems: "center", justifyContent: "center",
                                cursor: "pointer",
                                transition: "all 0.2s"
                            }}
                        >
                            <ArrowUpIcon />
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

const ArrowUpIcon = () => <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round"><path d="M12 19V5" /><path d="M5 12l7-7 7 7" /></svg>
