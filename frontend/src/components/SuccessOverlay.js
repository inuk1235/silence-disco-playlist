import { useEffect } from "react";
import { CheckCircle } from "lucide-react";

// Success Animation Overlay Component
const SuccessOverlay = ({ isVisible, trackName, artist, position, onComplete }) => {
    useEffect(() => {
        if (isVisible) {
            const timer = setTimeout(() => {
                onComplete();
            }, 3000);
            return () => clearTimeout(timer);
        }
    }, [isVisible, onComplete]);

    if (!isVisible) return null;

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-sm animate-fade-in">
            <div className="bg-[#1a1a24] border-2 border-cyan-400 rounded-2xl p-6 mx-4 max-w-sm w-full text-center shadow-[0_0_50px_rgba(0,240,255,0.4)] animate-scale-in">
                <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-cyan-400/20 flex items-center justify-center animate-pulse-glow">
                    <CheckCircle className="w-10 h-10 text-cyan-400" />
                </div>
                <h3 className="text-xl font-bold text-white mb-1" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                    Added to Queue!
                </h3>
                <p className="text-cyan-400 font-medium text-lg truncate">{trackName}</p>
                <p className="text-gray-400 text-sm truncate mb-3">{artist}</p>
                {position > 0 && (
                    <div className="inline-flex items-center gap-2 bg-cyan-400/10 px-4 py-2 rounded-full border border-cyan-400/30">
                        <span className="text-cyan-400 font-bold text-lg">#{position}</span>
                        <span className="text-gray-300 text-sm">in queue</span>
                    </div>
                )}
            </div>
        </div>
    );
};

export default SuccessOverlay;
