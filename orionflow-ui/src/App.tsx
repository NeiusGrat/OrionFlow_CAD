import { useEffect } from "react";
import { Routes, Route, Navigate, useSearchParams } from "react-router-dom";
import Workspace from "./components/Studio/Workspace";
import { useAuthStore } from "./store/authStore";
import AuthPage from "./pages/AuthPage";
import AuthHandoffPage from "./pages/AuthHandoffPage";
import StartPage from "./pages/StartPage";
import VerifyEmailPage from "./pages/VerifyEmailPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import PrivacyPage from "./pages/PrivacyPage";
import TermsPage from "./pages/TermsPage";
import AccountPage from "./pages/AccountPage";
import WatchdogPage from "./pages/WatchdogPage";
import InspectHome from "./pages/inspect/InspectHome";
import ProjectPage from "./pages/inspect/ProjectPage";
import InspectWorkspace from "./pages/inspect/Workspace";
import ComparePage from "./pages/inspect/ComparePage";
import AssemblyPage from "./pages/inspect/AssemblyPage";
import ReviewHome from "./pages/review/ReviewHome";
import ReviewProject from "./pages/review/ReviewProject";
import ReviewWorkspace from "./pages/review/ReviewWorkspace";

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
        // Deliberately once, on mount. The effect clears the query parameter it
        // reads, so listing `searchParams` would re-run it on its own cleanup.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    return <Workspace />;
}

function HomeRoute() {
    const [searchParams] = useSearchParams();
    const example = searchParams.get("example");
    if (example) return <Navigate to={`/studio?example=${encodeURIComponent(example)}`} replace />;
    return <InspectHome />;
}

export default function App() {
    return (
        <Routes>
            {/* app.orionflow.in opens on OrionFlow Inspect (FAI). The
                assembly watchdog lives at /watchdog and the design studio
                at /studio; a gallery deep link (/?example=<id>) is a studio
                link and is forwarded there. */}
            <Route
                path="/"
                element={
                    <ProtectedRoute>
                        <HomeRoute />
                    </ProtectedRoute>
                }
            />
            <Route path="/p/:pid" element={<ProtectedRoute><ProjectPage /></ProtectedRoute>} />
            <Route path="/r/:rid" element={<ProtectedRoute><InspectWorkspace /></ProtectedRoute>} />
            <Route path="/compare/:pid" element={<ProtectedRoute><ComparePage /></ProtectedRoute>} />
            <Route path="/assembly" element={<ProtectedRoute><AssemblyPage /></ProtectedRoute>} />
            <Route path="/assembly/:id" element={<ProtectedRoute><AssemblyPage /></ProtectedRoute>} />
            <Route path="/watchdog" element={<ProtectedRoute><WatchdogPage /></ProtectedRoute>} />
            {/* OrionFlow Review: robot hardware review (projects -> revisions -> lenses) */}
            <Route path="/review" element={<ProtectedRoute><ReviewHome /></ProtectedRoute>} />
            <Route path="/review/p/:pid" element={<ProtectedRoute><ReviewProject /></ProtectedRoute>} />
            <Route path="/review/r/:rid" element={<ProtectedRoute><ReviewWorkspace /></ProtectedRoute>} />
            <Route path="/review/r/:rid/:lens" element={<ProtectedRoute><ReviewWorkspace /></ProtectedRoute>} />
            <Route
                path="/studio"
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
            <Route
                path="/account"
                element={
                    <ProtectedRoute>
                        <AccountPage />
                    </ProtectedRoute>
                }
            />
            {/* The one step between "Try OrionFlow" on the landing page and
                the studio: name, company, work email, then sign-up with the
                first two already filled in. Public by design — it runs before
                anyone has an account. */}
            <Route path="/start" element={<StartPage />} />
            <Route path="/auth" element={<AuthPage />} />
            <Route path="/auth/handoff" element={<AuthHandoffPage />} />
            <Route path="/auth/verify-email" element={<VerifyEmailPage />} />
            <Route path="/auth/reset-password" element={<ResetPasswordPage />} />
            <Route path="/auth/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/privacy" element={<PrivacyPage />} />
            <Route path="/terms" element={<TermsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
    );
}
