import os, glob, pandas as pd
from dash import Dash, html, dcc, Input, Output, State, callback_context, ALL
from dash.exceptions import PreventUpdate
import math
import dash_svg
import json

ARTISTS_DIR = "artists_csv"
WINDOW = 7 # 7 cards for smooth entry/exit
TRANSITION_MS = 600 # *** MUST MATCH 'transition' time in CSS ***

def human_m(n):
    try:
        return f"{float(n)/1e6:.1f}M"
    except Exception:
        return "0.0M"

def load_artists():
    rows = []
    for p in sorted(glob.glob(os.path.join(ARTISTS_DIR, "*.csv"))):
        try: df = pd.read_csv(p)
        except: continue
        if df.empty or "artist_name" not in df.columns: continue
        
        # --- MODIFICATION START ---
        # Find the majority genre, not just the first one
        genre = "Unknown"
        if "genre" in df.columns and not df["genre"].dropna().empty:
            genre = str(df["genre"].mode().iloc[0]) # .mode() finds the most frequent
        # --- MODIFICATION END ---
            
        name  = str(df["artist_name"].iloc[0])
        img   = str(df.get("image_url_artist", [""])[0])
        fol   = df.get("followers", [0])[0]
        pop   = df.get("popularity_artist_2025", [0])[0]
        if "explicit" in df.columns and not df["explicit"].dropna().empty:
            is_explicit_series = df["explicit"].astype(str).str.lower().isin(["true", "1", "yes"])
            explicit = is_explicit_series.mean() > 0.5
        else:
            explicit = False
        
        rows.append({
            "name": name, "image": img, "followers": int(fol) if pd.notna(fol) else 0,
            "popularity": int(pop) if pd.notna(pop) else 0, 
            "genre": genre, # Use the new majority genre
            "explicit": explicit
        })
    return pd.DataFrame(rows)

artists = load_artists()
N = len(artists)

app = Dash(__name__, suppress_callback_exceptions=True)
app.title = "Spotify Top Artists"


def format_duration(ms):
    """Converts milliseconds to M:SS format."""
    try:
        seconds = int(ms / 1000)
        minutes = math.floor(seconds / 60)
        seconds = seconds % 60
        return f"{minutes}:{seconds:02d}"
    except Exception:
        return "0:00"

def get_mood(energy, valence):
    """Returns a mood label and CSS class based on the matrix."""
    try:
        energy = float(energy)
        valence = float(valence)
    except Exception:
        return "Balanced", "mood-balanced"

    if 0.4 <= valence <= 0.6:
        return "Balanced", "mood-balanced"
    
    if energy > 0.6:
        if valence > 0.6:
            return "Energetic", "mood-energetic"
        else: # valence <= 0.4
            return "Intense", "mood-intense"
    else: # energy <= 0.6
        if valence > 0.6:
            return "Happy", "mood-happy"
        else: # valence <= 0.4
            return "Melancholic", "mood-melancholic"
    
    # Fallback for any other combo (shouldn't be hit)
    return "Balanced", "mood-balanced"

def get_spotify_link(track_id):
    """Creates a Spotify track URL."""
    return f"https://open.spotify.com/track/{track_id}"

icon_clock = dash_svg.Svg(
    xmlns="http://www.w3.org/2000/svg", width="16", height="16", viewBox="0 0 24 24", 
    fill="none", 
    stroke="currentColor", 
    style={  # <-- Move styling props here
        'strokeWidth': "2",
        'strokeLinecap': "round",
        'strokeLinejoin': "round"
    },
    children=[
        dash_svg.Circle(cx="12", cy="12", r="10"),
        dash_svg.Polyline(points="12 6 12 12 16 14")
])

icon_bpm = dash_svg.Svg(
    xmlns="http://www.w3.org/2000/svg", width="16", height="16", viewBox="0 0 24 24", 
    fill="none", 
    stroke="currentColor", 
    style={  # <-- Move styling props here
        'strokeWidth': "2",
        'strokeLinecap': "round",
        'strokeLinejoin': "round"
    },
    children=[
        dash_svg.Polyline(points="22 12 18 12 15 21 9 3 6 12 2 12")
])

icon_play = dash_svg.Svg(
    xmlns="http://www.w3.org/2000/svg", width="14", height="14", viewBox="0 0 24 24", 
    fill="currentColor", 
    stroke="currentColor", 
    style={  # <-- Move styling props here
        'strokeWidth': "1",
        'strokeLinecap': "round",
        'strokeLinejoin': "round"
    },
    children=[
        dash_svg.Polygon(points="5 3 19 12 5 21 5 3")
])


def create_feature_bar(name, value, css_class):
    """Creates a single audio feature bar."""
    val = float(value or 0) * 100
    return html.Div(className="feature-bar", children=[
        html.Div(name, className="feature-name"),
        html.Div(className="feature-bar-bg", children=[
            html.Div(className=f"feature-bar-fg {css_class}", style={'width': f'{val}%'})
        ]),
        html.Div(f"{val:.0f}", className="feature-value")
    ])

def song_card(song_row):
    """Creates a single song card div."""
    try:
        # Get mood label and class
        mood_label, mood_class = get_mood(song_row.get('energy'), song_row.get('valence'))
        
        # Get popularity (handle both names)
        pop = song_row.get('song_popularity_2025', song_row.get('popularity', 0))
        pop = max(0, min(100, int(pop or 0)))
        
        # Get track features
        energy = song_row.get('energy', 0)
        dance = song_row.get('danceability', 0)
        valence = song_row.get('valence', 0)
        acoustic = song_row.get('acousticness', 0)

        return html.Div(className="song-card", children=[
            html.Div(className="song-card-image", children=[
                html.Img(src=song_row.get('album_image_url')),
                html.Div(className="song-card-grad"),
                html.Div(song_row.get('genre', 'Music'), className="tag tag-genre"),
                html.Div(mood_label, className=f"tag tag-mood {mood_class}")
            ]),
            html.Div(className="song-card-content", children=[
                html.H3(song_row.get('track_name', 'Unknown Track'), className="song-name"),
                html.P(song_row.get('artist_name', 'Unknown Artist'), className="song-artist"),
                
                html.Div(className="song-info-row", children=[
                    html.Div(className="song-info-item", children=[
                        icon_clock,
                        format_duration(song_row.get('duration_ms'))
                    ]),
                    html.Div(className="song-info-item", children=[
                        icon_bpm,
                        f"{float(song_row.get('tempo', 0)):.0f} BPM"
                    ]),
                    html.A(["Play", icon_play], 
                        href=get_spotify_link(song_row.get('track_id')), 
                        target="_blank", 
                        className="play-button"
                        
                    )
                ]),
                
                html.P("Popularity", className="pop-title"),
                html.Div(className="line", children=[html.Div(f"{pop}/100")]),
                html.Div(className="bar-bg", children=[
                    html.Div(className="bar-fg", style={"width": f"{pop}%"})
                ]),
                
                html.P("Audio Features", className="audio-features-title"),
                create_feature_bar("Energy", energy, "feature-energy"),
                create_feature_bar("Danceability", dance, "feature-dance"),
                create_feature_bar("Positivity", valence, "feature-positive"),
                create_feature_bar("Acoustic", acoustic, "feature-acoustic"),
            ])
        ])
    except Exception as e:
        print(f"Error creating song card: {e}")
        return html.Div(f"Error loading song: {song_row.get('track_name')}")

def card(row, pos_idx):
    # row can be a dict or a pandas Series
    def rget(k, default=None):
        try:
            return row.get(k, default)
        except AttributeError:  # pandas Series
            try:
                return row[k]
            except Exception:
                return default

    artist_name = rget("name", "Unknown")
    img         = rget("image", "")
    followers   = rget("followers", 0) or 0
    genre       = rget("genre", "Unknown")
    exp         = bool(rget("explicit", False))
    pop_raw     = rget("popularity", 0) or 0
    pop         = max(0, min(100, int(pop_raw)))

    return html.Div(
        key=str(artist_name),
        className=f"card card-pos-{int(pos_idx)}",
        children=[
            html.Img(src=img, className="img"),
            html.Div(className="grad"),
            html.Div("EXPLICIT", className="explicit") if exp else None,
            html.Div(className="content", children=[
                html.Div(artist_name, className="name"),
                html.Div(f"{human_m(followers)} followers", className="sub"),
                html.Div([html.Div("Popularity"), html.Div(f"{pop}/100")], className="line"),
                html.Div(className="bar-bg", children=[
                    html.Div(className="bar-fg", style={"width": f"{pop}%"})
                ]),
                html.Div(className="bottom-row", children=[
                    html.Div(className="meta", children=[
                        html.Span("Genre "),
                        html.B(genre),
                    ]),
                    # UNIQUE pattern-matching id (adds 'pos' to avoid duplicates)
                    html.Button(
                        "Explore",
                        id={'type': 'explore-button', 'artist': str(artist_name), 'pos': int(pos_idx)},
                        className="pill"
                    )
                ])
            ])
        ]
    )
def window_nodes(start):
    if N == 0: return []
    nodes = []
    # Render from -1 to 5 (total of 7 cards)
    for i in range(-1, WINDOW - 1): 
        data_idx = (start + i) % N
        # We give each card a stable class based on its position in the list
        nodes.append(card(artists.iloc[data_idx], i))
    return nodes

# --- THIS IS THE ONLY 'app.layout' DEFINITION ---
# --- REPLACE your entire app.layout with this ---

app.layout = html.Div(className="page", children=[
    
    # --- This is your existing carousel ---
    html.Div(id="carousel-container", className="carousel-container", children=[
        html.Div("Top Artists", className="section-title"),
        html.Div(className="viewport", children=[
            html.Div(id="row", className="row"),
            html.Button("❮", id="arrow-left", className="chev left"),
            html.Button("❯", id="arrow-right", className="chev right"),
        ]),
    ]),

    # --- This is the new hidden song panel ---
    html.Div(id="song-panel", className="song-panel", children=[
        # --- THE HEADER AND BUTTON ARE NOW STATIC ---
        html.Div(className="song-panel-header", children=[
            html.H2(id="song-panel-title", className="song-panel-title"),
            html.Button("✕", id="close-panel-button", className="close-button")
        ]),
        # The content (grid) will be loaded here
        html.Div(id="song-panel-content") 
    ]),

    # --- Store all the state here ---
    dcc.Store(id="start", data=0),
    dcc.Store(id="animating", data=False),
    dcc.Store(id="direction", data=""),
    dcc.Interval(id="anim-timer", interval=TRANSITION_MS, n_intervals=0, disabled=True),
    dcc.Interval(id="reflow-timer", interval=1, n_intervals=0, disabled=True),
    
    # --- New stores to control the panel (THESE ARE REQUIRED) ---
    dcc.Store(id='song-panel-open', data=False),
    dcc.Store(id='selected-artist-name', data="")
])

# --- THIS IS THE ONLY 'render_window' CALLBACK ---
@app.callback(Output("row", "children"), Input("start", "data"))
def render_window(start): 
    return window_nodes(int(start or 0))

# --- THIS IS THE ONLY 'handle_slide' CALLBACK ---
@app.callback(
    Output("start", "data"),
    Output("row", "className"),
    Output("anim-timer", "disabled"),
    Output("animating", "data"),
    Output("direction", "data"),
    # --- Inputs ---
    Input("arrow-left", "n_clicks"),
    Input("arrow-right", "n_clicks"),
    Input("anim-timer", "n_intervals"),
    # --- State ---
    State("start", "data"),
    State("animating", "data"),
    State("direction", "data"),
    prevent_initial_call=True
)
def handle_slide(nL, nR, _tick, start, animating, direction):
    ctx = callback_context
    if not ctx.triggered or N == 0:
        raise PreventUpdate

    trig_id = ctx.triggered[0]["prop_id"].split(".")[0]
    start = int(start or 0)

    # --- Branch 1: A button was clicked ---
    if trig_id in ["arrow-left", "arrow-right"]:
        if animating:
            raise PreventUpdate
        
        new_direction = "right" if trig_id == "arrow-right" else "left"
        new_className = "row is-moving-left" if new_direction == "right" else "row is-moving-right"
        
        # start, className, timer_disabled, animating, direction
        return start, new_className, False, True, new_direction

    # --- Branch 2: The animation timer ticked (CSS transition finished) ---
    if trig_id == "anim-timer":
        if not animating:
            raise PreventUpdate
        
        # Now we "commit" the change based on the stored direction
        new_start = start
        if direction == "right":
            new_start = (start + 1) % N
        elif direction == "left":
            new_start = (start - 1 + N) % N
        
        # Reset everything: new start index, base class, disable timer
        # This is the logic that causes the "rebound" glitch
        # start, className, timer_disabled, animating, direction
        return new_start, "row", True, False, ""

    raise PreventUpdate

@app.callback(
    Output('song-panel-open', 'data'),
    Output('selected-artist-name', 'data'),
    Input({'type': 'explore-button', 'artist': ALL, 'pos': ALL}, 'n_clicks'),
    State('animating', 'data'),
    prevent_initial_call=True
)
def open_song_panel(n_clicks, animating):
    """
    Opens the song panel only when an 'Explore' button is clicked.
    Does NOT trigger during arrow navigation or re-render.
    """
    
    # 1️⃣ Guard: no clicks yet or carousel is animating
    if animating or not n_clicks or not any(n_clicks):
        raise PreventUpdate

    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    
    # 2️⃣ Extract the triggered ID cleanly
    artist_name = None
    trig = getattr(ctx, "triggered_id", None)
    
    if isinstance(trig, dict):
        artist_name = trig.get('artist')
    else:
        try:
            id_json_str = ctx.triggered[0]['prop_id'].split('.')[0]
            artist_name = json.loads(id_json_str).get('artist')
        except Exception:
            raise PreventUpdate # Failed to parse

    # 3️⃣ Guard: no valid artist
    if not artist_name:
        raise PreventUpdate

    print(f"✅ Opening panel for: {artist_name}")
    # We removed the file-checking logic.
    # This will now work for EVERY artist.
    return True, artist_name


# 2. Close the panel when the "Close" button is clicked
@app.callback(
    Output('song-panel-open', 'data', allow_duplicate=True),
    Input('close-panel-button', 'n_clicks'),
    prevent_initial_call=True
)
def close_song_panel(n_clicks):
    # ADDED THIS GUARD: Only return False if the button was actually clicked
    if n_clicks is None or n_clicks == 0:
        raise PreventUpdate
    
    print("❌ Close button clicked, closing panel.")
    return False

# 3. Add/remove the 'is-open' class to trigger the CSS slide
@app.callback(
    Output('song-panel', 'className'),
    Input('song-panel-open', 'data')
)
def toggle_panel_class(is_open):
    print("📂 toggle_panel_class →", is_open)
    if is_open:
        return "song-panel is-open"
    return "song-panel"

# 4. Update the content of the panel based on the selected artist
@app.callback(
    Output('song-panel-content', 'children'),
    Output('song-panel-title', 'children'), # <-- Also update the title
    Input('selected-artist-name', 'data')
)
def update_panel_content(artist_name):
    print("🎵 update_panel_content called for:", artist_name)
    if not artist_name:
        # Return empty content and a default title
        return [], "" 
    
    # 1. Find and load the artist's CSV
    # (Your existing logic for this is fine, assuming it works)
    csv_path = os.path.join(ARTISTS_DIR, f"{artist_name.replace(' ', '_').replace('.', '')}.csv")
    if not os.path.exists(csv_path):
        return [
            html.P(f"Could not find data file for {artist_name}")
        ], f"{artist_name} - Error"
        
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        return [
            html.P(f"Could not read data for {artist_name}: {e}")
        ], f"{artist_name} - Error"

    # 2. Sort tracks
    pop_col = 'song_popularity_2025' if 'song_popularity_2025' in df.columns else 'popularity'
    top_tracks = df.sort_values(by=pop_col, ascending=False).head(20)

    # 3. Create the song card components
    song_cards = [song_card(row) for _, row in top_tracks.iterrows()]
    
    # 4. Return ONLY the grid and the title string
    title = f"{artist_name}'s Top Tracks"
    return html.Div(song_cards, className="song-grid"), title


if __name__ == "__main__":
    app.run(debug=True, port=8050)