import { useState, useEffect } from "react";
import LeftSidebar from "./components/Panels/LeftSidebar";
import ChatPanel from "./components/Panels/ChatPanel";
import Viewer from "./components/Viewer/Viewer";
import { useDesignStore } from "./store/designStore";
import { useChatStore, type ChatMessage } from "./store/chatStore";
import { ArrowRight } from "lucide-react";

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
                background: "#030712",
                color: "#f8fafc",
            }}
        >
            <LeftSidebar />

            <div style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                position: "relative",
            }}>
                {!current && !isGenerating ? (
                    <div
                        style={{
                            flex: 1,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            flexDirection: "column",
                            padding: "40px",
                        }}
                    >
                        {/* Simple Logo */}
                        <h1 style={{
                            fontSize: "48px",
                            fontWeight: 700,
                            letterSpacing: "-0.03em",
                            marginBottom: "48px",
                        }}>
                            <span style={{ color: "#f8fafc" }}>Orion</span>
                            <span style={{ color: "#3b82f6" }}>Flow</span>
                        </h1>

                        {/* Simple Input */}
                        <div style={{
                            width: "100%",
                            maxWidth: "560px",
                        }}>
                            <div style={{
                                display: "flex",
                                alignItems: "center",
                                background: "#111827",
                                border: "1px solid #1f2937",
                                borderRadius: "12px",
                                padding: "4px",
                            }}>
                                <input
                                    type="text"
                                    placeholder="Describe a CAD model..."
                                    value={initialPrompt}
                                    onChange={(e) => setInitialPrompt(e.target.value)}
                                    onKeyDown={(e) => e.key === "Enter" && initialPrompt.trim() && handleGenerate(initialPrompt)}
                                    autoFocus
                                    style={{
                                        flex: 1,
                                        background: "transparent",
                                        border: "none",
                                        fontSize: "15px",
                                        padding: "14px 16px",
                                        outline: "none",
                                        color: "#f8fafc",
                                    }}
                                />
                                <button
                                    onClick={() => handleGenerate(initialPrompt)}
                                    disabled={!initialPrompt.trim()}
                                    style={{
                                        height: "44px",
                                        width: "44px",
                                        borderRadius: "8px",
                                        background: initialPrompt.trim() ? "#3b82f6" : "#1f2937",
                                        color: initialPrompt.trim() ? "#fff" : "#6b7280",
                                        border: "none",
                                        cursor: initialPrompt.trim() ? "pointer" : "not-allowed",
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                        transition: "all 0.15s ease",
                                    }}
                                >
                                    <ArrowRight size={18} />
                                </button>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div style={{ flex: 1, position: "relative" }}>
                        <Viewer url={current ? current.files.glb : ""} />
                    </div>
                )}
            </div>

            <ChatPanel onGenerate={handleGenerate} />
        </div>
    );
}
