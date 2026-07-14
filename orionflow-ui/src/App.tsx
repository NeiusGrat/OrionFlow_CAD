import { useEffect } from "react";
import { Routes, Route, Navigate, useSearchParams } from "react-router-dom";
import Workspace from "./components/Studio/Workspace";
import { useDesignStore } from "./store/designStore";
import { useChatStore, type ChatMessage } from "./store/chatStore";
import { useAuthStore } from "./store/authStore";
import { useOFLStore } from "./store/oflStore";
import { generateOFL, getFullUrl, type OFLResponse } from "./services/oflApi";
import AuthPage from "./pages/AuthPage";
import VerifyEmailPage from "./pages/VerifyEmailPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import PrivacyPage from "./pages/PrivacyPage";
import TermsPage from "./pages/TermsPage";

/** Validation evidence line shown under agent replies, e.g.
 *  "✓ watertight · 19.7 cm³ · 120×80×6 mm · self-repaired ×1" */
function buildReport(data: OFLResponse): string {
    const bits: string[] = [];
    const s = data.stats;
    if (s) {
        bits.push(s.watertight ? "watertight" : "open mesh");
        if (s.volume_mm3 > 0)
            bits.push(
                s.volume_mm3 >= 1000
                    ? `${(s.volume_mm3 / 1000).toFixed(1)} cm³`
                    : `${s.volume_mm3.toFixed(0)} mm³`
            );
        if (s.bbox_mm?.length === 3) bits.push(`${s.bbox_mm.map((v) => Math.round(v)).join("×")} mm`);
    }
    if (data.repair_attempts) bits.push(`self-repaired ×${data.repair_attempts}`);
    return bits.length ? `\n✓ ${bits.join(" · ")}` : "";
}

/** Snapshot the successful result as a named version on the part's timeline. */
function pushVersion(designId: string, label: string, data: OFLResponse) {
    useDesignStore.getState().addVersion(designId, {
        label: label.length > 48 ? label.slice(0, 48) + "…" : label,
        timestamp: Date.now(),
        files: {
            glb: getFullUrl(data.files.glb) || "",
            step: getFullUrl(data.files.step) || "",
            stl: getFullUrl(data.files.stl) || "",
        },
        oflCode: data.ofl_code,
        parameters: Object.fromEntries(data.parameters.map((p) => [p.name, p.value])),
    });
}

// Protected route wrapper
function ProtectedRoute({ children }: { children: React.ReactNode }) {
    const isAuthenticated = useAuthStore((state) => state.isAuthenticated);

    if (!isAuthenticated) {
        return <Navigate to="/auth" replace />;
    }

    return <>{children}</>;
}

// The AI-native CAD design studio
function CADApp() {
    const current = useDesignStore((state) => state.current);
    const addCreation = useDesignStore((state) => state.addCreation);
    const addMessage = useChatStore((state) => state.addMessage);
    const setIsGenerating = useDesignStore((state) => state.setIsGenerating);

    async function handleGenerate(prompt: string) {
        if (!prompt.trim()) return;

        const active = useDesignStore.getState().current;
        const oflCode = useOFLStore.getState().oflCode;

        const userMsg: ChatMessage = {
            id: crypto.randomUUID(),
            role: "user",
            content: prompt,
            timestamp: Date.now(),
        };

        // ── Edit mode: an existing part + code → apply the instruction as a
        //    CAD operation via /ofl/edit instead of regenerating from scratch.
        if (active && oflCode && prompt.toLowerCase() !== "regenerate") {
            addMessage(active.id, userMsg);
            setIsGenerating(true);
            try {
                const res = await useOFLStore.getState().edit(prompt);
                if (res?.success) pushVersion(active.id, prompt, res);
                addMessage(active.id, {
                    id: crypto.randomUUID(),
                    role: "assistant",
                    content: res?.success
                        ? `Applied — model and code updated.${buildReport(res)}`
                        : `Edit failed: ${res?.error || "unknown error"}`,
                    timestamp: Date.now(),
                    files: res?.success
                        ? {
                              glb: getFullUrl(res.files.glb) || "",
                              step: getFullUrl(res.files.step) || "",
                              stl: getFullUrl(res.files.stl) || "",
                          }
                        : undefined,
                });
            } finally {
                setIsGenerating(false);
            }
            return;
        }

        // ── New part (or explicit regenerate)
        setIsGenerating(true);
        const isRegen = prompt.toLowerCase() === "regenerate" && active;
        const finalPrompt = isRegen ? active!.prompt : prompt;
        const activeId = isRegen ? active!.id : crypto.randomUUID();

        if (!isRegen) {
            addCreation({
                id: activeId,
                prompt: finalPrompt,
                parameters: {},
                material: { roughness: 0.5, metalness: 0.1 },
                files: { glb: "", step: "", stl: "" },
            });
        }
        addMessage(activeId, userMsg);

        try {
            const data = await generateOFL(finalPrompt);
            useOFLStore.getState().setFromResponse(data);

            if (!data.success) {
                throw new Error(data.error || "Generation failed");
            }

            const files = {
                glb: getFullUrl(data.files.glb) || "",
                step: getFullUrl(data.files.step) || "",
                stl: getFullUrl(data.files.stl) || "",
            };

            addMessage(activeId, {
                id: crypto.randomUUID(),
                role: "assistant",
                content: `Part generated — inspect it in the viewport, tune parameters, or describe the next operation.${buildReport(data)}`,
                timestamp: Date.now(),
                partVersion:
                    (useChatStore.getState().getHistory(activeId).filter((m) => m.role === "assistant").length || 0) + 1,
                files,
            });

            useDesignStore.setState((state) => {
                const updated = state.creations.map((c) =>
                    c.id === activeId
                        ? {
                              ...c,
                              files,
                              parameters: Object.fromEntries(data.parameters.map((p) => [p.name, p.value])),
                          }
                        : c
                );
                const curr = state.current?.id === activeId ? updated.find((c) => c.id === activeId) : state.current;
                return { creations: updated, current: curr || null };
            });
            pushVersion(activeId, finalPrompt, data);
        } catch (e: any) {
            console.error(e);
            addMessage(activeId, {
                id: crypto.randomUUID(),
                role: "assistant",
                content: `Error: ${e.message}`,
                timestamp: Date.now(),
            });
        } finally {
            setIsGenerating(false);
        }
    }

    useEffect(() => {
        const handler = (e: any) => {
            handleGenerate(e.detail.prompt);
        };
        window.addEventListener("generate-request", handler);
        return () => window.removeEventListener("generate-request", handler);
    }, [current]);

    // Deep link from the marketing gallery: /?example=<id> (or legacy /app?example=)
    const [searchParams, setSearchParams] = useSearchParams();
    useEffect(() => {
        const exampleId = searchParams.get("example");
        if (!exampleId) return;
        import("./lib/examples").then(async ({ fetchExamples, loadExampleIntoStudio }) => {
            try {
                const examples = await fetchExamples();
                const ex = examples.find((e) => e.id === exampleId);
                if (ex) loadExampleIntoStudio(ex);
            } finally {
                setSearchParams({}, { replace: true });
            }
        });
    }, []);

    return <Workspace onGenerate={handleGenerate} />;
}

export default function App() {
    return (
        <Routes>
            {/* app.orionflow.in is the studio — no marketing pages here */}
            <Route
                path="/"
                element={
                    <ProtectedRoute>
                        <CADApp />
                    </ProtectedRoute>
                }
            />
            {/* legacy studio path + gallery deep links keep working */}
            <Route
                path="/app"
                element={
                    <ProtectedRoute>
                        <CADApp />
                    </ProtectedRoute>
                }
            />
            <Route path="/auth" element={<AuthPage />} />
            <Route path="/auth/verify-email" element={<VerifyEmailPage />} />
            <Route path="/auth/reset-password" element={<ResetPasswordPage />} />
            <Route path="/auth/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/privacy" element={<PrivacyPage />} />
            <Route path="/terms" element={<TermsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
    );
}
