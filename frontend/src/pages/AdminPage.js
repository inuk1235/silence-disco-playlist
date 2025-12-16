import { useEffect, useState } from "react";
import { Toaster } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Headphones } from "lucide-react";
import api, { endpoints, API_BASE_URL } from "../lib/api";

const AdminPage = () => {
    const [isAuthenticated, setIsAuthenticated] = useState(false);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const checkAuth = async () => {
            try {
                const response = await api.get(endpoints.checkAuth);
                setIsAuthenticated(response.data.authenticated);
            } catch (e) {
                console.error("Error checking auth:", e);
            } finally {
                setLoading(false);
            }
        };

        const params = new URLSearchParams(window.location.search);
        if (params.get("auth") === "success") {
            setIsAuthenticated(true);
            setLoading(false);
        } else {
            checkAuth();
        }
    }, []);

    const handleAuth = () => {
        // We need to redirect to the backend auth URL mostly because of OAuth redirect chain
        window.location.href = `${API_BASE_URL}${endpoints.auth}`;
    };

    if (loading) {
        return (
            <div className="min-h-screen bg-gradient-to-b from-[#0a0a0f] to-[#12121a] flex items-center justify-center">
                <p className="text-white">Loading...</p>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-gradient-to-b from-[#0a0a0f] to-[#12121a] flex items-center justify-center p-4">
            <Toaster position="top-center" theme="dark" />
            <Card className="bg-[#1a1a24] border-[#2a2a3a] p-6 sm:p-8 text-center max-w-md w-full mx-4">
                <Headphones className="w-14 h-14 sm:w-16 sm:h-16 mx-auto mb-4 text-cyan-400" />
                <h1 className="text-xl sm:text-2xl font-bold text-white mb-2" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                    DJ Admin Panel
                </h1>

                {isAuthenticated ? (
                    <>
                        <div className="bg-green-500/20 border border-green-500/50 rounded-lg p-3 sm:p-4 mb-4">
                            <p className="text-green-400 font-medium text-sm sm:text-base">Spotify Connected!</p>
                        </div>
                        <p className="text-gray-400 text-xs sm:text-sm mb-4">The app is ready for guests to request songs.</p>
                        <Button
                            variant="outline"
                            onClick={() => window.location.href = "/"}
                            className="w-full border-cyan-500/50 text-cyan-400 hover:bg-cyan-500/10 text-sm sm:text-base"
                            data-testid="go-to-guest-btn"
                        >
                            Go to Guest View
                        </Button>
                    </>
                ) : (
                    <>
                        <p className="text-gray-400 text-sm sm:text-base mb-6">Connect your Spotify account to enable song requests.</p>
                        <Button
                            onClick={handleAuth}
                            className="bg-green-600 hover:bg-green-700 text-white px-5 sm:px-6 py-2.5 sm:py-3 text-base sm:text-lg"
                            data-testid="connect-spotify-btn"
                        >
                            Connect Spotify
                        </Button>
                        <p className="text-gray-500 text-[10px] sm:text-xs mt-4">Make sure Spotify is playing on your device first.</p>
                    </>
                )}
            </Card>
        </div>
    );
};

export default AdminPage;
