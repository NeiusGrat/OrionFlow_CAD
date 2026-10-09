import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import OrionFlowLogo from '../components/OrionFlowLogo';
import { useAuthStore } from '../store/authStore';

/** Landing of the orionflow.in sign-in form.
 *
 *  The marketing site signs the visitor in against the API, then sends them
 *  here with the token pair in the URL *fragment* — fragments are never sent
 *  to a server or written to access logs. The fragment is wiped from history
 *  before anything else happens, the access token is checked against /me, and
 *  only then is the session stored.
 */
export default function AuthHandoffPage() {
    const navigate = useNavigate();
    const adoptTokens = useAuthStore((s) => s.adoptTokens);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const params = new URLSearchParams(window.location.hash.slice(1));
        window.history.replaceState(null, '', window.location.pathname);
        const access = params.get('access_token');
        const refresh = params.get('refresh_token');
        // Only same-app paths: an absolute URL here would be an open redirect.
        const next = params.get('next') || '/';
        const safeNext = next.startsWith('/') && !next.startsWith('//') ? next : '/';
        if (!access || !refresh) {
            setError('This sign-in link is incomplete. Please sign in again.');
            return;
        }
        adoptTokens(access, refresh)
            .then(() => navigate(safeNext, { replace: true }))
            .catch(() => setError('That session could not be confirmed. Please sign in again.'));
    }, [adoptTokens, navigate]);

    return (
        <div style={{
            minHeight: '100vh', width: '100%', background: '#fff', color: '#0A0A0A',
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            justifyContent: 'center', gap: '18px', padding: '48px', textAlign: 'center',
        }}>
            <OrionFlowLogo size={40} theme="mono" />
            <p style={{ fontSize: '15px', color: error ? '#B42318' : '#555', maxWidth: '420px' }}>
                {error || 'Signing you in…'}
            </p>
            {error && (
                <Link to="/auth" style={{
                    background: '#0A0A0A', color: '#fff', padding: '10px 22px',
                    textDecoration: 'none', fontSize: '14px',
                }}>
                    Go to sign in
                </Link>
            )}
        </div>
    );
}
