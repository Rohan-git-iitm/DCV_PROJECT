import os, csv, argparse, time
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth
from spotipy import SpotifyException

# ---------------------------- helpers ----------------------------

def parse_playlist_id(s: str) -> str:
    if s.startswith("spotify:playlist:"): return s.split(":")[-1]
    if s.startswith("http"): return s.split("/playlist/")[1].split("?")[0]
    return s

def year_from_release_date(s: str):
    try: return int(s[:4])
    except: return None

def get_spotify_client(auth_mode: str):
    """
    auth_mode = "client"  -> Client Credentials (public resources)
    auth_mode = "user"    -> User OAuth (private playlists or if client mode fails)
    """
    if auth_mode == "client":
        # Spotipy reads SPOTIPY_CLIENT_ID / SPOTIPY_CLIENT_SECRET from env
        return spotipy.Spotify(auth_manager=SpotifyClientCredentials())
    elif auth_mode == "user":
        scope = "playlist-read-private playlist-read-collaborative"
        # Uses SPOTIPY_* env vars; opens a browser the first time, caches token in .cache
        return spotipy.Spotify(auth_manager=SpotifyOAuth(scope=scope))
    else:
        raise SystemExit("auth must be one of: client, user")

def fetch_playlist_items(sp: spotipy.Spotify, playlist_id: str, market: str | None):
    """Paginate through playlist items safely."""
    kwargs = {"additional_types": ("track",), "limit": 100}
    if market: kwargs["market"] = market
    res = sp.playlist_items(playlist_id, **kwargs)
    items = list(res.get("items", []) or [])
    while res.get("next"):
        res = sp.next(res)
        items.extend(res.get("items", []) or [])
    return items

def chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

# ------------------ robust audio-features via ISRC fallback ------------------

def get_isrc(sp, track_id, market="US"):
    try:
        t = sp.track(track_id, market=market)
        return (t.get("external_ids") or {}).get("isrc")
    except SpotifyException:
        return None

def find_track_by_isrc(sp, isrc, market="US"):
    if not isrc:
        return None
    try:
        res = sp.search(q=f'isrc:"{isrc}"', type="track", market=market, limit=1)
        items = (res.get("tracks") or {}).get("items") or []
        return items[0]["id"] if items else None
    except SpotifyException:
        return None

def audio_features_with_isrc_fallback(sp, track_ids, primary_market="US", chunk=50):
    """
    Returns dict: original_track_id -> audio_feature_dict.
    If /audio-features 403s for a given id, we:
      1) read its ISRC
      2) search same recording (ISRC) in 'primary_market' to get an alternate id
      3) fetch features for the alternate id and store under the original id.
    """
    out = {}

    def fetch_single(tid):
        # Direct attempt
        try:
            af = sp.audio_features([tid])
            if af and af[0] and af[0].get("id"):
                return af[0]
        except SpotifyException:
            pass
        # ISRC fallback
        isrc = get_isrc(sp, tid, market=primary_market)
        alt  = find_track_by_isrc(sp, isrc, market=primary_market)
        if alt and alt != tid:
            try:
                af = sp.audio_features([alt])
                if af and af[0] and af[0].get("id"):
                    return af[0]
            except SpotifyException:
                pass
        return None

    # de-dupe while preserving order
    uniq = []
    seen = set()
    for tid in track_ids:
        if tid and tid not in seen:
            seen.add(tid)
            uniq.append(tid)

    # fast path: bulk, then fix bad ones per-id
    for i in range(0, len(uniq), chunk):
        group = uniq[i:i+chunk]
        try:
            fs = sp.audio_features(group)
        except SpotifyException as e:
            # bulk failed → set to None list and fix per-id
            fs = [None] * len(group)

        for tid, f in zip(group, fs or []):
            if f and f.get("id"):
                out[tid] = f
            else:
                one = fetch_single(tid)
                if one:
                    out[tid] = one
                else:
                    # optional: print a short note so you know which ones lacked features
                    print(f"[warn] features unavailable for track_id={tid}")

    return out

# ---------------------------- main program ----------------------------

def main():
    ap = argparse.ArgumentParser(description="Fetch playlist → tracks/albums/artists/audio-features (ISRC-fallback) into CSV.")
    ap.add_argument("playlist", help="Playlist URL/URI/ID")
    ap.add_argument("--market", default="IN", help="Market for playlist items (e.g., IN/US). Try US if features 403.")
    ap.add_argument("--auth", choices=["client","user"], default="client", help="client=ClientCredentials, user=OAuth")
    ap.add_argument("--out", default=None, help="Output CSV path")
    args = ap.parse_args()

    pid = parse_playlist_id(args.playlist)
    sp = get_spotify_client(args.auth)

    # Playlist meta (nice to have; not required)
    pl_name, owner = None, None
    try:
        meta = sp.playlist(pid)
        pl_name = (meta.get("name") or "playlist").replace("/", "-").strip()
        owner = ((meta.get("owner") or {}).get("display_name") or (meta.get("owner") or {}).get("id"))
    except Exception:
        pl_name = f"Playlist_{pid[:8]}"

    out_csv = args.out or f"{pl_name}_{pid[:8]}.csv"
    print(f"Playlist: {pl_name} | Owner: {owner} | Saving → {out_csv}")

    # Items
    try:
        items = fetch_playlist_items(sp, pid, market=args.market or None)
    except SpotifyException as e:
        if args.auth == "client":
            raise SystemExit(f"Failed with client creds (try --auth user if playlist is private): {e}")
        raise

    if not items:
        raise SystemExit("No items returned (empty or not accessible).")

    # Collect IDs and base rows
    track_ids, album_ids, artist_ids = [], set(), set()
    base_rows, pos = [], 0
    for it in items:
        tr = it.get("track")
        if not tr or not tr.get("id"):
            continue
        tid = tr["id"]
        track_ids.append(tid)

        alb = tr.get("album") or {}
        if alb.get("id"): album_ids.add(alb["id"])

        a_ids = [a.get("id") for a in tr.get("artists", []) if a.get("id")]
        artist_ids.update(a_ids)

        base_rows.append({
            "playlist_name": pl_name,
            "playlist_id": pid,
            "position": pos,
            "added_at": it.get("added_at"),
            "track_id": tid,
            "all_artist_ids": ";".join(a_ids)
        })
        pos += 1

    # Tracks
    tracks = {}
    for group in chunked(list(dict.fromkeys(track_ids)), 50):
        js = sp.tracks(group)
        for t in js.get("tracks", []) or []:
            if t and t.get("id"):
                tracks[t["id"]] = t

    # Albums
    albums = {}
    for group in chunked(list(album_ids), 20):
        js = sp.albums(group)
        for a in js.get("albums", []) or []:
            if a and a.get("id"):
                albums[a["id"]] = a

    # Artists (primary + others)
    primary_ids = []
    for t in tracks.values():
        arts = t.get("artists") or []
        if arts and arts[0].get("id"):
            primary_ids.append(arts[0]["id"])
    artist_pool = list(set(primary_ids) | set(artist_ids))

    artists = {}
    for group in chunked(artist_pool, 50):
        js = sp.artists(group)
        for a in js.get("artists", []) or []:
            if a and a.get("id"):
                artists[a["id"]] = a

    # Audio features (robust)
    print("Fetching audio features (with ISRC fallback) …")
    feats = audio_features_with_isrc_fallback(sp, track_ids, primary_market="US", chunk=50)

    # Build final rows
    rows = []
    for r in base_rows:
        tr = tracks.get(r["track_id"], {})
        if not tr:
            continue

        alb_id = (tr.get("album") or {}).get("id")
        alb    = albums.get(alb_id, tr.get("album") or {})
        arts   = tr.get("artists", []) or []
        pa     = arts[0] if arts else {}
        pa_obj = artists.get(pa.get("id"), {}) if pa.get("id") else {}
        f      = feats.get(r["track_id"], {}) or {}

        rows.append({
            **r,
            # track
            "track_name": tr.get("name"),
            "track_popularity": tr.get("popularity"),
            "track_explicit": tr.get("explicit"),
            "duration_ms": tr.get("duration_ms"),
            "track_number": tr.get("track_number"),
            "preview_url": tr.get("preview_url"),
            "track_url": (tr.get("external_urls") or {}).get("spotify"),
            "uri": tr.get("uri"),
            "all_artists": ", ".join(a.get("name","") for a in arts),
            "primary_artist_id": pa.get("id"),
            "primary_artist_name": pa_obj.get("name"),
            "primary_artist_popularity": pa_obj.get("popularity"),
            "primary_artist_followers": (pa_obj.get("followers") or {}).get("total"),
            "primary_artist_genres": ", ".join(pa_obj.get("genres", [])) if pa_obj else None,
            # album
            "album_id": alb_id,
            "album_name": alb.get("name"),
            "album_type": alb.get("album_type"),
            "album_release_date": alb.get("release_date"),
            "album_release_precision": alb.get("release_date_precision"),
            "album_release_year": year_from_release_date(alb.get("release_date") or ""),
            "album_total_tracks": alb.get("total_tracks"),
            "album_label": alb.get("label"),
            "album_url": (alb.get("external_urls") or {}).get("spotify"),
            "album_image_url": (alb.get("images") or [{}])[0].get("url"),
            # audio features
            "danceability": f.get("danceability"),
            "energy": f.get("energy"),
            "valence": f.get("valence"),
            "tempo": f.get("tempo"),
            "loudness": f.get("loudness"),
            "speechiness": f.get("speechiness"),
            "acousticness": f.get("acousticness"),
            "instrumentalness": f.get("instrumentalness"),
            "liveness": f.get("liveness"),
            "key": f.get("key"),
            "mode": f.get("mode"),
            "time_signature": f.get("time_signature"),
        })

    if not rows:
        raise SystemExit("No rows built. If playlist is private, run with --auth user.")

    with open(out_csv, "w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    missing = [tid for tid in track_ids if tid not in feats]
    if missing:
        print(f"Finished. {len(missing)} track(s) lacked audio features after fallback (kept rows, feature cols empty).")
    print(f"Saved {len(rows)} rows → {out_csv}")

if __name__ == "__main__":
    main()
