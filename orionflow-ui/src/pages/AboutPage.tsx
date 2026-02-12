import { Link } from 'react-router-dom';
import { ArrowLeft, ArrowRight, Cpu, Zap, Target, Users } from 'lucide-react';
import Navbar from '../components/Landing/Navbar';
import Footer from '../components/Landing/Footer';

const values = [
    {
        icon: Cpu,
        title: 'Engineering First',
        description: 'We build tools that real engineers need. No gimmicks, no shortcuts - just precision geometry and reliable exports.',
    },
    {
        icon: Zap,
        title: 'Speed & Iteration',
        description: 'Design should be fast. We obsess over reducing the time from idea to manufacturable CAD model.',
    },
    {
        icon: Target,
        title: 'Accuracy Matters',
        description: 'B-REP geometry with proper tolerancing. Our models are production-ready, not just visual prototypes.',
    },
    {
        icon: Users,
        title: 'Community Driven',
        description: 'We build in public and listen to our users. The best CAD tool is the one engineers actually want to use.',
    },
];

const team = [
    {
        name: 'Engineering Team',
        description: 'Experts in computational geometry, AI/ML, and CAD systems.',
    },
    {
        name: 'Product Team',
        description: 'Designers and PMs focused on creating the best user experience.',
    },
    {
        name: 'Operations',
        description: 'Keeping everything running smoothly as we scale.',
    },
];

export default function AboutPage() {
    return (
        <div style={{
            minHeight: '100vh',
            background: '#030712',
            color: '#f8fafc',
            overflowX: 'hidden',
        }}>
            <Navbar />

            {/* Hero */}
            <section style={{
                padding: '160px 48px 100px',
                position: 'relative',
            }}>
                <div style={{
                    position: 'absolute',
                    inset: 0,
                    background: 'radial-gradient(ellipse 80% 50% at 50% 0%, rgba(59, 130, 246, 0.08) 0%, transparent 50%)',
                    pointerEvents: 'none',
                }} />

                <div style={{ maxWidth: '1280px', margin: '0 auto', position: 'relative', zIndex: 1 }}>
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
                        fontSize: '56px',
                        fontWeight: 800,
                        letterSpacing: '-0.03em',
                        marginBottom: '24px',
                    }}>
                        <span style={{ color: '#f8fafc' }}>Building the Future of </span>
                        <span style={{
                            background: 'linear-gradient(135deg, #3b82f6 0%, #60a5fa 100%)',
                            WebkitBackgroundClip: 'text',
                            WebkitTextFillColor: 'transparent',
                            backgroundClip: 'text',
                        }}>CAD</span>
                    </h1>

                    <p style={{
                        fontSize: '20px',
                        color: '#94a3b8',
                        maxWidth: '700px',
                        lineHeight: 1.6,
                        marginBottom: '48px',
                    }}>
                        OrionFlow is on a mission to democratize mechanical engineering. We believe anyone with an idea should be able to design production-ready parts - no CAD expertise required.
                    </p>

                    <div style={{
                        display: 'flex',
                        gap: '48px',
                        flexWrap: 'wrap',
                    }}>
                        <div>
                            <div style={{
                                fontSize: '48px',
                                fontWeight: 800,
                                color: '#3b82f6',
                                lineHeight: 1,
                            }}>2026</div>
                            <div style={{ color: '#64748b', fontSize: '14px', marginTop: '4px' }}>Founded</div>
                        </div>
                        <div>
                            <div style={{
                                fontSize: '48px',
                                fontWeight: 800,
                                color: '#3b82f6',
                                lineHeight: 1,
                            }}>10K+</div>
                            <div style={{ color: '#64748b', fontSize: '14px', marginTop: '4px' }}>Beta Users</div>
                        </div>
                        <div>
                            <div style={{
                                fontSize: '48px',
                                fontWeight: 800,
                                color: '#3b82f6',
                                lineHeight: 1,
                            }}>50K+</div>
                            <div style={{ color: '#64748b', fontSize: '14px', marginTop: '4px' }}>Parts Generated</div>
                        </div>
                    </div>
                </div>
            </section>

            {/* Our Story */}
            <section style={{
                padding: '80px 48px',
                background: 'linear-gradient(180deg, rgba(15, 23, 42, 0.3) 0%, transparent 100%)',
            }}>
                <div style={{ maxWidth: '900px', margin: '0 auto' }}>
                    <h2 style={{
                        fontSize: '36px',
                        fontWeight: 700,
                        letterSpacing: '-0.02em',
                        marginBottom: '24px',
                    }}>
                        Our Story
                    </h2>

                    <div style={{
                        fontSize: '17px',
                        color: '#94a3b8',
                        lineHeight: 1.8,
                    }}>
                        <p style={{ marginBottom: '24px' }}>
                            OrionFlow was born out of frustration. As engineers, we spent countless hours wrestling with complex CAD software when all we wanted was to get our ideas into manufacturable form. We knew there had to be a better way.
                        </p>
                        <p style={{ marginBottom: '24px' }}>
                            With advances in AI and browser-based computing, we saw an opportunity to reimagine CAD from the ground up. What if you could simply describe what you want, and have a real parametric model generated instantly? What if CAD software was as intuitive as having a conversation?
                        </p>
                        <p>
                            Today, OrionFlow is making that vision a reality. Our platform combines cutting-edge AI with a professional-grade geometry kernel, running entirely in your browser. No installs, no learning curve - just describe your part and start designing.
                        </p>
                    </div>
                </div>
            </section>

            {/* Values */}
            <section style={{
                padding: '100px 48px',
            }}>
                <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
                    <div style={{ textAlign: 'center', marginBottom: '64px' }}>
                        <h2 style={{
                            fontSize: '40px',
                            fontWeight: 700,
                            letterSpacing: '-0.02em',
                            marginBottom: '16px',
                        }}>
                            What We Believe
                        </h2>
                        <p style={{
                            fontSize: '18px',
                            color: '#94a3b8',
                        }}>
                            The principles that guide everything we build.
                        </p>
                    </div>

                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(2, 1fr)',
                        gap: '24px',
                    }}>
                        {values.map((value, index) => (
                            <div key={index} style={{
                                background: 'rgba(15, 23, 42, 0.6)',
                                border: '1px solid rgba(255, 255, 255, 0.06)',
                                borderRadius: '20px',
                                padding: '36px',
                            }}>
                                <div style={{
                                    width: '52px',
                                    height: '52px',
                                    borderRadius: '14px',
                                    background: 'rgba(59, 130, 246, 0.15)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    marginBottom: '20px',
                                }}>
                                    <value.icon size={24} color="#60a5fa" />
                                </div>

                                <h3 style={{
                                    fontSize: '20px',
                                    fontWeight: 600,
                                    marginBottom: '12px',
                                    color: '#f1f5f9',
                                }}>
                                    {value.title}
                                </h3>

                                <p style={{
                                    fontSize: '15px',
                                    color: '#94a3b8',
                                    lineHeight: 1.6,
                                }}>
                                    {value.description}
                                </p>
                            </div>
                        ))}
                    </div>
                </div>
            </section>

            {/* Team */}
            <section style={{
                padding: '80px 48px 120px',
            }}>
                <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
                    <div style={{ textAlign: 'center', marginBottom: '64px' }}>
                        <h2 style={{
                            fontSize: '40px',
                            fontWeight: 700,
                            letterSpacing: '-0.02em',
                            marginBottom: '16px',
                        }}>
                            Our Team
                        </h2>
                        <p style={{
                            fontSize: '18px',
                            color: '#94a3b8',
                        }}>
                            A passionate group of engineers, designers, and dreamers.
                        </p>
                    </div>

                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(3, 1fr)',
                        gap: '24px',
                    }}>
                        {team.map((dept, index) => (
                            <div key={index} style={{
                                background: 'rgba(15, 23, 42, 0.4)',
                                border: '1px solid rgba(255, 255, 255, 0.06)',
                                borderRadius: '16px',
                                padding: '32px',
                                textAlign: 'center',
                            }}>
                                <div style={{
                                    width: '64px',
                                    height: '64px',
                                    borderRadius: '50%',
                                    background: 'linear-gradient(145deg, rgba(59, 130, 246, 0.2) 0%, rgba(59, 130, 246, 0.05) 100%)',
                                    margin: '0 auto 20px',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    fontSize: '24px',
                                }}>
                                    {dept.name.charAt(0)}
                                </div>

                                <h3 style={{
                                    fontSize: '18px',
                                    fontWeight: 600,
                                    marginBottom: '8px',
                                    color: '#f1f5f9',
                                }}>
                                    {dept.name}
                                </h3>

                                <p style={{
                                    fontSize: '14px',
                                    color: '#94a3b8',
                                    lineHeight: 1.5,
                                }}>
                                    {dept.description}
                                </p>
                            </div>
                        ))}
                    </div>

                    {/* Join Us */}
                    <div style={{
                        marginTop: '64px',
                        textAlign: 'center',
                        padding: '48px',
                        background: 'linear-gradient(145deg, rgba(37, 99, 235, 0.15) 0%, rgba(15, 23, 42, 0.8) 100%)',
                        borderRadius: '24px',
                        border: '1px solid rgba(59, 130, 246, 0.2)',
                    }}>
                        <h3 style={{
                            fontSize: '28px',
                            fontWeight: 700,
                            marginBottom: '12px',
                        }}>
                            Join Our Team
                        </h3>
                        <p style={{
                            color: '#94a3b8',
                            fontSize: '16px',
                            marginBottom: '24px',
                        }}>
                            We're always looking for talented people to help us build the future of CAD.
                        </p>
                        <button style={{
                            background: 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
                            color: 'white',
                            padding: '14px 28px',
                            borderRadius: '12px',
                            fontWeight: 600,
                            fontSize: '15px',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '8px',
                            border: 'none',
                            cursor: 'pointer',
                            boxShadow: '0 4px 20px rgba(59, 130, 246, 0.4)',
                        }}>
                            View Open Positions
                            <ArrowRight size={16} />
                        </button>
                    </div>
                </div>
            </section>

            <Footer />
        </div>
    );
}
