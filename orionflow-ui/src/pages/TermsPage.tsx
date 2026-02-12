import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import Navbar from '../components/Landing/Navbar';
import Footer from '../components/Landing/Footer';

export default function TermsPage() {
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
                        Terms of Service
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
                                1. Acceptance of Terms
                            </h2>
                            <p style={{ color: '#94a3b8' }}>
                                By accessing or using OrionFlow's services, you agree to be bound by these Terms of Service. If you disagree with any part of these terms, you may not access our service.
                            </p>
                        </section>

                        <section style={{ marginBottom: '40px' }}>
                            <h2 style={{
                                fontSize: '24px',
                                fontWeight: 600,
                                color: '#f8fafc',
                                marginBottom: '16px',
                            }}>
                                2. Description of Service
                            </h2>
                            <p style={{ color: '#94a3b8' }}>
                                OrionFlow provides an AI-powered CAD generation platform that converts natural language descriptions into parametric CAD models. Our service includes model generation, editing, export functionality, and related features.
                            </p>
                        </section>

                        <section style={{ marginBottom: '40px' }}>
                            <h2 style={{
                                fontSize: '24px',
                                fontWeight: 600,
                                color: '#f8fafc',
                                marginBottom: '16px',
                            }}>
                                3. User Accounts
                            </h2>
                            <p style={{ color: '#94a3b8', marginBottom: '16px' }}>
                                When you create an account with us, you must provide accurate and complete information. You are responsible for:
                            </p>
                            <ul style={{ color: '#94a3b8', paddingLeft: '24px' }}>
                                <li style={{ marginBottom: '8px' }}>Maintaining the security of your account</li>
                                <li style={{ marginBottom: '8px' }}>All activities that occur under your account</li>
                                <li style={{ marginBottom: '8px' }}>Notifying us immediately of any unauthorized use</li>
                            </ul>
                        </section>

                        <section style={{ marginBottom: '40px' }}>
                            <h2 style={{
                                fontSize: '24px',
                                fontWeight: 600,
                                color: '#f8fafc',
                                marginBottom: '16px',
                            }}>
                                4. Intellectual Property
                            </h2>
                            <p style={{ color: '#94a3b8', marginBottom: '16px' }}>
                                <strong style={{ color: '#f8fafc' }}>Your Content:</strong> You retain all rights to the CAD models and designs you create using our service. By using OrionFlow, you grant us a limited license to process and store your designs for the purpose of providing our service.
                            </p>
                            <p style={{ color: '#94a3b8' }}>
                                <strong style={{ color: '#f8fafc' }}>Our Content:</strong> The OrionFlow platform, including its AI models, user interface, and underlying technology, remains our intellectual property.
                            </p>
                        </section>

                        <section style={{ marginBottom: '40px' }}>
                            <h2 style={{
                                fontSize: '24px',
                                fontWeight: 600,
                                color: '#f8fafc',
                                marginBottom: '16px',
                            }}>
                                5. Acceptable Use
                            </h2>
                            <p style={{ color: '#94a3b8', marginBottom: '16px' }}>
                                You agree not to use OrionFlow to:
                            </p>
                            <ul style={{ color: '#94a3b8', paddingLeft: '24px' }}>
                                <li style={{ marginBottom: '8px' }}>Generate designs for illegal purposes or weapons</li>
                                <li style={{ marginBottom: '8px' }}>Violate any applicable laws or regulations</li>
                                <li style={{ marginBottom: '8px' }}>Infringe upon the intellectual property rights of others</li>
                                <li style={{ marginBottom: '8px' }}>Attempt to reverse engineer our AI models</li>
                                <li style={{ marginBottom: '8px' }}>Interfere with or disrupt the service</li>
                            </ul>
                        </section>

                        <section style={{ marginBottom: '40px' }}>
                            <h2 style={{
                                fontSize: '24px',
                                fontWeight: 600,
                                color: '#f8fafc',
                                marginBottom: '16px',
                            }}>
                                6. Subscription and Payment
                            </h2>
                            <p style={{ color: '#94a3b8' }}>
                                Some features of OrionFlow require a paid subscription. By subscribing, you agree to pay the fees associated with your chosen plan. Subscriptions will automatically renew unless cancelled before the renewal date.
                            </p>
                        </section>

                        <section style={{ marginBottom: '40px' }}>
                            <h2 style={{
                                fontSize: '24px',
                                fontWeight: 600,
                                color: '#f8fafc',
                                marginBottom: '16px',
                            }}>
                                7. Disclaimer of Warranties
                            </h2>
                            <p style={{ color: '#94a3b8' }}>
                                OrionFlow is provided "as is" without warranties of any kind. While we strive for accuracy, AI-generated CAD models should be verified by qualified engineers before use in production or safety-critical applications.
                            </p>
                        </section>

                        <section style={{ marginBottom: '40px' }}>
                            <h2 style={{
                                fontSize: '24px',
                                fontWeight: 600,
                                color: '#f8fafc',
                                marginBottom: '16px',
                            }}>
                                8. Limitation of Liability
                            </h2>
                            <p style={{ color: '#94a3b8' }}>
                                To the maximum extent permitted by law, OrionFlow shall not be liable for any indirect, incidental, special, consequential, or punitive damages resulting from your use of the service.
                            </p>
                        </section>

                        <section style={{ marginBottom: '40px' }}>
                            <h2 style={{
                                fontSize: '24px',
                                fontWeight: 600,
                                color: '#f8fafc',
                                marginBottom: '16px',
                            }}>
                                9. Changes to Terms
                            </h2>
                            <p style={{ color: '#94a3b8' }}>
                                We reserve the right to modify these terms at any time. We will notify users of any material changes via email or through the service. Continued use after changes constitutes acceptance.
                            </p>
                        </section>

                        <section style={{ marginBottom: '40px' }}>
                            <h2 style={{
                                fontSize: '24px',
                                fontWeight: 600,
                                color: '#f8fafc',
                                marginBottom: '16px',
                            }}>
                                10. Contact
                            </h2>
                            <p style={{ color: '#94a3b8' }}>
                                For questions about these Terms of Service, please contact us at legal@orionflow.app
                            </p>
                        </section>
                    </div>
                </div>
            </section>

            <Footer />
        </div>
    );
}
