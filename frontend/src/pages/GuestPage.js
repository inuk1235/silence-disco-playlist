import { useEffect, useState, useCallback, useRef } from "react";
import { Toaster, toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Search, Music, Headphones, Clock, CheckCircle, Loader2 } from "lucide-react";
import api, { endpoints } from "../lib/api";
import SuccessOverlay from "../components/SuccessOverlay";

const GuestPage = () => {
    const [playlistInfo, setPlaylistInfo] = useState({ name: "Silent Disco", color: "#ffffff" });
    const [nowPlaying, setNowPlaying] = useState(null);
    const [queue, setQueue] = useState([]);
    const [searchQuery, setSearchQuery] = useState("");
    const [searchResults, setSearchResults] = useState([]);
    const [isAuthenticated, setIsAuthenticated] = useState(false);
    const [addingTrack, setAddingTrack] = useState(null); // Track URI being added
    const [successData, setSuccessData] = useState(null); // {trackName, artist, position}
    const addingRef = useRef(new Set()); // Prevent duplicate clicks

    // Check auth status
    useEffect(() => {
        const checkAuth = async () => {
            try {
                const response = await api.get(endpoints.checkAuth);
                setIsAuthenticated(response.data.authenticated);
            } catch (e) {
                console.error("Error checking auth:", e);
            }
        };
        checkAuth();
    }, []);

    // Fetch playlist info
    useEffect(() => {
        const fetchPlaylistInfo = async () => {
            try {
                const response = await api.get(endpoints.getPlaylistInfo);
                setPlaylistInfo(response.data);
            } catch (e) {
                console.error("Error fetching playlist info:", e);
            }
        };
        if (isAuthenticated) fetchPlaylistInfo();
    }, [isAuthenticated]);

    // Fetch now playing every 2 seconds
    useEffect(() => {
        const fetchNowPlaying = async () => {
            try {
                const response = await api.get(endpoints.getNowPlaying);
                setNowPlaying(response.data);
            } catch (e) {
                console.error("Error fetching now playing:", e);
            }
        };
        if (isAuthenticated) {
            fetchNowPlaying();
            const interval = setInterval(fetchNowPlaying, 2000);
            return () => clearInterval(interval);
        }
    }, [isAuthenticated]);

    // Fetch queue every 3 seconds
    useEffect(() => {
        const fetchQueue = async () => {
            try {
                const response = await api.get(endpoints.getQueue);
                setQueue(response.data.queue || []);
            } catch (e) {
                console.error("Error fetching queue:", e);
            }
        };
        if (isAuthenticated) {
            fetchQueue();
            const interval = setInterval(fetchQueue, 3000);
            return () => clearInterval(interval);
        }
    }, [isAuthenticated]);

    // Search tracks
    const handleSearch = useCallback(async (query) => {
        if (!query.trim()) {
            setSearchResults([]);
            return;
        }
        try {
            const response = await api.post(endpoints.search, { query });
            setSearchResults(response.data.tracks || []);
        } catch (e) {
            console.error("Error searching:", e);
        }
    }, []);

    // Debounced search
    useEffect(() => {
        const timer = setTimeout(() => {
            if (searchQuery) handleSearch(searchQuery);
        }, 300);
        return () => clearTimeout(timer);
    }, [searchQuery, handleSearch]);

    // Add track to queue with duplicate prevention
    const addTrack = async (track) => {
        // Prevent duplicate clicks
        if (addingRef.current.has(track.uri)) {
            return;
        }

        addingRef.current.add(track.uri);
        setAddingTrack(track.uri);

        try {
            const response = await api.post(endpoints.addTrack, {
                track_uri: track.uri,
                track_name: track.name,
                artist: track.artist,
                album_art: track.album_art
            });

            // Show success animation
            setSuccessData({
                trackName: track.name,
                artist: track.artist,
                position: response.data.position || 0
            });

            setSearchQuery("");
            setSearchResults([]);
        } catch (e) {
            const errorMsg = e.response?.data?.detail || "Failed to add track";
            toast.error(errorMsg);
        } finally {
            setAddingTrack(null);
            // Keep in ref for a short time to prevent rapid re-clicks
            setTimeout(() => {
                addingRef.current.delete(track.uri);
            }, 2000);
        }
    };

    // Format time
    const formatTime = (ms) => {
        if (!ms) return "0:00";
        const seconds = Math.floor(ms / 1000);
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}:${secs.toString().padStart(2, "0")}`;
    };

    // Close success overlay
    const handleSuccessComplete = useCallback(() => {
        setSuccessData(null);
    }, []);

    // Not authenticated view
    if (!isAuthenticated) {
        return (
            <div className="min-h-screen bg-gradient-to-b from-[#0a0a0f] to-[#12121a] flex items-center justify-center p-4">
                <Card className="bg-[#1a1a24] border-[#2a2a3a] p-6 sm:p-8 text-center max-w-md w-full mx-4">
                    <Headphones className="w-14 h-14 sm:w-16 sm:h-16 mx-auto mb-4 text-cyan-400" />
                    <h1 className="text-xl sm:text-2xl font-bold text-white mb-2" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                        Byron Bay Silent Disco
                    </h1>
                    <p className="text-gray-400 text-sm sm:text-base mb-6">Waiting for DJ to connect Spotify...</p>
                    <p className="text-xs sm:text-sm text-gray-500">Ask the DJ to authenticate at /admin</p>
                </Card>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-gradient-to-b from-[#0a0a0f] to-[#12121a] pb-8">
            <Toaster position="top-center" theme="dark" />

            {/* Success Animation Overlay */}
            <SuccessOverlay
                isVisible={!!successData}
                trackName={successData?.trackName}
                artist={successData?.artist}
                position={successData?.position}
                onComplete={handleSuccessComplete}
            />

            {/* Header */}
            <header className="pt-4 sm:pt-6 pb-2 px-4 text-center">
                <div className="max-w-lg mx-auto px-3 sm:px-4">
                    <h1 className="text-3xl sm:text-4xl font-bold text-white mb-1" style={{ fontFamily: "'Space Grotesk', sans-serif" }} data-testid="app-title">
                        Byron Bay Silent Disco
                    </h1>
                    <h2
                        className="text-2xl sm:text-3xl md:text-4xl font-bold mt-2 px-2"
                        style={{
                            color: playlistInfo.color,
                            fontFamily: "'Space Grotesk', sans-serif",
                            textShadow: playlistInfo.color !== '#ffffff' ? `0 0 20px ${playlistInfo.color}40` : 'none'
                        }}
                        data-testid="playlist-name"
                    >
                        {playlistInfo.name}
                    </h2>
                </div>
            </header>

            <div className="max-w-lg mx-auto px-3 sm:px-4 space-y-4 sm:space-y-6">
                {/* Now Playing Card */}
                <Card
                    className="relative overflow-hidden bg-[#1a1a24] border-2 border-cyan-400/50 p-3 sm:p-4"
                    style={{ boxShadow: "0 0 30px rgba(0, 240, 255, 0.3)" }}
                    data-testid="now-playing-card"
                >
                    <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/5 to-transparent pointer-events-none" />

                    {nowPlaying?.is_playing && nowPlaying.song_name ? (
                        <div className="flex gap-3 sm:gap-4">
                            {nowPlaying.album_art && (
                                <img
                                    src={nowPlaying.album_art}
                                    alt="Album art"
                                    className="w-20 h-20 sm:w-24 sm:h-24 rounded-lg object-cover shadow-lg flex-shrink-0"
                                    data-testid="now-playing-album-art"
                                />
                            )}
                            <div className="flex-1 min-w-0">
                                <p className="text-cyan-400 text-[10px] sm:text-xs font-medium uppercase tracking-wider mb-0.5 sm:mb-1">Now Playing</p>
                                <h2 className="text-white font-bold text-base sm:text-lg truncate" style={{ fontFamily: "'Space Grotesk', sans-serif" }} data-testid="now-playing-song">
                                    {nowPlaying.song_name}
                                </h2>
                                <p className="text-gray-400 text-xs sm:text-sm truncate mb-2 sm:mb-3" data-testid="now-playing-artist">{nowPlaying.artist}</p>

                                {/* Progress bar */}
                                <div className="space-y-1">
                                    <div className="h-1 sm:h-1.5 bg-gray-700 rounded-full overflow-hidden">
                                        <div
                                            className="h-full bg-gradient-to-r from-cyan-400 to-cyan-300 rounded-full transition-all duration-1000"
                                            style={{ width: `${(nowPlaying.progress_ms / nowPlaying.duration_ms) * 100}%` }}
                                            data-testid="now-playing-progress"
                                        />
                                    </div>
                                    <div className="flex justify-between text-[10px] sm:text-xs text-gray-500">
                                        <span>{formatTime(nowPlaying.progress_ms)}</span>
                                        <span className="text-cyan-400 font-medium" data-testid="time-left">{formatTime(nowPlaying.time_left_ms)} left</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="text-center py-4 sm:py-6">
                            <Music className="w-10 h-10 sm:w-12 sm:h-12 mx-auto mb-2 text-gray-600" />
                            <p className="text-gray-500 text-sm sm:text-base">{nowPlaying?.is_playing === false ? "Playback paused" : "Nothing playing right now"}</p>
                        </div>
                    )}
                </Card>

                {/* Search Area */}
                <div className="relative">
                    <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 sm:w-5 sm:h-5 text-gray-500" />
                        <Input
                            type="text"
                            placeholder="Search for a song..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="pl-9 sm:pl-10 bg-[#1a1a24] border-[#2a2a3a] text-white placeholder:text-gray-500 h-11 sm:h-12 text-sm sm:text-base focus:border-cyan-400 focus:ring-cyan-400/20"
                            style={{ fontFamily: "'Inter', sans-serif" }}
                            data-testid="search-input"
                        />
                    </div>

                    {/* Search Results Dropdown */}
                    {searchResults.length > 0 && (
                        <Card className="absolute z-50 w-full mt-2 bg-[#1a1a24] border-[#2a2a3a] overflow-hidden" data-testid="search-results">
                            <div className="max-h-[60vh] overflow-y-auto overscroll-contain">
                                <div className="p-2 space-y-1">
                                    {searchResults.map((track, index) => {
                                        const isDisabled = track.in_cooldown || track.recently_added;
                                        const isAdding = addingTrack === track.uri;

                                        return (
                                            <div
                                                key={track.uri + index}
                                                className={`p-2 rounded-lg transition-colors ${isDisabled ? 'opacity-60' : 'hover:bg-[#2a2a34]'}`}
                                                data-testid={`search-result-${index}`}
                                            >
                                                <div className="flex items-center gap-2">
                                                    {track.album_art && (
                                                        <img src={track.album_art} alt="" className="w-10 h-10 rounded object-cover flex-shrink-0" />
                                                    )}
                                                    <div className="flex-1 min-w-0 mr-2">
                                                        <p className={`text-sm font-medium truncate ${isDisabled ? 'text-gray-500' : 'text-white'}`}>{track.name}</p>
                                                        <p className="text-gray-500 text-xs truncate">{track.artist}</p>
                                                        {track.in_cooldown && (
                                                            <p className="text-red-400 text-[10px] flex items-center gap-1 mt-0.5">
                                                                <Clock className="w-3 h-3" />
                                                                Played recently ({track.cooldown_minutes}m)
                                                            </p>
                                                        )}
                                                        {track.recently_added && !track.in_cooldown && (
                                                            <p className="text-cyan-400 text-[10px] flex items-center gap-1 mt-0.5">
                                                                <CheckCircle className="w-3 h-3" />
                                                                Just added
                                                            </p>
                                                        )}
                                                    </div>
                                                    <Button
                                                        size="sm"
                                                        onClick={() => addTrack(track)}
                                                        disabled={isDisabled || isAdding}
                                                        className={`text-xs h-8 px-3 rounded-full flex-shrink-0 whitespace-nowrap ${isDisabled
                                                            ? 'bg-gray-700/50 text-gray-500 cursor-not-allowed border-gray-600'
                                                            : isAdding
                                                                ? 'bg-cyan-500/30 text-cyan-300 border-cyan-400'
                                                                : 'bg-cyan-500/20 border border-cyan-500/60 text-cyan-400 hover:bg-cyan-500/30 hover:text-cyan-300'
                                                            }`}
                                                        data-testid={`add-queue-btn-${index}`}
                                                    >
                                                        {isAdding ? (
                                                            <Loader2 className="w-3 h-3 animate-spin" />
                                                        ) : isDisabled ? (
                                                            track.recently_added ? 'Added' : 'Cooldown'
                                                        ) : (
                                                            'Add'
                                                        )}
                                                    </Button>
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        </Card>
                    )}
                </div>

                {/* Coming Up List */}
                <div>
                    <h3 className="text-white font-bold text-base sm:text-lg mb-2 sm:mb-3" style={{ fontFamily: "'Space Grotesk', sans-serif" }} data-testid="queue-title">
                        Coming Up
                    </h3>

                    {queue.length === 0 ? (
                        <Card className="bg-[#1a1a24] border-[#2a2a3a] p-4 sm:p-6 text-center">
                            <p className="text-gray-500 text-sm sm:text-base">Queue is empty</p>
                        </Card>
                    ) : (
                        <ScrollArea className="h-[350px] sm:h-[400px]">
                            <div className="space-y-2 pr-2">
                                {queue.map((track, index) => (
                                    <Card
                                        key={track.uri + index}
                                        className={`bg-[#1a1a24] border p-2.5 sm:p-3 flex items-center gap-2 sm:gap-3 transition-all ${track.is_guest_request
                                            ? "border-cyan-400/60 shadow-[0_0_20px_rgba(0,240,255,0.25)]"
                                            : "border-[#2a2a3a]"
                                            }`}
                                        data-testid={`queue-item-${index}`}
                                    >
                                        {/* Position */}
                                        <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-[#2a2a34] flex items-center justify-center text-xs sm:text-sm font-bold flex-shrink-0">
                                            {index === 0 ? (
                                                <span className="text-cyan-400 text-[10px] sm:text-xs">Next</span>
                                            ) : (
                                                <span className="text-gray-400 text-[10px] sm:text-xs">{index + 1}</span>
                                            )}
                                        </div>

                                        {track.album_art && (
                                            <img src={track.album_art} alt="" className="w-9 h-9 sm:w-11 sm:h-11 rounded object-cover flex-shrink-0" />
                                        )}

                                        <div className="flex-1 min-w-0">
                                            <p className="text-white text-xs sm:text-sm font-medium truncate">{track.name}</p>
                                            <p className="text-gray-400 text-[10px] sm:text-xs truncate">{track.artist}</p>
                                        </div>

                                        {track.is_guest_request && (
                                            <span className="text-[10px] sm:text-xs text-cyan-400 bg-cyan-400/15 px-2 py-0.5 sm:px-2.5 sm:py-1 rounded-full border border-cyan-400/30 flex-shrink-0" data-testid="guest-request-badge">
                                                Request
                                            </span>
                                        )}
                                    </Card>
                                ))}
                            </div>
                        </ScrollArea>
                    )}
                </div>
            </div>
        </div>
    );
};

export default GuestPage;
