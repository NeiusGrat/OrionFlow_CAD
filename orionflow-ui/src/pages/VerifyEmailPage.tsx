import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import OrionFlowLogo from '../components/OrionFlowLogo';
import { apiVerifyEmail } from '../services/authApi';

export default function VerifyEmailPage() {
    const [searchParams] = useSearchParams();
    const token = searchParams.get('token') || '';
    const [status, setStatus] = useState<'working' | 'ok' | 'error'>('working');
    const [message, setMessage] = useState('Verifying your email…');

    useEffect(() => {
        if (!token) {
            setStatus('error');
            setMessage('Missing verification token. Use the link from your email.');
            return;
        }
        apiVerifyEmail(token)
            .then(() => {
                setStatus('ok');
                setMessage('Email verified! Your account is now active.');
            })
            .catch((err: Error) => {
                setStatus('error');
                setMessage(err.message || 'Verification failed.');
            });
    }, [token]);

    return (
        <div style={{
            minHeight: '100vh',
            width: '100%',
            background: '#17140F',
            color: '#EFE7D8',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '20px',
            padding: '48px',
            textAlign: 'center',
        }}>
            <OrionFlowLogo size={48} />
            <h1 style={{ fontSize: '24px', fontWeight: 700 }}>Email verification</h1>
            <p style={{
                color: status === 'error' ? '#DE8871' : status === 'ok' ? '#7FB894' : '#A79D8B',
                fontSize: '15px',
                maxWidth: '420px',
            }}>
                {message}
            </p>
            {status !== 'working' && (
                <Link to="/auth" style={{
                    background: '#8AA5E6',
                    color: '#fff',
                    padding: '10px 24px',
                    borderRadius: '8px',
                    textDecoration: 'none',
                    fontSize: '14px',
                }}>
                    Go to sign in
                </Link>
            )}
        </div>
    );
}
