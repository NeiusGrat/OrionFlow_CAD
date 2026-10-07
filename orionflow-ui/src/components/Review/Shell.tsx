/** Shared chrome for every Review page: the .rv root, the top bar and the mark. */
import { Link } from 'react-router-dom';
import OrionFlowLogo from '../OrionFlowLogo';
import '../../styles/review.css';

export function Brand() {
    return (
        <Link to="/review" className="rv-brand" aria-label="OrionFlow Review home">
            <OrionFlowLogo size={18} theme="mono" />
            ORIONFLOW
        </Link>
    );
}

export function ReviewRoot({ children, dark = false }: { children: React.ReactNode; dark?: boolean }) {
    return (
        <div className="rv" data-theme={dark ? 'dark' : 'light'}>
            {children}
        </div>
    );
}

export function StepList({ steps }: { steps: { key: string; label: string; state: string; seconds: number | null; note: string }[] }) {
    const mark: Record<string, string> = { done: '✓', failed: '■', skipped: '–', pending: '·', running: '' };
    return (
        <ol className="rv-steps">
            {steps.map((s) => (
                <li key={s.key} data-state={s.state}>
                    <span className="st" aria-label={s.state}>{mark[s.state] ?? ''}</span>
                    <span>{s.label}</span>
                    <span className="note" title={s.note}>{s.note}</span>
                    <span className="num">{s.seconds !== null ? `${s.seconds.toFixed(1)} s` : ''}</span>
                </li>
            ))}
        </ol>
    );
}
