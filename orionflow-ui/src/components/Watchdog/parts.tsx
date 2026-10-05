/** Small pieces every watchdog module shares. */
import { useRef, useState } from "react";
import { X } from "lucide-react";
import type { Stage } from "../../services/watchdogApi";
import { STAGES } from "../../lib/watchdog";

const STATUS_WORD: Record<string, string> = {
    PASS: "passed", FAIL: "found problems", WARNING: "found warnings", SKIPPED: "skipped",
    ERROR: "errored", RUNNING: "running", DONE: "done",
};

/** The fifteen checks of an assembly run, as one line of lamps. */
export function StageLine({ stages, current, running }: { stages?: Stage[]; current?: string | null; running?: boolean }) {
    const by = new Map((stages ?? []).map((s) => [s.stage, s]));
    let reached = true;
    return (
        <div className="wd-stages" role="list" aria-label="Verification stages">
            {STAGES.map(([id, key, label]) => {
                const s = by.get(key);
                let status: string = s?.status ?? "";
                if (!s && running) {
                    if (key === current) { status = "RUNNING"; reached = false; }
                    else if (reached && current) status = "DONE";
                }
                const why = s?.reason ? ` — ${s.reason}` : s?.duration_s != null ? ` — ${s.duration_s}s` : "";
                return (
                    <div key={key} className="wd-stage" data-s={status} role="listitem"
                         title={`${label}: ${STATUS_WORD[status] ?? "waiting"}${why}`}>
                        <div className="bar" />
                        <div className="name"><b>{id}</b>{label}</div>
                    </div>
                );
            })}
        </div>
    );
}

/** One file slot in an upload bay; drop or click. */
export function DropSlot({ label, hint, accept, many, files, required, onFiles }: {
    label: string; hint?: string; accept: string; many?: boolean; files: File[]; required?: boolean;
    onFiles: (f: File[]) => void;
}) {
    const input = useRef<HTMLInputElement>(null);
    const [over, setOver] = useState(false);
    const names = files.map((f) => f.name).join(", ");
    return (
        <div
            className={`wd-drop${files.length ? " filled" : ""}${over ? " over" : ""}`}
            role="button"
            tabIndex={0}
            onClick={() => input.current?.click()}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.current?.click(); } }}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
                e.preventDefault();
                setOver(false);
                const list = [...e.dataTransfer.files];
                if (list.length) onFiles(many ? [...files, ...list] : list.slice(0, 1));
            }}
        >
            <div className="k">
                <span>{label}</span>
                <em>{names || hint || accept.replace(/,/g, " ")}</em>
            </div>
            {required && !files.length && <span className="req">required</span>}
            {files.length > 0 && (
                <button className="x" aria-label={`Remove ${label}`} onClick={(e) => { e.stopPropagation(); onFiles([]); }}>
                    <X size={14} />
                </button>
            )}
            <input
                ref={input}
                type="file"
                hidden
                accept={accept}
                multiple={many}
                onChange={(e) => {
                    const list = [...(e.target.files ?? [])];
                    if (list.length) onFiles(many ? [...files, ...list] : list.slice(0, 1));
                    e.target.value = "";
                }}
            />
        </div>
    );
}

