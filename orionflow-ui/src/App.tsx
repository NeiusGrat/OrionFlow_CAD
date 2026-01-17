import { useState, useEffect } from "react";
import LeftSidebar from "./components/Panels/LeftSidebar";
import ChatPanel from "./components/Panels/ChatPanel";
import Viewer from "./components/Viewer/Viewer";
import { useDesignStore } from "./store/designStore";
import { useChatStore, type ChatMessage } from "./store/chatStore";
import { Hexagon, Zap, Cpu, Box, ArrowRight } from "lucide-react";

export default function App() {
    const current = useDesignStore((state) => state.current);
    const addCreation = useDesignStore((state) => state.addCreation);
    const setCurrent = useDesignStore((state) => state.setCurrent);
    const addMessage = useChatStore((state) => state.addMessage);
    const setIsGenerating = useDesignStore((state) => state.setIsGenerating);
    const isGenerating = useDesignStore((state) => state.isGenerating);

    async function handleGenerate(prompt: string, image?: File) {
        if (!prompt.trim()) return;

        setIsGenerating(true);

        let activeId = current?.id;
        let isNew = false;
        let finalPrompt = prompt;

        if (!activeId) {
            isNew = true;
            activeId = crypto.randomUUID();
        } else {
            if (prompt.toLowerCase() === "regenerate") {
                finalPrompt = current?.prompt || "";
            } else if (current?.prompt) {
                finalPrompt = current.prompt + " " + prompt;
            }
        }

        const userMsg: ChatMessage = {
            id: crypto.randomUUID(),
            role: 'user',
            content: prompt,
            timestamp: Date.now(),
            image: image ? URL.createObjectURL(image) : undefined
        };

        if (isNew) {
            addCreation({
                id: activeId,
                prompt: finalPrompt,
                parameters: {},
                material: { roughness: 0.5, metalness: 0.1 },
                files: { glb: "", step: "", stl: "" },
            });
            addMessage(activeId, userMsg);
            setCurrent(activeId);
        } else {
            try {
                addMessage(activeId, userMsg);
                useDesignStore.setState(state => ({
                    creations: state.creations.map(c => c.id === activeId ? { ...c, prompt: finalPrompt } : c),
                    current: state.current?.id === activeId ? { ...state.current!, prompt: finalPrompt } : state.current
                }));
            } catch (e) { console.warn("Failed to add msg", e) }
        }

        try {
            const response = await fetch("http://127.0.0.1:8000/generate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt: finalPrompt }),
            });

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.detail || "Generation failed");
            }

            const data = await response.json();

            const assistantMsg: ChatMessage = {
                id: crypto.randomUUID(),
                role: 'assistant',
                content: "Here is your updated part:",
                timestamp: Date.now(),
                partVersion: (useChatStore.getState().getHistory(activeId).filter(m => m.role === 'assistant').length || 0) + 1,
                files: {
                    glb: "http://127.0.0.1:8000/" + data.viewer.glb_url,
                    step: "http://127.0.0.1:8000/" + data.downloads.step,
                    stl: "http://127.0.0.1:8000/" + data.downloads.stl,
                }
            };

            addMessage(activeId, assistantMsg);

            useDesignStore.setState((state) => {
                const updated = state.creations.map(c => {
                    if (c.id === activeId) {
                        return {
                            ...c,
                            files: assistantMsg.files!,
                            featureGraph: data.cfg,
                            parameters: data.cfg.parameters || {}
                        };
                    }
                    return c;
                })
                const curr = state.current?.id === activeId ? updated.find(c => c.id === activeId) : state.current;
                return { creations: updated, current: curr || null };
            });

        } catch (e: any) {
            console.error(e);
            addMessage(activeId, {
                id: crypto.randomUUID(),
                role: 'assistant',
                content: `Error: ${e.message}`,
                timestamp: Date.now()
            });
        } finally {
            setIsGenerating(false);
        }
    }

    useEffect(() => {
        const handler = (e: any) => {
            handleGenerate(e.detail.prompt, e.detail.image);
        };
        window.addEventListener('generate-request', handler);
        return () => window.removeEventListener('generate-request', handler);
    }, [current]);

    const [initialPrompt, setInitialPrompt] = useState("");

    return (
        <div
            style={{
                display: "flex",
                height: "100vh",
                width: "100vw",
                overflow: "hidden",
                background: "var(--slate-950)",
                color: "var(--color-text-primary)",
            }}
        >
            {/* Left Sidebar */}
            <LeftSidebar />

            {/* Main Viewer Area */}
            <div style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                position: "relative",
                background: "var(--slate-950)",
            }}>
                {/* Welcome / Empty State */}
                {!current && !isGenerating ? (
                    <div
                        className="grid-bg"
                        style={{
                            flex: 1,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            flexDirection: "column",
                            gap: "40px",
                            padding: "60px",
                            position: "relative",
                            overflow: "hidden",
                        }}
                    >
                        {/* Background Gradient Orbs */}
                        <div style={{
                            position: "absolute",
                            width: "600px",
                            height: "600px",
                            borderRadius: "50%",
                            background: "radial-gradient(circle, rgba(245, 158, 11, 0.08) 0%, transparent 70%)",
                            top: "-200px",
                            right: "-100px",
                            pointerEvents: "none",
                        }} />
                        <div style={{
                            position: "absolute",
                            width: "500px",
                            height: "500px",
                            borderRadius: "50%",
                            background: "radial-gradient(circle, rgba(6, 182, 212, 0.06) 0%, transparent 70%)",
                            bottom: "-150px",
                            left: "-100px",
                            pointerEvents: "none",
                        }} />

                        {/* Hero Section */}
                        <div style={{
                            textAlign: "center",
                            zIndex: 1,
                            animation: "fadeIn 0.6s var(--ease-out-expo)",
                        }}>
                            {/* Logo */}
                            <div style={{
                                width: "100px",
                                height: "100px",
                                borderRadius: "var(--radius-2xl)",
                                background: "linear-gradient(135deg, var(--copper-500) 0%, var(--copper-400) 100%)",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                margin: "0 auto 32px",
                                boxShadow: "0 0 60px var(--copper-glow), 0 20px 40px rgba(0,0,0,0.4)",
                                position: "relative",
                            }}>
                                <Hexagon size={48} color="var(--slate-950)" strokeWidth={2} fill="var(--slate-950)" />
                                <div style={{
                                    position: "absolute",
                                    inset: "-4px",
                                    borderRadius: "var(--radius-2xl)",
                                    border: "1px solid rgba(245, 158, 11, 0.3)",
                                }} />
                            </div>

                            {/* Title */}
                            <h1 style={{
                                fontSize: "56px",
                                fontWeight: 800,
                                letterSpacing: "-0.03em",
                                marginBottom: "16px",
                                lineHeight: 1.1,
                            }}>
                                <span style={{ color: "var(--color-text-primary)" }}>Orion</span>
                                <span style={{ color: "var(--copper-400)" }}>Flow</span>
                            </h1>

                            <p style={{
                                fontSize: "18px",
                                color: "var(--color-text-muted)",
                                fontWeight: 400,
                                maxWidth: "500px",
                                lineHeight: 1.6,
                                margin: "0 auto",
                            }}>
                                Transform your ideas into parametric CAD models with AI-powered precision engineering
                            </p>
                        </div>

                        {/* Input Section */}
                        <div style={{
                            width: "100%",
                            maxWidth: "600px",
                            zIndex: 1,
                            animation: "slideInUp 0.5s var(--ease-out-expo) 0.1s both",
                        }}>
                            <div style={{
                                background: "var(--slate-900)",
                                borderRadius: "var(--radius-xl)",
                                border: "1px solid var(--color-border)",
                                padding: "8px",
                                display: "flex",
                                alignItems: "center",
                                boxShadow: "var(--shadow-lg)",
                                transition: "all var(--duration-normal) var(--ease-out-quad)",
                            }}>
                                <input
                                    type="text"
                                    placeholder="Describe a part to create..."
                                    value={initialPrompt}
                                    onChange={(e) => setInitialPrompt(e.target.value)}
                                    onKeyDown={(e) => e.key === "Enter" && initialPrompt.trim() && handleGenerate(initialPrompt)}
                                    autoFocus
                                    style={{
                                        flex: 1,
                                        background: "transparent",
                                        border: "none",
                                        fontSize: "16px",
                                        padding: "16px 20px",
                                        outline: "none",
                                        color: "var(--color-text-primary)",
                                    }}
                                />
                                <button
                                    onClick={() => handleGenerate(initialPrompt)}
                                    disabled={!initialPrompt.trim()}
                                    style={{
                                        height: "52px",
                                        padding: "0 28px",
                                        borderRadius: "var(--radius-lg)",
                                        background: initialPrompt.trim()
                                            ? "linear-gradient(135deg, var(--copper-500) 0%, var(--copper-400) 100%)"
                                            : "var(--slate-800)",
                                        color: initialPrompt.trim() ? "var(--slate-950)" : "var(--color-text-muted)",
                                        border: "none",
                                        fontSize: "15px",
                                        fontWeight: 600,
                                        cursor: initialPrompt.trim() ? "pointer" : "not-allowed",
                                        display: "flex",
                                        alignItems: "center",
                                        gap: "8px",
                                        boxShadow: initialPrompt.trim() ? "0 0 30px var(--copper-glow)" : "none",
                                        transition: "all var(--duration-fast) var(--ease-out-quad)",
                                    }}
                                >
                                    Create
                                    <ArrowRight size={18} strokeWidth={2.5} />
                                </button>
                            </div>
                        </div>

                        {/* Example Prompts */}
                        <div style={{
                            display: "flex",
                            gap: "12px",
                            flexWrap: "wrap",
                            justifyContent: "center",
                            maxWidth: "600px",
                            zIndex: 1,
                            animation: "slideInUp 0.5s var(--ease-out-expo) 0.2s both",
                        }}>
                            {[
                                "A 25mm cube with chamfered edges",
                                "Cylinder with center hole",
                                "L-bracket with fillets"
                            ].map((example, i) => (
                                <button
                                    key={example}
                                    onClick={() => setInitialPrompt(example)}
                                    style={{
                                        padding: "10px 18px",
                                        background: "var(--slate-900)",
                                        border: "1px solid var(--color-border)",
                                        borderRadius: "var(--radius-full)",
                                        color: "var(--color-text-secondary)",
                                        fontSize: "13px",
                                        fontWeight: 500,
                                        cursor: "pointer",
                                        transition: "all var(--duration-fast) var(--ease-out-quad)",
                                        display: "flex",
                                        alignItems: "center",
                                        gap: "8px",
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
                                    <Box size={14} style={{ color: "var(--copper-400)" }} />
                                    {example}
                                </button>
                            ))}
                        </div>

                        {/* Features */}
                        <div style={{
                            display: "flex",
                            gap: "32px",
                            marginTop: "20px",
                            zIndex: 1,
                            animation: "slideInUp 0.5s var(--ease-out-expo) 0.3s both",
                        }}>
                            {[
                                { icon: Zap, label: "Instant Generation", desc: "AI-powered CAD" },
                                { icon: Cpu, label: "Parametric Models", desc: "Fully editable" },
                                { icon: Box, label: "Export Ready", desc: "STEP, STL, GLB" },
                            ].map(({ icon: Icon, label, desc }) => (
                                <div
                                    key={label}
                                    style={{
                                        display: "flex",
                                        alignItems: "center",
                                        gap: "14px",
                                        padding: "16px 20px",
                                        background: "var(--slate-900)",
                                        border: "1px solid var(--color-border)",
                                        borderRadius: "var(--radius-lg)",
                                    }}
                                >
                                    <div style={{
                                        width: "40px",
                                        height: "40px",
                                        borderRadius: "var(--radius-md)",
                                        background: "var(--slate-800)",
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                    }}>
                                        <Icon size={20} style={{ color: "var(--copper-400)" }} />
                                    </div>
                                    <div>
                                        <div style={{
                                            fontSize: "14px",
                                            fontWeight: 600,
                                            color: "var(--color-text-primary)",
                                        }}>
                                            {label}
                                        </div>
                                        <div style={{
                                            fontSize: "12px",
                                            color: "var(--color-text-muted)",
                                            marginTop: "2px",
                                        }}>
                                            {desc}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                ) : (
                    <div style={{ flex: 1, position: "relative" }}>
                        <Viewer url={current ? current.files.glb : ""} />
                    </div>
                )}
            </div>

            {/* Right Chat Panel */}
            <ChatPanel onGenerate={handleGenerate} />
        </div>
    );
}
