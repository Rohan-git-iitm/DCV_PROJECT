import os, csv, time, argparse, requests
from requests.auth import HTTPBasicAuth

API = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"

# ---------- auth ----------
def get_token(cid=None, csec=None):
    cid  = cid  or os.getenv("SPOTIFY_CLIENT_ID")
    csec = csec or os.getenv("SPOTIFY_CLIENT_SECRET")
    if not cid or not csec:
        raise SystemExit("Set SPOTIFY_CLIENT_ID/SECRET or use --client-id/--client-secret")
    r = requests.post(
        TOKEN_URL,
        data={"grant_type":"client_credentials"},
        auth=HTTPBasicAuth(cid, csec),
        headers={"Content-Type":"application/x-www-form-urlencoded"},
        timeout=20,
    )
    if r.status_code != 200:
        raise SystemExit(f"Token error {r.status_code}: {r.text[:200]}")
    return r.json()["access_token"]

# ---------- helpers ----------
def sp_get(url, token, params=None):
    h = {"Authorization": f"Bearer {token}"}
    while True:
        r = requests.get(url, headers=h, params=params or {}, timeout=30)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After","1"))); continue
        r.raise_for_status()
        return r.json()

def sp_get_paged(url, token, params=None):
    params = dict(params or {})
    params.setdefault("limit", 100)
    while True:
        data = sp_get(url, token, params)
        for item in data.get("items", []):
            yield item
        if not data.get("next"): break
        url = data["next"]
        params = {}

def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]

def parse_playlist_id(s: str) -> str:
    if s.startswith("spotify:playlist:"): return s.split(":")[-1]
    if s.startswith("http"): return s.split("/playlist/")[1].split("?")[0]
    return s

def year_from_release_date(s: str):
    try: return int(s[:4])
    except: return None

# ---------- batch getters ----------
def get_playlist_tracks_resilient(pid, token, market=None):
    """Try tracks with market; if 404, retry without market."""
    url = f"{API}/playlists/{pid}/tracks"
    pos = 0
    # try with market first
    if market:
        try:
            for it in sp_get_paged(url, token, {"market": market, "limit": 100}):
                it["_position"] = pos; pos += 1; yield it
            return
        except requests.HTTPError as e:
            if getattr(e.response, "status_code", None) != 404:
                raise
            # fall through → retry without market
    for it in sp_get_paged(url, token, {"limit": 100}):
        it["_position"] = pos; pos += 1; yield it

def get_tracks(ids, token):
    out={}
    for group in chunked(list(set(ids)), 50):
        js = sp_get(f"{API}/tracks", token, {"ids": ",".join(group)})
        for t in js.get("tracks", []) or []:
            if t and t.get("id"): out[t["id"]] = t
    return out

def get_albums(ids, token):
    out={}
    for group in chunked(list(set([i for i in ids if i])), 20):
        js = sp_get(f"{API}/albums", token, {"ids": ",".join(group)})
        for a in js.get("albums", []) or []:
            if a and a.get("id"): out[a["id"]] = a
    return out

def get_artists(ids, token):
    out={}
    for group in chunked(list(set([i for i in ids if i])), 50):
        js = sp_get(f"{API}/artists", token, {"ids": ",".join(group)})
        for a in js.get("artists", []) or []:
            if a and a.get("id"): out[a["id"]] = a
    return out

def get_audio_features(ids, token):
    out={}
    for group in chunked(list(set(ids)), 100):
        js = sp_get(f"{API}/audio-features", token, {"ids": ",".join(group)})
        for f in js.get("audio_features", []) or []:
            if f and f.get("id"): out[f["id"]] = f
    return out

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Fetch Billions Club tracks without playlist meta.")
    ap.add_argument("playlist", help="Playlist URL/URI/ID")
    ap.add_argument("--market", default="US", help="Market code (default US)")
    ap.add_argument("--out", default=None, help="Output CSV path")
    ap.add_argument("--client-id", default=None)
    ap.add_argument("--client-secret", default=None)
    args = ap.parse_args()

    pid   = parse_playlist_id(args.playlist)
    token = get_token(args.client_id, args.client_secret)

    # no playlist meta call here — direct to tracks
    print(f"Fetching tracks for playlist {pid} (market={args.market}) …")
    items = list(get_playlist_tracks_resilient(pid, token, market=args.market))
    if not items:
        raise SystemExit("No items returned. If this persists, try --market '' or --market IN.")

    # collect IDs
    track_ids, album_ids, artist_ids = [], set(), set()
    base_rows=[]
    for it in items:
        tr = it.get("track")
        if not tr or not tr.get("id"): continue
        tid = tr["id"]
        track_ids.append(tid)
        alb = tr.get("album") or {}
        if alb.get("id"): album_ids.add(alb["id"])
        a_ids = [a.get("id") for a in tr.get("artists", []) if a.get("id")]
        for aid in a_ids: artist_ids.add(aid)
        base_rows.append({
            "playlist_id": pid,
            "position": it.get("_position"),
            "added_at": it.get("added_at"),
            "track_id": tid,
            "all_artist_ids": ";".join(a_ids)
        })

    print(f"Tracks: {len(track_ids)} | unique albums: {len(album_ids)} | unique artists: {len(artist_ids)}")
    tracks  = get_tracks(track_ids, token)
    albums  = get_albums(album_ids, token)

    # primary artist pool (first artist per track) + all artists
    prim_ids=[]
    for t in tracks.values():
        arts=t.get("artists") or []
        if arts and arts[0].get("id"): prim_ids.append(arts[0]["id"])
    artists = get_artists(set(prim_ids)|artist_ids, token)

    feats   = get_audio_features(track_ids, token)

    # build rows
    rows=[]
    for r in base_rows:
        tr = tracks.get(r["track_id"], {})
        if not tr: continue
        alb_id = (tr.get("album") or {}).get("id")
        alb    = albums.get(alb_id, tr.get("album") or {})
        arts   = tr.get("artists", []) or []
        pa     = arts[0] if arts else {}
        pa_obj = artists.get(pa.get("id"), {}) if pa.get("id") else {}

        f = feats.get(r["track_id"], {}) or {}

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
        raise SystemExit("No rows built — tracks unavailable in this market? Try --market '' or --market IN.")

    out = args.out or f"BillionsClub_{pid[:8]}.csv"
    with open(out, "w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"Saved {len(rows)} rows → {out}")

if __name__ == "__main__":
    main()
