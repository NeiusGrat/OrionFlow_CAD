import { useState, useEffect } from "react";
import LeftPanel from "./components/Panels/LeftPanel";
import RightPanel from "./components/Panels/RightPanel";
import Viewer from "./components/Viewer/Viewer";
import { useDesignStore, type ChatMessage } from "./store/designStore";
import { Box, LayoutGrid } from "lucide-react";

export default function App() {
  const current = useDesignStore((state) => state.current);
  const addCreation = useDesignStore((state) => state.addCreation);
  const setCurrent = useDesignStore((state) => state.setCurrent);
  const addMessage = useDesignStore((state) => state.addMessage); // NEW
  const setIsGenerating = useDesignStore((state) => state.setIsGenerating);
  const triggerViewAction = useDesignStore((state) => state.triggerViewAction);
  const isGenerating = useDesignStore((state) => state.isGenerating);

  // Handle generation triggered from LeftPanel or Initial View
  async function handleGenerate(prompt: string, image?: File) {
    if (!prompt.trim()) return;

    setIsGenerating(true);

    // Determine if we are starting new or iterating
    let activeId = current?.id;
    let isNew = false;
    let finalPrompt = prompt;

    if (!activeId) {
      isNew = true;
      activeId = crypto.randomUUID();
    } else {
      // ITERATION LOGIC: 
      // If user says "regenerate", we might just resend the SAME prompt or a specific "regenerate" signal?
      // For now, we append.
      if (prompt.toLowerCase() === "regenerate") {
        finalPrompt = current?.prompt || "";
      } else if (current?.prompt) {
        finalPrompt = current.prompt + " " + prompt;
      }
    }

    // 1. Add User Message (Skip if "regenerate" implicit trigger?)
    // Actually, if user clicked regen, we might not want to show a text bubble "regenerate"? 
    // But for now let's show it or maybe handle `prompt === "regenerate"` differently.
    // The user spec said "Regenerate SAME version". 
    // For now, standard flow.
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: prompt,
      timestamp: Date.now(),
      image: image ? URL.createObjectURL(image) : undefined
    };

    if (isNew) {
      // Initialize creation
      addCreation({
        id: activeId,
        prompt: finalPrompt,
        parameters: {},
        material: { roughness: 0.5, metalness: 0.1 },
        files: { glb: "", step: "" },
        history: [userMsg]
      });
      setCurrent(activeId); // Switch to this view
    } else {
      try {
        addMessage(activeId, userMsg);
        // Also update the hidden full prompt of the current design state so next iteration catches it
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
        body: JSON.stringify({ prompt: finalPrompt }), // Send FULL context
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || "Generation failed");
      }

      const data = await response.json();

      // 2. Add Assistant Message with Part Info
      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: "Here is your updated part:",
        timestamp: Date.now(),
        partVersion: (useDesignStore.getState().current?.history.filter(m => m.role === 'assistant').length || 0) + 1,
        files: {
          glb: "http://127.0.0.1:8000/" + data.files.glb,
          step: "http://127.0.0.1:8000/" + data.files.step,
        }
      };

      addMessage(activeId, assistantMsg);

      // Update the 'current' file refs
      useDesignStore.setState((state) => {
        const updated = state.creations.map(c => {
          if (c.id === activeId) {
            return {
              ...c,
              files: assistantMsg.files!, // Update main files entry for Viewer
              featureGraph: data.feature_graph // Keep graph updated
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

  // Listen for custom events from LeftPanel
  useEffect(() => {
    const handler = (e: any) => {
      handleGenerate(e.detail.prompt, e.detail.image);
    };
    window.addEventListener('generate-request', handler);
    return () => window.removeEventListener('generate-request', handler);
  }, [current]);

  const [initialPrompt, setInitialPrompt] = useState("");

  // --- HOME VIEW ---
  if (!current && !isGenerating) {
    return (
      <div style={{
        height: "100vh", width: "100vw",
        background: "var(--color-bg-app)",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: "'Inter', sans-serif"
      }}>
        <div style={{ width: "100%", maxWidth: "700px", padding: "20px", textAlign: "center" }}>
          {/* LOGO */}
          <div style={{ marginBottom: "40px", display: "inline-flex", alignItems: "center", gap: "12px" }}>
            <h1 style={{ fontSize: "42px", fontWeight: 800, letterSpacing: "-1px" }}>
              OrionFlow
            </h1>
          </div>

          {/* BIG PROMPT INPUT */}
          <div style={{
            background: "var(--color-bg-panel)",
            border: "1px solid var(--color-border)",
            borderRadius: "16px",
            padding: "8px",
            display: "flex",
            alignItems: "center",
            boxShadow: "0 20px 40px rgba(0,0,0,0.4)"
          }}>
            <input
              type="text"
              placeholder="Describe what you want to make..."
              value={initialPrompt}
              onChange={(e) => setInitialPrompt(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleGenerate(initialPrompt)}
              autoFocus
              style={{
                flex: 1,
                background: "transparent",
                border: "none",
                fontSize: "18px",
                padding: "16px",
                outline: "none",
                color: "var(--color-text-primary)"
              }}
            />
            <button
              onClick={() => handleGenerate(initialPrompt)}
              disabled={!initialPrompt.trim()}
              style={{
                height: "50px",
                padding: "0 30px",
                borderRadius: "12px",
                background: "var(--color-accent)",
                color: "white",
                border: "none",
                fontSize: "16px",
                fontWeight: 600,
                cursor: "pointer",
                opacity: !initialPrompt.trim() ? 0.5 : 1
              }}
            >
              create
            </button>
          </div>
        </div>
      </div>
    );
  }

  // --- EDITOR VIEW ---
  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        width: "100vw",
        overflow: "hidden",
        background: "var(--color-bg-app)",
        color: "var(--color-text-primary)",
      }}
    >
      <LeftPanel />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", position: "relative", background: "#f8f9fa", }}>
        <div style={{ flex: 1, position: "relative" }}>
          <Viewer url={current ? current.files.glb : ""} />
        </div>

        {/* BOTTOM VIEW CONTROLS (Removed Reset) */}
        {!isGenerating && (
          <div style={{
            position: "absolute",
            bottom: "24px",
            left: "50%",
            transform: "translateX(-50%)",
            background: "#ffffff",
            border: "1px solid #e5e7eb",
            borderRadius: "99px",
            padding: "8px 20px",
            display: "flex",
            gap: "20px",
            alignItems: "center",
            boxShadow: "0 10px 30px rgba(0,0,0,0.1)",
            color: "#374151"
          }}>
            <div
              style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer", fontSize: "13px", fontWeight: 600 }}
              onClick={() => triggerViewAction('ortho')}
            >
              <LayoutGrid size={16} />
              <span>Orthographic</span>
            </div>
            <div style={{ width: "1px", height: "16px", background: "#e5e7eb" }} />
            <div
              style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer", fontSize: "13px", fontWeight: 600 }}
              onClick={() => triggerViewAction('iso')}
            >
              <Box size={16} />
              <span>Isometric</span>
            </div>
            {/* Reset Button REmoved */}
          </div>
        )}
      </div>

      <RightPanel />
    </div>
  );
}
