/**
 * OrionFlow Watchdog — the engineering verification console.
 *
 * One place where an engineer hands over the product's definition (assembly,
 * BOM, previous revision, drawings, robot model) and gets back what disagrees
 * with what, measured. Three engines behind one sign-in:
 *
 *   Assembly  interface_check — interfaces, clearance, BOM, revisions, drawings, URDF drift
 *   Drawings  drawcheck       — incoming drawing check and query list
 *   Robot     robocheck + embodiment — robot-model physics, spec-to-robot compile
 *
 * The design studio (text-to-CAD) stays one click away at /studio.
 */
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Boxes, Bot, FileText, LogOut, PenTool } from "lucide-react";
import OrionFlowLogo from "../components/OrionFlowLogo";
import AssemblyWatch from "../components/Watchdog/AssemblyWatch";
import DrawingWatch from "../components/Watchdog/DrawingWatch";
import RobotWatch from "../components/Watchdog/RobotWatch";
import { getModules, type Modules } from "../services/watchdogApi";
import { useAuthStore } from "../store/authStore";
import "../styles/watchdog.css";

type Tab = "assembly" | "drawing" | "robot";
const TABS: { id: Tab; label: string; icon: typeof Boxes }[] = [
    { id: "assembly", label: "Assembly", icon: Boxes },
    { id: "drawing", label: "Drawings", icon: FileText },
    { id: "robot", label: "Robot model", icon: Bot },
];

export default function WatchdogPage() {
    const [params, setParams] = useSearchParams();
    const tab = (TABS.find((t) => t.id === params.get("m"))?.id ?? "assembly") as Tab;
    const [modules, setModules] = useState<Modules | null>(null);
    const [modError, setModError] = useState<string | null>(null);
    const user = useAuthStore((s) => s.user);
    const logout = useAuthStore((s) => s.logout);

    useEffect(() => {
        document.title = "OrionFlow Watchdog";
        getModules().then(setModules).catch((e) => setModError(e.message));
    }, []);

    const status = (id: Tab) => modules?.[id];
    const pending = !modules && !modError;

    return (
        <div className="wd">
            <header className="wd-top">
                <div className="wd-brand">
                    <OrionFlowLogo size={26} theme="dark" />
                    <span>OrionFlow <small>Watchdog</small></span>
                </div>
                <nav className="wd-tabs" role="tablist" aria-label="What to check">
                    {TABS.map(({ id, label, icon: Icon }) => {
                        const s = status(id);
                        return (
                            <button key={id} role="tab" className="wd-tab" aria-selected={tab === id}
                                    title={s ? (s.available ? s.what : s.reason ?? "unavailable") : undefined}
                                    onClick={() => setParams({ m: id }, { replace: true })}>
                                <Icon size={15} />
                                {label}
                                <span className={`dot${s ? (s.available ? " on" : " off") : ""}`} />
                            </button>
                        );
                    })}
                </nav>
                <div className="wd-top-right">
                    {modules && (
                        <span className="wd-chip" title="The language model only reads messy documents and writes summaries; geometry and rules decide every finding.">
                            {modules.llm.configured ? <>Language model <b>{modules.llm.name}</b></> : <>Deterministic only</>}
                        </span>
                    )}
                    <Link className="wd-link" to="/">Inspect</Link>
                    <Link className="wd-link" to="/studio"><PenTool size={14} /> Design studio</Link>
                    <button className="wd-link" onClick={logout} title={user?.email ?? "Sign out"} aria-label="Sign out">
                        <LogOut size={14} />
                    </button>
                </div>
            </header>

            {modError ? (
                <div className="wd-view-empty" style={{ position: "relative", gridRow: "2 / 4" }}>
                    <h2>The verification service is not reachable</h2>
                    <p>{modError}</p>
                </div>
            ) : pending ? (
                <div className="wd-view-empty" style={{ position: "relative", gridRow: "2 / 4" }}><p>Connecting to the verification engines…</p></div>
            ) : tab === "assembly" ? (
                <AssemblyWatch available={!!modules?.assembly.available} reason={modules?.assembly.reason ?? null} />
            ) : tab === "drawing" ? (
                <DrawingWatch available={!!modules?.drawing.available} reason={modules?.drawing.reason ?? null} />
            ) : (
                <RobotWatch available={!!modules?.robot.available} reason={modules?.robot.reason ?? null} />
            )}
        </div>
    );
}
