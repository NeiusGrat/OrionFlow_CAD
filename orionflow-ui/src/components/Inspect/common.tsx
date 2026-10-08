/** App bar, drop zone and the "New inspection" dialog shared by Inspect screens. */
import { useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { LogOut, X } from "lucide-react";
import { createProject, createRevision } from "../../services/faiApi";
import { useAuthStore } from "../../store/authStore";

/** The mark: a balloon with a leader, the one gesture the product is about. */
export function Mark({ size = 22 }: { size?: number }) {
    return (
        <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="9" cy="9" r="7.2" fill="#000" />
            <text x="9" y="12.4" textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize="9.5" fontWeight="600" fill="#fff">1</text>
            <path d="M14.2 14.2 L21 21" stroke="#000" strokeWidth="1.6" />
            <rect x="19.4" y="19.4" width="3.2" height="3.2" fill="#000" />
        </svg>
    );
}

export function AppBar({ crumbs, right }: { crumbs?: ReactNode; right?: ReactNode }) {
    const logout = useAuthStore((s) => s.logout);
    const user = useAuthStore((s) => s.user);
    return (
        <header className="in-bar">
            <Link to="/" className="in-mark"><Mark /> OrionFlow Inspect</Link>
            {crumbs && <nav className="in-crumbs" aria-label="Breadcrumb"><span className="sep">/</span>{crumbs}</nav>}
            <div className="right">
                <Link to="/" className="in-btn quiet sm">Projects</Link>
                <Link to="/assembly" className="in-btn quiet sm">Assembly check</Link>
                <Link to="/review" className="in-btn quiet sm">Robot review</Link>
                {right}
                <button className="in-btn quiet sm" onClick={logout} title={user?.email ? `Sign out ${user.email}` : "Sign out"} aria-label="Sign out">
                    <LogOut size={14} />
                </button>
            </div>
        </header>
    );
}

export function Drop({ label, hint, accept, file, required, onFile }: {
    label: string; hint: string; accept: string; file: File | null; required?: boolean; onFile: (f: File | null) => void;
}) {
    const input = useRef<HTMLInputElement>(null);
    const [over, setOver] = useState(false);
    return (
        <div
            role="button"
            tabIndex={0}
            className={`in-drop${file ? " filled" : ""}${over ? " over" : ""}`}
            onClick={() => input.current?.click()}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.current?.click(); } }}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) onFile(f); }}
        >
            <div className="k">
                <b>{label}</b>
                <span>{file ? `${file.name} (${(file.size / 1024).toFixed(0)} KB)` : hint}</span>
            </div>
            {file ? (
                <button className="in-btn quiet sm" aria-label={`Remove ${label}`} onClick={(e) => { e.stopPropagation(); onFile(null); }}><X size={14} /></button>
            ) : (
                <span className="tag">{required ? "required" : "optional"}</span>
            )}
            <input ref={input} type="file" hidden accept={accept}
                   onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />
        </div>
    );
}

/** New inspection: for a new part (creates the project) or a new revision of one. */
export function NewInspection({ projectId, onClose }: { projectId?: string; onClose: () => void }) {
    const navigate = useNavigate();
    const [drawing, setDrawing] = useState<File | null>(null);
    const [step, setStep] = useState<File | null>(null);
    const [bom, setBom] = useState<File | null>(null);
    const [partNumber, setPartNumber] = useState("");
    const [customer, setCustomer] = useState("");
    const [standard, setStandard] = useState("ISO GPS");
    const [gclass, setGclass] = useState("");
    const [po, setPo] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);

    async function run() {
        if (!drawing) return;
        setBusy(true);
        setError(null);
        try {
            const pid = projectId ?? (await createProject({
                part_number: partNumber || drawing.name.replace(/\.pdf$/i, ""), customer,
            })).id;
            const rev = await createRevision(pid, { drawing, step, bom, standard, general_class: gclass, po_number: po });
            navigate(`/r/${rev.id}`);
        } catch (e) {
            setError((e as Error).message);
            setBusy(false);
        }
    }

    return (
        <div className="in-scrim" role="dialog" aria-modal="true" aria-labelledby="new-insp" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
            <div className="in-modal">
                <header>
                    <h2 id="new-insp">{projectId ? "New revision" : "New inspection"}</h2>
                    <button className="in-btn quiet sm" onClick={onClose} aria-label="Close"><X size={15} /></button>
                </header>
                <div className="body">
                    {!projectId && (
                        <div className="in-row">
                            <label className="in-field"><span>Part number</span>
                                <input className="in-input" value={partNumber} onChange={(e) => setPartNumber(e.target.value)} placeholder="Read from the title block if blank" /></label>
                            <label className="in-field"><span>Customer</span>
                                <input className="in-input" value={customer} onChange={(e) => setCustomer(e.target.value)} placeholder="e.g. Acme Aerostructures" /></label>
                        </div>
                    )}
                    <Drop label="Drawing" hint="PDF exported from CAD — text layer preferred" accept=".pdf" file={drawing} required onFile={setDrawing} />
                    <Drop label="3D model" hint="STEP (.step, .stp) — to cross-check drawing values against the model" accept=".step,.stp" file={step} onFile={setStep} />
                    <Drop label="BOM or PO" hint="CSV with part number, revision, material" accept=".csv,.tsv,.txt" file={bom} onFile={setBom} />
                    <div className="in-row" style={{ marginTop: 8 }}>
                        <label className="in-field"><span>Standard</span>
                            <select className="in-select" value={standard} onChange={(e) => setStandard(e.target.value)}>
                                <option value="ISO GPS">ISO GPS (ISO 1101 / 8015)</option>
                                <option value="ASME Y14.5">ASME Y14.5</option>
                            </select></label>
                        <label className="in-field"><span>General tolerance</span>
                            <select className="in-select" value={gclass} onChange={(e) => setGclass(e.target.value)}>
                                <option value="">From the drawing's note</option>
                                <option value="f">ISO 2768-f (fine)</option>
                                <option value="m">ISO 2768-m (medium)</option>
                                <option value="c">ISO 2768-c (coarse)</option>
                                <option value="v">ISO 2768-v (very coarse)</option>
                            </select></label>
                    </div>
                    <label className="in-field"><span>PO number</span>
                        <input className="in-input" value={po} onChange={(e) => setPo(e.target.value)} placeholder="Optional — goes on Form 1" /></label>
                    {error && <div className="in-error">{error}</div>}
                </div>
                <footer>
                    <button className="in-btn line" onClick={onClose}>Cancel</button>
                    <button className="in-btn" disabled={!drawing || busy} onClick={run}>{busy ? "Uploading…" : "Run inspection"}</button>
                </footer>
            </div>
        </div>
    );
}
