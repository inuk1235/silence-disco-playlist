# Bolt's Journal

## 2024-05-23 - [Optimization: High-Frequency Polling & Database Writes]
**Learning:** The `get_now_playing` endpoint was designed to poll Spotify and write to MongoDB (to update cooldowns) on *every* request. With frontend polling every 2s, this creates a massive N*0.5 writes/sec load on the DB (where N is user count). A simple side-effect (updating timestamp) became a bottleneck.
**Action:** When an endpoint is polled frequently, always cache the read *and* consider how side-effects (like DB writes) scale. Buffering or caching the response prevents the side-effect from executing too often.
