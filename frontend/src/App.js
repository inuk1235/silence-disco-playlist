import { useEffect, useState, useCallback } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import axios from "axios";
import { Toaster, toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Search, Music, DollarSign, Headphones } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Main Guest Page
const GuestPage = () => {
  const [playlistInfo, setPlaylistInfo] = useState({ name: "Silent Disco", color: "#ffffff" });
  const [nowPlaying, setNowPlaying] = useState(null);
  const [queue, setQueue] = useState([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [squareLink, setSquareLink] = useState("");
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  // Fetch config
  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const response = await axios.get(`${API}/config`);
        setSquareLink(response.data.square_payment_link);
      } catch (e) {
        console.error("Error fetching config:", e);
      }
    };
    fetchConfig();
  }, []);

  // Check auth status
  useEffect(() => {
    const checkAuth = async () => {
      try {
        const response = await axios.get(`${API}/spotify/status`);
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
        const response = await axios.get(`${API}/spotify/playlist-info`);
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
        const response = await axios.get(`${API}/spotify/now-playing`);
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
        const response = await axios.get(`${API}/spotify/queue`);
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
    setIsSearching(true);
    try {
      const response = await axios.post(`${API}/spotify/search`, { query });
      setSearchResults(response.data.tracks || []);
    } catch (e) {
      console.error("Error searching:", e);
      toast.error("Search failed");
    } finally {
      setIsSearching(false);
    }
  }, []);

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchQuery) handleSearch(searchQuery);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery, handleSearch]);

  // Add track to queue
  const addTrack = async (trackUri) => {
    try {
      const response = await axios.post(`${API}/spotify/add-track`, { track_uri: trackUri });
      toast.success(response.data.message || "Track added to queue!");
      setSearchQuery("");
      setSearchResults([]);
    } catch (e) {
      console.error("Error adding track:", e);
      toast.error("Failed to add track");
    }
  };

  // Skip queue (paid)
  const skipQueue = async (trackUri) => {
    // Open payment link
    window.open(squareLink, "_blank");
    // Add track as priority
    try {
      await axios.post(`${API}/spotify/skip-paid`, { track_uri: trackUri });
      toast.success("Track added as next up!");
      setSearchQuery("");
      setSearchResults([]);
    } catch (e) {
      console.error("Error with skip:", e);
      toast.error("Failed to add track");
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

  // Not authenticated view
  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-[#0a0a0f] to-[#12121a] flex items-center justify-center p-4">
        <Card className="bg-[#1a1a24] border-[#2a2a3a] p-8 text-center max-w-md w-full">
          <Headphones className="w-16 h-16 mx-auto mb-4 text-cyan-400" />
          <h1 className="text-2xl font-bold text-white mb-2" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
            Byron Bay Silent Disco
          </h1>
          <p className="text-gray-400 mb-6">Waiting for DJ to connect Spotify...</p>
          <p className="text-sm text-gray-500">Ask the DJ to authenticate at /admin</p>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#0a0a0f] to-[#12121a] pb-8">
      <Toaster position="top-center" theme="dark" />
      
      {/* Header */}
      <header className="pt-6 pb-4 px-4 text-center">
        <p className="text-sm font-medium mb-1" style={{ color: playlistInfo.color, fontFamily: "'Space Grotesk', sans-serif" }} data-testid="playlist-name">
          Playlist: {playlistInfo.name}
        </p>
        <h1 className="text-3xl font-bold text-white mb-1" style={{ fontFamily: "'Space Grotesk', sans-serif" }} data-testid="app-title">
          Byron Bay Silent Disco
        </h1>
        <p className="text-gray-400 text-sm" style={{ fontFamily: "'Inter', sans-serif" }}>
          Request a song for the Silent Disco
        </p>
      </header>

      <div className="max-w-lg mx-auto px-4 space-y-6">
        {/* Now Playing Card */}
        <Card 
          className="relative overflow-hidden bg-[#1a1a24] border-2 border-cyan-400/50 p-4"
          style={{ boxShadow: "0 0 30px rgba(0, 240, 255, 0.3)" }}
          data-testid="now-playing-card"
        >
          <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/5 to-transparent pointer-events-none" />
          
          {nowPlaying?.is_playing && nowPlaying.song_name ? (
            <div className="flex gap-4">
              {nowPlaying.album_art && (
                <img 
                  src={nowPlaying.album_art} 
                  alt="Album art" 
                  className="w-24 h-24 rounded-lg object-cover shadow-lg"
                  data-testid="now-playing-album-art"
                />
              )}
              <div className="flex-1 min-w-0">
                <p className="text-cyan-400 text-xs font-medium uppercase tracking-wider mb-1">Now Playing</p>
                <h2 className="text-white font-bold text-lg truncate" style={{ fontFamily: "'Space Grotesk', sans-serif" }} data-testid="now-playing-song">
                  {nowPlaying.song_name}
                </h2>
                <p className="text-gray-400 text-sm truncate mb-3" data-testid="now-playing-artist">{nowPlaying.artist}</p>
                
                {/* Progress bar */}
                <div className="space-y-1">
                  <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-gradient-to-r from-cyan-400 to-cyan-300 rounded-full transition-all duration-1000"
                      style={{ width: `${(nowPlaying.progress_ms / nowPlaying.duration_ms) * 100}%` }}
                      data-testid="now-playing-progress"
                    />
                  </div>
                  <div className="flex justify-between text-xs text-gray-500">
                    <span>{formatTime(nowPlaying.progress_ms)}</span>
                    <span className="text-cyan-400 font-medium" data-testid="time-left">{formatTime(nowPlaying.time_left_ms)} left</span>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="text-center py-6">
              <Music className="w-12 h-12 mx-auto mb-2 text-gray-600" />
              <p className="text-gray-500">Nothing playing right now</p>
            </div>
          )}
        </Card>

        {/* Search Area */}
        <div className="relative">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500" />
            <Input
              type="text"
              placeholder="Search for a song..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10 bg-[#1a1a24] border-[#2a2a3a] text-white placeholder:text-gray-500 h-12 text-base focus:border-cyan-400 focus:ring-cyan-400/20"
              style={{ fontFamily: "'Inter', sans-serif" }}
              data-testid="search-input"
            />
          </div>

          {/* Search Results Dropdown */}
          {searchResults.length > 0 && (
            <Card className="absolute z-50 w-full mt-2 bg-[#1a1a24] border-[#2a2a3a] max-h-96 overflow-hidden" data-testid="search-results">
              <ScrollArea className="h-full max-h-96">
                <div className="p-2 space-y-1">
                  {searchResults.map((track, index) => (
                    <div 
                      key={track.uri + index}
                      className="flex items-center gap-3 p-2 rounded-lg hover:bg-[#2a2a34] transition-colors"
                      data-testid={`search-result-${index}`}
                    >
                      {track.album_art && (
                        <img src={track.album_art} alt="" className="w-12 h-12 rounded object-cover" />
                      )}
                      <div className="flex-1 min-w-0">
                        <p className="text-white text-sm font-medium truncate">{track.name}</p>
                        <p className="text-gray-500 text-xs truncate">{track.artist}</p>
                      </div>
                      <div className="flex flex-col gap-1">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => addTrack(track.uri)}
                          className="text-xs h-8 px-3 bg-cyan-500/10 border-cyan-500/50 text-cyan-400 hover:bg-cyan-500/20 hover:text-cyan-300"
                          data-testid={`add-track-btn-${index}`}
                        >
                          Add 4th
                        </Button>
                        <Button
                          size="sm"
                          onClick={() => skipQueue(track.uri)}
                          className="text-xs h-8 px-3 bg-red-500/10 border border-red-500/50 text-red-400 hover:bg-red-500/20 hover:text-red-300"
                          data-testid={`skip-queue-btn-${index}`}
                        >
                          <DollarSign className="w-3 h-3 mr-1" />1 Skip
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </Card>
          )}
        </div>

        {/* Queue List */}
        <div>
          <h3 className="text-white font-bold text-lg mb-3" style={{ fontFamily: "'Space Grotesk', sans-serif" }} data-testid="queue-title">
            Coming Up
          </h3>
          
          {queue.length === 0 ? (
            <Card className="bg-[#1a1a24] border-[#2a2a3a] p-6 text-center">
              <p className="text-gray-500">Queue is empty</p>
            </Card>
          ) : (
            <div className="space-y-2">
              {queue.map((track, index) => (
                <Card 
                  key={track.uri + index}
                  className={`bg-[#1a1a24] border p-3 flex items-center gap-3 transition-all ${
                    track.is_guest_request 
                      ? "border-cyan-400/50 shadow-[0_0_15px_rgba(0,240,255,0.2)]" 
                      : "border-[#2a2a3a]"
                  }`}
                  data-testid={`queue-item-${index}`}
                >
                  <div className="w-8 h-8 rounded-full bg-[#2a2a34] flex items-center justify-center text-sm font-bold text-gray-400">
                    {index === 0 ? (
                      <span className="text-cyan-400" data-testid="next-song-label">N</span>
                    ) : index}
                  </div>
                  {track.album_art && (
                    <img src={track.album_art} alt="" className="w-12 h-12 rounded object-cover" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-white text-sm font-medium truncate">{track.name}</p>
                    <p className="text-gray-500 text-xs truncate">{track.artist}</p>
                  </div>
                  {track.is_guest_request && (
                    <span className="text-xs text-cyan-400 bg-cyan-400/10 px-2 py-1 rounded-full" data-testid="guest-request-badge">
                      Request
                    </span>
                  )}
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// Admin Page for Spotify Authentication
const AdminPage = () => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const response = await axios.get(`${API}/spotify/status`);
        setIsAuthenticated(response.data.authenticated);
      } catch (e) {
        console.error("Error checking auth:", e);
      } finally {
        setLoading(false);
      }
    };
    
    // Check URL for auth success
    const params = new URLSearchParams(window.location.search);
    if (params.get("auth") === "success") {
      setIsAuthenticated(true);
      setLoading(false);
    } else {
      checkAuth();
    }
  }, []);

  const handleAuth = () => {
    window.location.href = `${API}/spotify/auth`;
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
      <Card className="bg-[#1a1a24] border-[#2a2a3a] p-8 text-center max-w-md w-full">
        <Headphones className="w-16 h-16 mx-auto mb-4 text-cyan-400" />
        <h1 className="text-2xl font-bold text-white mb-2" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
          DJ Admin Panel
        </h1>
        
        {isAuthenticated ? (
          <>
            <div className="bg-green-500/20 border border-green-500/50 rounded-lg p-4 mb-4">
              <p className="text-green-400 font-medium">Spotify Connected!</p>
            </div>
            <p className="text-gray-400 text-sm mb-4">The app is ready for guests to request songs.</p>
            <Button 
              variant="outline" 
              onClick={() => window.location.href = "/"}
              className="border-cyan-500/50 text-cyan-400 hover:bg-cyan-500/10"
              data-testid="go-to-guest-btn"
            >
              Go to Guest View
            </Button>
          </>
        ) : (
          <>
            <p className="text-gray-400 mb-6">Connect your Spotify account to enable song requests.</p>
            <Button 
              onClick={handleAuth}
              className="bg-green-600 hover:bg-green-700 text-white px-6 py-3 text-lg"
              data-testid="connect-spotify-btn"
            >
              Connect Spotify
            </Button>
            <p className="text-gray-500 text-xs mt-4">Make sure Spotify is playing on your device first.</p>
          </>
        )}
      </Card>
    </div>
  );
};

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<GuestPage />} />
          <Route path="/admin" element={<AdminPage />} />
        </Routes>
      </BrowserRouter>
    </div>
  );
}

export default App;
