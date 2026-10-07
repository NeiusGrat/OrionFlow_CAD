/** Review home: the user's projects, a new project, and the YUBI demo. */
import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Brand, ReviewRoot } from '../../components/Review/Shell';
import { createProject, createYubiDemo, listProjects, type ProjectSummary } from '../../services/reviewApi';

export default function ReviewHome() {
    const nav = useNavigate();
    const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
    const [error, setError] = useState('');
    const [name, setName] = useState('');
    const [busy, setBusy] = useState<'' | 'new' | 'demo'>('');

    useEffect(() => {
        listProjects().then(setProjects).catch((e) => setError(String(e.message ?? e)));
    }, []);

    const create = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!name.trim()) return;
        setBusy('new');
        try {
            const p = await createProject(name.trim());
            nav(`/review/p/${p.id}`);
        } catch (err) {
            setError(String((err as Error).message));
            setBusy('');
        }
    };

    const demo = async () => {
        setBusy('demo');
        setError('');
        try {
            const p = await createYubiDemo();
            nav(`/review/p/${p.id}`);
        } catch (err) {
            setError(String((err as Error).message));
            setBusy('');
        }
    };

    return (
        <ReviewRoot>
            <header className="rv-top">
                <Brand />
                <span className="muted">Review</span>
                <span style={{ marginLeft: 'auto' }} />
                <Link className="btn btn--ghost" to="/">Inspect</Link>
                <Link className="btn btn--ghost" to="/watchdog">Watchdog</Link>
            </header>
            <main className="rv-page">
                <div className="rv-page__in">
                    <span className="label">Projects</span>
                    <h1>Robot hardware review</h1>
                    <p className="rv-page__lead">
                        Upload a robot's STEP assembly with its BOM, drawings and sim model. OrionFlow measures the geometry,
                        cross-checks every document against it and links each finding to its evidence.
                    </p>
                    <form className="rv-page__actions" onSubmit={create}>
                        <input
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder="New project name"
                            aria-label="New project name"
                            maxLength={200}
                            style={{ height: 36, width: 280, border: '1px solid var(--line-2)', borderRadius: 2, padding: '0 10px' }}
                        />
                        <button className="btn btn--solid btn--lg" disabled={!name.trim() || !!busy}>
                            {busy === 'new' ? 'Creating…' : 'Create project'}
                        </button>
                        <button type="button" className="btn btn--lg" onClick={demo} disabled={!!busy}
                            title="Fetches the YUBI gripper from github.com/Toyota/yubi-hw at tags v1.2.0 and v2.0.0">
                            {busy === 'demo' ? 'Fetching from GitHub…' : 'Load YUBI gripper demo'}
                        </button>
                    </form>
                    {error && <p className="rv-err">{error}</p>}

                    {projects === null && !error && <p className="muted" style={{ marginTop: 28 }}>Loading…</p>}
                    {projects && projects.length === 0 && (
                        <div className="rv-empty" style={{ marginTop: 28, border: '1px solid var(--line)' }}>
                            <b>No projects yet</b>
                            Create one, or load the YUBI gripper to see a real review end to end.
                        </div>
                    )}
                    {projects && projects.length > 0 && (
                        <div className="rv-grid">
                            {projects.map((p) => (
                                <Link key={p.id} to={`/review/p/${p.id}`} className="rv-card">
                                    <span className="label">{p.revision_count} revision{p.revision_count === 1 ? '' : 's'}</span>
                                    <h2>{p.name}</h2>
                                    <p>{p.description || 'No description'}</p>
                                    <p className="mono" style={{ marginTop: 10, fontSize: 11 }}>{new Date(p.created_at).toLocaleDateString()}</p>
                                </Link>
                            ))}
                        </div>
                    )}
                    <p className="muted" style={{ marginTop: 40, fontSize: 11 }}>
                        Demo data: YUBI hardware by Toyota Motor Corporation, CERN-OHL-W v2 —{' '}
                        <a href="https://github.com/Toyota/yubi-hw" target="_blank" rel="noopener" style={{ textDecoration: 'underline' }}>github.com/Toyota/yubi-hw</a>
                    </p>
                </div>
            </main>
        </ReviewRoot>
    );
}
