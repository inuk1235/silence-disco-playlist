import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
const API_BASE_URL = `${BACKEND_URL}/api`;

const api = axios.create({
  baseURL: API_BASE_URL,
});

export const endpoints = {
  checkAuth: "/spotify/status",
  getPlaylistInfo: "/spotify/playlist-info",
  getNowPlaying: "/spotify/now-playing",
  getQueue: "/spotify/queue",
  search: "/spotify/search",
  addTrack: "/spotify/add-track",
  auth: "/spotify/auth",
};

export { API_BASE_URL };
export default api;
