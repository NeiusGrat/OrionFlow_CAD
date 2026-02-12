import Navbar from '../components/Landing/Navbar';
import HeroSection from '../components/Landing/HeroSection';
import TrustedBySection from '../components/Landing/TrustedBySection';
import DemoVideoSection from '../components/Landing/DemoVideoSection';
import AIDirectorSection from '../components/Landing/AIDirectorSection';
import CapabilitiesSection from '../components/Landing/CapabilitiesSection';
import BuiltForEngineersSection from '../components/Landing/BuiltForEngineersSection';
import PricingSection from '../components/Landing/PricingSection';
import FooterCTASection from '../components/Landing/FooterCTASection';
import Footer from '../components/Landing/Footer';

export default function LandingPage() {
    return (
        <div style={{
            minHeight: '100vh',
            background: '#030712',
            color: '#f8fafc',
            overflowX: 'hidden',
            overflowY: 'auto',
        }}>
            <Navbar />
            <HeroSection />
            <TrustedBySection />
            <div id="features">
                <DemoVideoSection />
                <AIDirectorSection />
                <CapabilitiesSection />
            </div>
            <BuiltForEngineersSection />
            <div id="pricing">
                <PricingSection />
            </div>
            <FooterCTASection />
            <Footer />
        </div>
    );
}
