#!/usr/bin/env python3
import os
import time
import glob
import argparse
from typing import Dict, List, Tuple

import pandas as pd

try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    from spotipy.exceptions import SpotifyException
except Exception as e:
    raise SystemExit(
        "Missing dependency. Run: pip install spotipy pandas\n"
        f"Import error: {e}"
    )

# ---------- Helpers ----------

def ensure_env():
    """
    Spotipy uses SPOTIPY_CLIENT_ID/SECRET.
    If only SPOTIFY_* are present, copy them over.
    """
    if not os.getenv("SPOTIPY_CLIENT_ID") and os.getenv("SPOTIFY_CLIENT_ID"):
        os.environ["SPOTIPY_CLIENT_ID"] = os.getenv("SPOTIFY_CLIENT_ID") or ""
    if not os.getenv("SPOTIPY_CLIENT_SECRET") and os.getenv("SPOTIFY_CLIENT_SECRET"):
        os.environ["SPOTIPY_CLIENT_SECRET"] = os.getenv("SPOTIFY_CLIENT_SECRET") or ""

def make_client() -> spotipy.Spotify:
    """
    Build a Spotipy client with sane retry behavior.
    """
    ensure_env()
    mgr = SpotifyClientCredentials(
        client_id=os.getenv("SPOTIPY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
    )
    # retries/status_retries/backoff_factor give some resilience
    sp = spotipy.Spotify(
        auth_manager=mgr,
        requests_timeout=30,
        retries=6,
        status_retries=3,
        backoff_factor=0.4,
    )
    return sp

def choose_image(images: List[dict], size: str = "large") -> str:
    """
    images: list of {"height":..., "width":..., "url":...}
    size: "large" | "medium" | "small"
    """
    if not images:
        return ""
    # Spotify returns sorted by size desc; we still sort defensively.
    imgs = sorted(images, key=lambda x: (x.get("width", 0), x.get("height", 0)), reverse=True)
    if size == "large":
        return imgs[0]["url"]
    if size == "small":
        return imgs[-1]["url"]
    # medium: pick middle-ish
    mid = len(imgs) // 2
    return imgs[mid]["url"]

def chunked(seq: List[str], n: int) -> List[List[str]]:
    return [seq[i:i+n] for i in range(0, len(seq), n)]

def fetch_tracks_album_data(sp: spotipy.Spotify, ids: List[str], market: str = None, image_size: str = "large"
                            ) -> Dict[str, Tuple[str, str, str]]:
    """
    Returns {track_id: (album_image_url, album_name, album_release_date)}
    Missing/invalid ids map to ("", "", "").
    """
    result: Dict[str, Tuple[str, str, str]] = {}
    for group in chunked(ids, 50):  # Spotify /tracks max=50
        for _attempt in range(5):
            try:
                resp = sp.tracks(group, market=market) if market else sp.tracks(group)
                items = resp.get("tracks", []) or []
                break
            except SpotifyException as e:
                # Rate limit or transient
                if e.http_status == 429:
                    wait = int(e.headers.get("Retry-After", "1"))
                    time.sleep(wait + 0.5)
                    continue
                # Other errors: fill blanks for this batch and continue
                items = []
                break
            except Exception:
                time.sleep(0.5)
                continue

        # Fill from response
        seen = set()
        for it in items:
            if not it:
                continue
            tid = it.get("id") or ""
            if not tid:
                continue
            alb = it.get("album", {}) or {}
            images = alb.get("images", []) or []
            url = choose_image(images, size=image_size)
            name = alb.get("name", "") or ""
            date = alb.get("release_date", "") or ""
            result[tid] = (url, name, date)
            seen.add(tid)

        # For any ids not returned, put blanks so mapping succeeds
        for tid in group:
            if tid not in seen:
                result[tid] = ("", "", "")

    return result

# ---------- Main pipeline ----------

def process_csv(sp: spotipy.Spotify, path: str, market: str, image_size: str, force: bool, dry: bool) -> Tuple[int, int]:
    """
    Add/overwrite album_image_url (and album_name, album_release_date) for this file.
    Returns (updated_rows, total_rows).
    """
    df = pd.read_csv(path)
    if "track_id" not in df.columns:
        print(f"[skip] {os.path.basename(path)} – no 'track_id' column.")
        return 0, 0

    # Create columns if missing
    for col in ["album_image_url", "album_name", "album_release_date"]:
        if col not in df.columns:
            df[col] = ""

    # Determine which rows need fetching
    if force:
        need_mask = df["track_id"].astype(str).str.len() > 0
    else:
        need_mask = (df["album_image_url"].astype(str).str.len() == 0) & (df["track_id"].astype(str).str.len() > 0)

    to_fetch_ids = df.loc[need_mask, "track_id"].astype(str).dropna().unique().tolist()
    if not to_fetch_ids:
        print(f"[ok] {os.path.basename(path)} – nothing to update.")
        return 0, len(df)

    mapping = fetch_tracks_album_data(sp, to_fetch_ids, market=market, image_size=image_size)

    # Apply mapping
    def map_img(tid):
        return mapping.get(str(tid), ("", "", ""))[0]
    def map_name(tid):
        return mapping.get(str(tid), ("", "", ""))[1]
    def map_date(tid):
        return mapping.get(str(tid), ("", "", ""))[2]

    df.loc[need_mask, "album_image_url"] = df.loc[need_mask, "track_id"].map(map_img)
    df.loc[need_mask, "album_name"] = df.loc[need_mask, "track_id"].map(map_name)
    df.loc[need_mask, "album_release_date"] = df.loc[need_mask, "track_id"].map(map_date)

    updated = int(need_mask.sum())
    if not dry:
        df.to_csv(path, index=False)
    print(f"[write] {os.path.basename(path)} – updated {updated}/{len(df)} rows.")
    return updated, len(df)

def main():
    ap = argparse.ArgumentParser(description="Add album image URL (and album metadata) to artist CSVs using Spotify track IDs.")
    ap.add_argument("--dir", default="artists_csv", help="Directory containing per-artist CSV files (default: artists_csv)")
    ap.add_argument("--market", default=None, help="Spotify market code (e.g., IN, US). Optional.")
    ap.add_argument("--size", default="large", choices=["large", "medium", "small"], help="Album image size preference.")
    ap.add_argument("--force", action="store_true", help="Re-fetch and overwrite existing album_image_url values.")
    ap.add_argument("--dry", action="store_true", help="Do not write files; just show what would change.")
    args = ap.parse_args()

    sp = make_client()

    paths = sorted(glob.glob(os.path.join(args.dir, "*.csv")))
    if not paths:
        print(f"No CSVs found in {args.dir}/")
        return

    total_upd = 0
    total_rows = 0
    for p in paths:
        upd, rows = process_csv(sp, p, args.market, args.size, args.force, args.dry)
        total_upd += upd
        total_rows += rows

    print(f"\nDone. Updated {total_upd} rows across {len(paths)} file(s).")

if __name__ == "__main__":
    main()
