import { useEffect } from "react";
import { Routes, Route, Navigate, useSearchParams } from "react-router-dom";
import Workspace from "./components/Studio/Workspace";
import { useAuthStore } from "./store/authStore";
import AuthPage from "./pages/AuthPage";
import VerifyEmailPage from "./pages/VerifyEmailPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import PrivacyPage from "./pages/PrivacyPage";
import TermsPage from "./pages/TermsPage";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
    const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
    if (!isAuthenticated) return <Navigate to="/auth" replace />;
    return <>{children}</>;
}

/** The studio.
 *
 *  Generation lives in `studioStore` now, not here: a turn is a stream of
 *  events (derivation, build, verdict) rather than one request/response, so
 *  the panel that renders it owns it. This component only handles routing and
 *  the gallery deep link.
 */
function CADApp() {
    const [searchParams, setSearchParams] = useSearchParams();

    // Deep link from the marketing gallery: /?example=<id>
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

    return <Workspace />;
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
