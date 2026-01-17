import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import OrionFlowLogo from '../OrionFlowLogo';

export default function FooterCTASection() {
    return (
        <section style={{
            padding: '120px 48px 80px',
            position: 'relative',
        }}>
            <div style={{
                maxWidth: '900px',
                margin: '0 auto',
                textAlign: 'center',
                position: 'relative',
            }}>
                {/* Background glow */}
                <div style={{
                    position: 'absolute',
                    width: '500px',
                    height: '500px',
                    borderRadius: '50%',
                    background: 'radial-gradient(circle, rgba(59, 130, 246, 0.1) 0%, transparent 70%)',
                    filter: 'blur(60px)',
                    top: '50%',
                    left: '50%',
                    transform: 'translate(-50%, -50%)',
                    pointerEvents: 'none',
                }} />

                <div style={{ position: 'relative', zIndex: 1 }}>
                    {/* Logo */}
                    <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '32px' }}>
                        <OrionFlowLogo size={64} />
                    </div>

                    {/* Headline */}
                    <h2 style={{
                        fontSize: '48px',
                        fontWeight: 700,
                        letterSpacing: '-0.02em',
                        marginBottom: '16px',
                        lineHeight: 1.2,
                    }}>
                        Build parts — not meshes.
                    </h2>

                    <p style={{
                        fontSize: '20px',
                        color: '#94a3b8',
                        marginBottom: '40px',
                        maxWidth: '600px',
                        margin: '0 auto 40px',
                    }}>
                        Start designing parametric CAD in the browser.
                    </p>

                    {/* CTA */}
                    <Link to="/auth" style={{ textDecoration: 'none' }}>
                        <button style={{
                            background: 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
                            color: 'white',
                            padding: '18px 40px',
                            borderRadius: '14px',
                            fontWeight: 600,
                            fontSize: '17px',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '12px',
                            border: 'none',
                            cursor: 'pointer',
                            boxShadow: '0 8px 32px rgba(59, 130, 246, 0.4)',
                            transition: 'all 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
                        }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.transform = 'translateY(-3px)';
                                e.currentTarget.style.boxShadow = '0 12px 40px rgba(59, 130, 246, 0.5)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.transform = 'translateY(0)';
                                e.currentTarget.style.boxShadow = '0 8px 32px rgba(59, 130, 246, 0.4)';
                            }}
                        >
                            Start Designing Free
                            <ArrowRight size={20} />
                        </button>
                    </Link>
                </div>
            </div>

            {/* Footer */}
            <div style={{
                marginTop: '80px',
                paddingTop: '32px',
                borderTop: '1px solid rgba(255, 255, 255, 0.06)',
                maxWidth: '1280px',
                margin: '80px auto 0',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <OrionFlowLogo size={28} />
                    <span style={{ color: '#64748b', fontSize: '14px' }}>
                        © 2026 OrionFlow. All rights reserved.
                    </span>
                </div>

                <div style={{ display: 'flex', gap: '24px' }}>
                    {['Privacy', 'Terms', 'Contact'].map((link, i) => (
                        <a key={i} href="#" style={{
                            color: '#64748b',
                            fontSize: '14px',
                            textDecoration: 'none',
                            transition: 'color 0.2s ease',
                        }}
                            onMouseEnter={(e) => e.currentTarget.style.color = '#94a3b8'}
                            onMouseLeave={(e) => e.currentTarget.style.color = '#64748b'}
                        >
                            {link}
                        </a>
                    ))}
                </div>
            </div>
        </section>
    );
}
