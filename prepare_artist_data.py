import pandas as pd
import os

# Load dataset
df = pd.read_csv("top_1k_spotify.csv")

# --- Basic cleaning ---
# Strip leading/trailing spaces in column names (sometimes happens)
df.columns = [c.strip() for c in df.columns]

# Optional sanity checks
print("Columns:", df.columns.tolist())
print("Number of rows:", len(df))

# --- Compute Top 30 artists by count ---
artist_counts = (
    df.groupby("artist_name")["track_id"]
      .count()
      .sort_values(ascending=False)
      .head(40)
)
top_artists = artist_counts.index.tolist()
print("\nTop 30 Artists by number of songs:")
print(artist_counts)

# --- Create folder to store per-artist CSVs ---
os.makedirs("artists_csv", exist_ok=True)

# --- Save one CSV per artist ---
for artist in top_artists:
    sub = df[df["artist_name"] == artist].copy()
    # Replace unsafe characters in filenames
    safe_name = "".join(ch for ch in artist if ch.isalnum() or ch in (" ", "_", "-")).strip().replace(" ", "_")
    path = f"artists_csv/{safe_name}.csv"
    sub.to_csv(path, index=False)
    print(f"Saved {len(sub)} songs → {path}")

print("\n✅ Done! Individual artist CSVs stored in 'artists_csv/' folder.")
