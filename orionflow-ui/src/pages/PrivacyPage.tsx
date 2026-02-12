import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import Navbar from '../components/Landing/Navbar';
import Footer from '../components/Landing/Footer';

export default function PrivacyPage() {
    return (
        <div style={{
            minHeight: '100vh',
            background: '#030712',
            color: '#f8fafc',
            overflowX: 'hidden',
        }}>
            <Navbar />

            {/* Content */}
            <section style={{
                padding: '160px 48px 120px',
                position: 'relative',
            }}>
                <div style={{
                    position: 'absolute',
                    inset: 0,
                    background: 'radial-gradient(ellipse 80% 50% at 50% 0%, rgba(59, 130, 246, 0.05) 0%, transparent 50%)',
                    pointerEvents: 'none',
                }} />

                <div style={{ maxWidth: '800px', margin: '0 auto', position: 'relative', zIndex: 1 }}>
                    <Link to="/" style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '8px',
                        color: '#64748b',
                        fontSize: '14px',
                        textDecoration: 'none',
                        marginBottom: '32px',
                        transition: 'color 0.2s ease',
                    }}>
                        <ArrowLeft size={16} />
                        Back to Home
                    </Link>

                    <h1 style={{
                        fontSize: '48px',
                        fontWeight: 800,
                        letterSpacing: '-0.03em',
                        marginBottom: '16px',
                    }}>
                        Privacy Policy
                    </h1>

                    <p style={{
                        color: '#64748b',
                        fontSize: '14px',
                        marginBottom: '48px',
                    }}>
                        Last updated: January 15, 2026
                    </p>

                    <div style={{
                        fontSize: '16px',
                        color: '#cbd5e1',
                        lineHeight: 1.8,
                    }}>
                        <section style={{ marginBottom: '40px' }}>
                            <h2 style={{
                                fontSize: '24px',
                                fontWeight: 600,
                                color: '#f8fafc',
                                marginBottom: '16px',
                            }}>
                                1. Introduction
                            </h2>
                            <p style={{ color: '#94a3b8' }}>
                                OrionFlow ("we", "our", or "us") is committed to protecting your privacy. This Privacy Policy explains how we collect, use, disclose, and safeguard your information when you use our CAD design platform and related services.
                            </p>
                        </section>

                        <section style={{ marginBottom: '40px' }}>
                            <h2 style={{
                                fontSize: '24px',
                                fontWeight: 600,
                                color: '#f8fafc',
                                marginBottom: '16px',
                            }}>
                                2. Information We Collect
                            </h2>
                            <p style={{ color: '#94a3b8', marginBottom: '16px' }}>
                                We collect information you provide directly to us, including:
                            </p>
                            <ul style={{ color: '#94a3b8', paddingLeft: '24px' }}>
                                <li style={{ marginBottom: '8px' }}>Account information (email, name, password)</li>
                                <li style={{ marginBottom: '8px' }}>CAD models and designs you create</li>
                                <li style={{ marginBottom: '8px' }}>Prompts and text inputs used for generation</li>
                                <li style={{ marginBottom: '8px' }}>Usage data and interaction patterns</li>
                                <li style={{ marginBottom: '8px' }}>Payment information (processed securely by third parties)</li>
                            </ul>
                        </section>

                        <section style={{ marginBottom: '40px' }}>
                            <h2 style={{
                                fontSize: '24px',
                                fontWeight: 600,
                                color: '#f8fafc',
                                marginBottom: '16px',
                            }}>
                                3. How We Use Your Information
                            </h2>
                            <p style={{ color: '#94a3b8', marginBottom: '16px' }}>
                                We use the information we collect to:
                            </p>
                            <ul style={{ color: '#94a3b8', paddingLeft: '24px' }}>
                                <li style={{ marginBottom: '8px' }}>Provide and improve our CAD generation services</li>
                                <li style={{ marginBottom: '8px' }}>Process your transactions and send related information</li>
                                <li style={{ marginBottom: '8px' }}>Send you technical notices and support messages</li>
                                <li style={{ marginBottom: '8px' }}>Respond to your comments, questions, and requests</li>
                                <li style={{ marginBottom: '8px' }}>Train and improve our AI models (with your consent)</li>
                            </ul>
                        </section>

                        <section style={{ marginBottom: '40px' }}>
                            <h2 style={{
                                fontSize: '24px',
                                fontWeight: 600,
                                color: '#f8fafc',
                                marginBottom: '16px',
                            }}>
                                4. Data Security
                            </h2>
                            <p style={{ color: '#94a3b8' }}>
                                We implement appropriate technical and organizational measures to protect your personal information against unauthorized access, alteration, disclosure, or destruction. Your CAD designs are encrypted in transit and at rest.
                            </p>
                        </section>

                        <section style={{ marginBottom: '40px' }}>
                            <h2 style={{
                                fontSize: '24px',
                                fontWeight: 600,
                                color: '#f8fafc',
                                marginBottom: '16px',
                            }}>
                                5. Your Rights
                            </h2>
                            <p style={{ color: '#94a3b8', marginBottom: '16px' }}>
                                Depending on your location, you may have certain rights regarding your personal information:
                            </p>
                            <ul style={{ color: '#94a3b8', paddingLeft: '24px' }}>
                                <li style={{ marginBottom: '8px' }}>Access and receive a copy of your data</li>
                                <li style={{ marginBottom: '8px' }}>Request correction of inaccurate data</li>
                                <li style={{ marginBottom: '8px' }}>Request deletion of your data</li>
                                <li style={{ marginBottom: '8px' }}>Object to or restrict processing</li>
                                <li style={{ marginBottom: '8px' }}>Data portability</li>
                            </ul>
                        </section>

                        <section style={{ marginBottom: '40px' }}>
                            <h2 style={{
                                fontSize: '24px',
                                fontWeight: 600,
                                color: '#f8fafc',
                                marginBottom: '16px',
                            }}>
                                6. Cookies and Tracking
                            </h2>
                            <p style={{ color: '#94a3b8' }}>
                                We use cookies and similar tracking technologies to track activity on our service and hold certain information. You can instruct your browser to refuse all cookies or to indicate when a cookie is being sent.
                            </p>
                        </section>

                        <section style={{ marginBottom: '40px' }}>
                            <h2 style={{
                                fontSize: '24px',
                                fontWeight: 600,
                                color: '#f8fafc',
                                marginBottom: '16px',
                            }}>
                                7. Contact Us
                            </h2>
                            <p style={{ color: '#94a3b8' }}>
                                If you have any questions about this Privacy Policy, please contact us at privacy@orionflow.app
                            </p>
                        </section>
                    </div>
                </div>
            </section>

            <Footer />
        </div>
    );
}
