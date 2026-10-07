/**
 * A project: its revisions as a timeline, and the upload of a new one.
 *
 * Upload is one drop zone for files, a folder or a zip. Every file is hashed
 * and classified on the server; the table lets the user correct the type and
 * choose which STEP is the assembly before running. A running review streams
 * its steps (polled) and never blocks the page.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Brand, ReviewRoot, StepList } from '../../components/Review/Shell';
import {
    FILE_KINDS, createRevision, deleteFile, fmtBytes, getProject, runReview, setFileKind, setPrimary,
    type FileKind, type Project, type Revision,
} from '../../services/reviewApi';

/** Files from a drop, walking dropped folders (Chrome/Edge/Safari/Firefox all expose entries). */
async function filesFromDrop(dt: DataTransfer): Promise<File[]> {
    const items = Array.from(dt.items ?? []);
    const entries = items.map((i) => (i as DataTransferItem & { webkitGetAsEntry?: () => FileSystemEntry | null }).webkitGetAsEntry?.()).filter(Boolean) as FileSystemEntry[];
    if (!entries.length) return Array.from(dt.files);
    const out: File[] = [];
    const walk = async (e: FileSystemEntry, prefix: string): Promise<void> => {
        if (e.isFile) {
            const f = await new Promise<File>((res, rej) => (e as FileSystemFileEntry).file(res, rej));
            out.push(new File([f], `${prefix}${f.name}`, { type: f.type }));
        } else if (e.isDirectory) {
            const reader = (e as FileSystemDirectoryEntry).createReader();
            let batch: FileSystemEntry[];
            do {
                batch = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej));
                for (const c of batch) await walk(c, `${prefix}${e.name}/`);
            } while (batch.length);
        }
    };
    for (const e of entries) await walk(e, '');
    return out.filter((f) => !f.name.split('/').pop()!.startsWith('.'));
}

function RevisionRow({ rev, onChange }: { rev: Revision; onChange: (r: Revision) => void }) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const steps = rev.files.filter((f) => f.kind === 'step');
    const primary = rev.primary_file_id ?? [...steps].sort((a, b) => b.size - a.size)[0]?.id;
    const running = rev.status === 'queued' || rev.status === 'running';

    const act = async (fn: () => Promise<unknown>) => {
        setBusy(true);
        setError('');
        try {
            await fn();
        } catch (e) {
            setError(String((e as Error).message));
        } finally {
            setBusy(false);
        }
    };

    return (
        <section className="rv-rev">
            <div>
                <span className="label">{rev.status}</span>
                <h3>{rev.label}</h3>
                {rev.git_repo && (
                    <div className="mono muted" style={{ fontSize: 11, marginTop: 4 }}>
                        {rev.git_repo}@{rev.git_ref}
                    </div>
                )}
                {rev.created_at && <div className="mono muted" style={{ fontSize: 11 }}>{new Date(rev.created_at).toLocaleString()}</div>}
            </div>
            <div style={{ minWidth: 0 }}>
                <table className="rv-table">
                    <thead>
                        <tr><th>File</th><th>Type</th><th className="num">Size</th><th>SHA-256</th><th>Assembly</th><th /></tr>
                    </thead>
                    <tbody>
                        {rev.files.map((f) => (
                            <tr key={f.id}>
                                <td style={{ overflowWrap: 'anywhere' }}>{f.name}</td>
                                <td>
                                    <select value={f.kind} disabled={running || busy} aria-label={`Type of ${f.name}`}
                                        onChange={(e) => act(async () => {
                                            await setFileKind(rev.id, f.id, e.target.value as FileKind);
                                            onChange({ ...rev, files: rev.files.map((x) => x.id === f.id ? { ...x, kind: e.target.value as FileKind, kind_source: 'user' } : x) });
                                        })}>
                                        {FILE_KINDS.map((k) => <option key={k} value={k}>{k.toUpperCase()}</option>)}
                                    </select>
                                    {f.kind_source === 'user' && <span className="muted" title="changed by you"> ✎</span>}
                                </td>
                                <td className="num">{fmtBytes(f.size)}</td>
                                <td className="mono muted" title={f.sha256} style={{ fontSize: 11 }}>{f.sha256.slice(0, 12)}…</td>
                                <td>
                                    {f.kind === 'step' && (
                                        <input type="radio" name={`primary-${rev.id}`} checked={primary === f.id} disabled={running || busy}
                                            aria-label={`Analyse ${f.name}`}
                                            onChange={() => act(async () => onChange(await setPrimary(rev.id, f.id)))} />
                                    )}
                                </td>
                                <td>
                                    {rev.status === 'draft' && (
                                        <button className="icon-btn" aria-label={`Remove ${f.name}`} disabled={busy}
                                            onClick={() => act(async () => {
                                                await deleteFile(rev.id, f.id);
                                                onChange({ ...rev, files: rev.files.filter((x) => x.id !== f.id) });
                                            })}>×</button>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {rev.job && (rev.job.state !== 'done' || rev.status !== 'done') && (
                    <div style={{ marginTop: 12 }}>
                        <StepList steps={rev.job.steps} />
                        {rev.job.error && <p className="rv-err">{rev.job.error}</p>}
                    </div>
                )}
                {rev.stats && (
                    <p className="mono muted" style={{ fontSize: 11, marginTop: 10 }}>
                        {rev.stats.parts} parts · {rev.stats.instances} instances · {rev.stats.triangles.toLocaleString('en-US')} triangles
                        {rev.job?.steps && ` · ${rev.job.steps.reduce((a, s) => a + (s.seconds ?? 0), 0).toFixed(1)} s`}
                    </p>
                )}
                {error && <p className="rv-err">{error}</p>}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'stretch' }}>
                {rev.status === 'done' && <Link className="btn btn--solid" to={`/review/r/${rev.id}/model`}>Open review →</Link>}
                <button className="btn" disabled={running || busy || !steps.length}
                    title={!steps.length ? 'Add a STEP file first' : undefined}
                    onClick={() => act(async () => {
                        const job = await runReview(rev.id);
                        onChange({ ...rev, status: 'queued', job });
                    })}>
                    {running ? 'Running…' : rev.status === 'draft' ? 'Run review' : 'Run again'}
                </button>
            </div>
        </section>
    );
}

export default function ReviewProject() {
    const { pid = '' } = useParams();
    const [project, setProject] = useState<Project | null>(null);
    const [error, setError] = useState('');
    const [over, setOver] = useState(false);
    const [label, setLabel] = useState('');
    const [uploading, setUploading] = useState('');
    const fileInput = useRef<HTMLInputElement>(null);
    const dirInput = useRef<HTMLInputElement>(null);

    const load = useCallback(() => getProject(pid).then(setProject).catch((e) => setError(String(e.message ?? e))), [pid]);
    useEffect(() => {
        load();
    }, [load]);

    // poll while anything is running
    const active = project?.revisions.some((r) => r.status === 'queued' || r.status === 'running');
    useEffect(() => {
        if (!active) return;
        const t = setInterval(load, 1200);
        return () => clearInterval(t);
    }, [active, load]);

    const upload = async (files: File[]) => {
        if (!files.length || !project) return;
        setUploading(`Uploading ${files.length} file${files.length === 1 ? '' : 's'} (${fmtBytes(files.reduce((a, f) => a + f.size, 0))})…`);
        setError('');
        try {
            const nextLabel = label.trim() || `rev ${String.fromCharCode(65 + project.revisions.length)}`;
            await createRevision(project.id, files, nextLabel);
            setLabel('');
            await load();
        } catch (e) {
            setError(String((e as Error).message));
        } finally {
            setUploading('');
        }
    };

    const replace = (r: Revision) => setProject((p) => p && { ...p, revisions: p.revisions.map((x) => (x.id === r.id ? r : x)) });

    return (
        <ReviewRoot>
            <header className="rv-top">
                <Brand />
                <nav className="rv-crumbs">
                    <Link className="crumb" to="/review">Projects</Link>
                    <span className="sep">/</span>
                    <span className="crumb">{project?.name ?? '…'}</span>
                </nav>
            </header>
            <main className="rv-page">
                <div className="rv-page__in">
                    <span className="label">Project</span>
                    <h1>{project?.name ?? ' '}</h1>
                    {project?.description && <p className="rv-page__lead">{project.description}</p>}
                    {error && <p className="rv-err">{error}</p>}

                    <section style={{ marginTop: 32 }}>
                        <span className="label">New revision</span>
                        <div className="rv-page__actions" style={{ marginTop: 10 }}>
                            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Label, e.g. rev B or v2.0.0" maxLength={120}
                                aria-label="Revision label" style={{ height: 32, width: 240, border: '1px solid var(--line-2)', borderRadius: 2, padding: '0 10px' }} />
                        </div>
                        <div
                            className={`rv-drop${over ? ' is-over' : ''}`}
                            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
                            onDragLeave={() => setOver(false)}
                            onDrop={async (e) => { e.preventDefault(); setOver(false); upload(await filesFromDrop(e.dataTransfer)); }}
                            onClick={() => fileInput.current?.click()}
                            role="button"
                            tabIndex={0}
                            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileInput.current?.click(); }}
                        >
                            <b>{uploading || 'Drop a package here'}</b>
                            STEP assembly, BOM (CSV, XLSX, Markdown), drawings and instructions (PDF), URDF or MJCF — files, a folder or a zip.
                            <div style={{ marginTop: 10 }}>
                                <button type="button" className="btn" onClick={(e) => { e.stopPropagation(); dirInput.current?.click(); }}>Choose a folder</button>
                            </div>
                        </div>
                        <input ref={fileInput} type="file" multiple hidden onChange={(e) => upload(Array.from(e.target.files ?? []))} />
                        <input ref={dirInput} type="file" hidden
                            {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
                            onChange={(e) => upload(Array.from(e.target.files ?? []))} />
                    </section>

                    <div className="rv-revs">
                        {project?.revisions.length === 0 && <div className="rv-empty"><b>No revisions yet</b>Upload a package to create the first one.</div>}
                        {[...(project?.revisions ?? [])].reverse().map((r) => <RevisionRow key={r.id} rev={r} onChange={replace} />)}
                    </div>
                </div>
            </main>
        </ReviewRoot>
    );
}
