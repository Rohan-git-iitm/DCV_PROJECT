import os, glob, pandas as pd
from dash import Dash, html, dcc, Input, Output, State, callback_context, ALL
import plotly.express as px
from dash.exceptions import PreventUpdate
import math
import dash_svg
import json
import re

ARTISTS_DIR = "artists_csv"
WINDOW = 7 # 7 cards for smooth entry/exit
TRANSITION_MS = 600 # *** MUST MATCH 'transition' time in CSS ***

def human_m(n):
    try:
        return f"{float(n)/1e6:.1f}M"
    except Exception:
        return "0.0M"

def load_artists(year='all_time'):
    """
    Loads the top artists for a specific year (or all-time).
    """
    # Determine the correct folder based on the year
    folder = os.path.join(ARTISTS_DIR, str(year))
    
    rows = []
    # Use glob to find all CSV files in that year's folder
    for p in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        try: 
            df = pd.read_csv(p)
        except: 
            continue
        if df.empty or "artist_name" not in df.columns: 
            continue
        
        # --- Your existing logic ---
        genre = "Unknown"
        if "genre" in df.columns and not df["genre"].dropna().empty:
            genre = str(df["genre"].mode().iloc[0])
            
        name  = str(df["artist_name"].iloc[0])
        img   = str(df.get("image_url_artist", [""])[0])
        fol   = df.get("followers", [0])[0]
        pop   = df.get("popularity_artist_2025", [0])[0] # Note: This col might need to be dynamic
        
        if "explicit" in df.columns and not df["explicit"].dropna().empty:
            is_explicit_series = df["explicit"].astype(str).str.lower().isin(["true", "1", "yes"])
            explicit = is_explicit_series.mean() > 0.5
        else:
            explicit = False
        
        rows.append({
            "name": name, "image": img, "followers": int(fol) if pd.notna(fol) else 0,
            "popularity": int(pop) if pd.notna(pop) else 0, 
            "genre": genre, 
            "explicit": explicit
        })
        
    return pd.DataFrame(rows)

artists = load_artists()
N = len(artists)

app = Dash(__name__, suppress_callback_exceptions=True)
app.title = "Spotify Music Dashboard"

try:
    df_for_dropdown = pd.read_csv("cleaned_data.csv")
    TOP_10_ARTISTS_LIST = df_for_dropdown['artist_name'].value_counts().head(10).index.tolist()
    ARTIST_DROPDOWN_OPTIONS = [{'label': artist, 'value': artist} for artist in TOP_10_ARTISTS_LIST]
except FileNotFoundError:
    print("WARNING: cleaned_data.csv not found. Artist dropdown will be empty.")
    TOP_10_ARTISTS_LIST = []
    ARTIST_DROPDOWN_OPTIONS = []


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
                html.Img(src=song_row.get('image_url_song')),
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

def window_nodes(start, artists_df):
    """
    Creates the card components from a provided artist dataframe.
    """
    N = len(artists_df)
    if N == 0: 
        return [], 0 # Return empty list and N=0
    
    nodes = []
    for i in range(-1, WINDOW - 1): 
        data_idx = (start + i) % N
        nodes.append(card(artists_df.iloc[data_idx], i))
    
    return nodes, N # Return nodes and the count

# --- THIS IS THE ONLY 'app.layout' DEFINITION ---
# --- REPLACE your entire app.layout with this ---

year_options = [{'label': 'All-Time', 'value': 'all_time'}] + \
               [{'label': str(y), 'value': str(y)} for y in range(2023, 2012, -1)]


app.layout = html.Div(className="page", children=[
    # --- This is your existing carousel ---
    html.Div(id="carousel-container", className="carousel-container", children=[
        
        # --- MODIFIED HEADER ---
        html.Div(className="song-panel-header", children=[ # Re-using this class
            
            # --- NEW TITLE/SUBTITLE BLOCK ---
            html.Div([
                html.Div("Music Dashboard", className="section-title"),
                html.P("Discover trending artists and explore their music through the years", className="section-subtitle")
            ]),
            # --- END NEW BLOCK ---
            
            dcc.Dropdown(
                id='year-filter',
                options=year_options,
                value='2023', # Default value
                clearable=False,
                className="year-dropdown"
            )
        ]),
        # --- END MODIFIED HEADER ---
        
        html.Div(className="viewport", children=[
            html.Div(id="row", className="row"),
            html.Button("❮", id="arrow-left", className="chev left"),
            html.Button("❯", id="arrow-right", className="chev right"),
        ]),
    ]),

    # --- This is the new hidden song panel ---
    html.Div(id="song-panel", className="song-panel", children=[
        html.Div(className="song-panel-header", children=[
            html.H2(id="song-panel-title", className="song-panel-title"),
            html.Button("✕", id="close-panel-button", className="close-button")
        ]),
        html.Div(id="song-panel-content") 
    ]),

    # --- NEW: Wrapper for ALL plots ---
    html.Div(className="plots-section", children=[
        
        # --- Plot 1 ---
        html.Div(className="plot-container", children=[
            # This title is now inside the plot-container
            html.H2("Top Genres Over Time", className="section-title"), 
            dcc.Graph(id='genre-bar-chart-race')
        ]),

        html.Div(className="plot-container", children=[
            html.H2("Top 10 Artists Popularity Over Time", className="section-title"),
            
            # The Dropdown
            dcc.Dropdown(
                id='artist-dropdown',
                options=ARTIST_DROPDOWN_OPTIONS,
                value=TOP_10_ARTISTS_LIST, # Select all by default
                multi=True, # Allow multiple selections
                className="artist-dropdown",
                placeholder="Select artists to display..."
            ),
            
            # The Graph
            dcc.Graph(id='artist-line-chart')
        ]),

        html.Div(className="plot-container", children=[
            html.H2('Audio Feature Distribution for Top Genres', className="section-title"),
            # The title is dynamic, so it's set in the callback
            dcc.Graph(id='genre-box-plot')
        ]),

        html.Div(className="plot-container", children=[
            # Title is set in the callback
            dcc.Graph(id='animated-radar-chart')
        ]),

        html.Div(className="plot-container", children=[
            dcc.Graph(id='corr-song-plot')
        ]),

        # --- ADD PLOT 6 (Artist Followers) ---
        html.Div(className="plot-container", children=[
            dcc.Graph(id='corr-artist-plot')
        ]),
        
        # --- Plot 2 (Example of how you'd add another) ---
        # html.Div(className="plot-container", children=[
        #     html.H2("Another Chart", className="section-title"),
        #     dcc.Graph(id='another-chart')
        # ]),
        
    ]),
    # --- END PLOTS SECTION --

    # --- Store all the state here ---
    dcc.Store(id="start", data=0),
    dcc.Store(id="animating", data=False),
    dcc.Store(id="direction", data=""),
    dcc.Store(id="current-N", data=0), # <-- NEW: Store for artist count
    dcc.Interval(id="anim-timer", interval=TRANSITION_MS, n_intervals=0, disabled=True),
    dcc.Interval(id="reflow-timer", interval=30, n_intervals=0, disabled=True), # We'll keep this for the jitter fix
    
    # --- New stores to control the panel ---
    dcc.Store(id='song-panel-open', data=False),
    dcc.Store(id='selected-artist-name', data="")
])


@app.callback(
    Output("row", "children"),
    Output("current-N", "data"),
    Output("start", "data", allow_duplicate=True), # Also resets 'start'
    Input("year-filter", "value"),
    Input("start", "data"),
    prevent_initial_call='initial_duplicate'
)
def update_artist_carousel(selected_year, start_index):
    """
    This runs when the Year changes OR when the 'start' index changes.
    It loads the correct artists and renders the carousel.
    """
    ctx = callback_context
    triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

    # 1. Load the artists for the selected year
    artists_df = load_artists(selected_year)
    
    # 2. Check what triggered the callback
    start = 0 # Default to 0 if the year changed
    if triggered_id == "start":
        start = int(start_index or 0) # Keep the current start index
    
    # 3. Create the new cards
    nodes, N = window_nodes(start, artists_df)
    
    return nodes, N, start


# --- THIS IS THE ONLY 'handle_slide' CALLBACK ---
@app.callback(
    Output("start", "data"),
    Output("row", "className"),
    Output("anim-timer", "disabled"),
    Output("reflow-timer", "disabled"),
    Output("animating", "data"),
    Output("direction", "data"),
    Input("arrow-left", "n_clicks"),
    Input("arrow-right", "n_clicks"),
    Input("anim-timer", "n_intervals"),
    Input("reflow-timer", "n_intervals"),
    State("start", "data"),
    State("animating", "data"),
    State("direction", "data"),
    State("current-N", "data") # <-- ADDED STATE
)
def handle_slide(nL, nR, _tick_anim, _tick_reflow, start, animating, direction, N): # <-- ADDED 'N'
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
        return start, new_className, False, True, True, new_direction

    # --- Branch 2: The animation timer ticked ---
    if trig_id == "anim-timer":
        if not animating:
            raise PreventUpdate
        
        new_start = start
        if direction == "right":
            new_start = (start + 1) % N
        elif direction == "left":
            new_start = (start - 1 + N) % N
        
        return new_start, "row no-transition", True, False, False, ""

    # --- Branch 3: The reflow timer ticked ---
    if trig_id == "reflow-timer":
        return start, "row", True, True, False, ""

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
    
    print("Close button clicked, closing panel.")
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
    Output('song-panel-title', 'children'),
    Input('selected-artist-name', 'data'),
    State('year-filter', 'value') # <-- ADDED STATE
)
def update_panel_content(artist_name, selected_year): # <-- ADDED 'selected_year'
    print(f"🎵 update_panel_content for: {artist_name} in {selected_year}")
    if not artist_name:
        return [], "" 
    
    # 1. Sanitize artist name
    name_curr = artist_name.replace(' ', '_')
    safe_name = re.sub(r'[^\w_]', '', name_curr)
    
    # 2. Use the 'selected_year' to find the correct folder
    csv_path = os.path.join(ARTISTS_DIR, str(selected_year), f"{safe_name}.csv")
    
    if not os.path.exists(csv_path):
        return [
            html.P(f"Could not find data file for {artist_name} in {selected_year}.")
        ], f"{artist_name} - Error"
        
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        return [
            html.P(f"Could not read data for {artist_name}: {e}")
        ], f"{artist_name} - Error"

    # 3. Sort tracks
    pop_col = 'song_popularity_2025' if 'song_popularity_2025' in df.columns else 'popularity'
    top_tracks = df.sort_values(by=pop_col, ascending=False).head(20)

    # 4. Create the song card components
    song_cards = [song_card(row) for _, row in top_tracks.iterrows()]
    
    # 5. Return the grid and the title
    title = f"{artist_name}'s Top Tracks"
    return html.Div(song_cards, className="song-grid"), title

##############################
########### PLOTS ############
##############################

@app.callback(
    Output('genre-bar-chart-race', 'figure'),
    Input('year-filter', 'value') # Triggers once on load
)
def update_bar_chart_race(_load_trigger):
    
    # --- This is your Plotly code ---
    TOP_N = 10
    
    try:
        df_3 = pd.read_csv("cleaned_data.csv")
    except FileNotFoundError:
        print("Error: cleaned_data.csv not found for bar chart race.")
        return px.bar() # Return an empty figure

    genre_counts = df_3['genre'].value_counts()
    top_genres = genre_counts.head(TOP_N).index.tolist()

    df_top = df_3[df_3['genre'].isin(top_genres)]

    # Base group
    year_genre_counts = (
        df_top.groupby(['year', 'genre'])
              .size()
              .reset_index(name='count')
    )

    # FIX FLICKER: Create complete grid of (year × genre)
    years = sorted(df_top['year'].unique())
    genres = sorted(top_genres)

    grid = pd.MultiIndex.from_product([years, genres], names=['year','genre'])
    year_genre_complete = pd.DataFrame(index=grid).reset_index()

    # Merge original counts
    year_genre_complete = year_genre_complete.merge(
        year_genre_counts,
        how='left',
        on=['year','genre']
    )

    # Fill missing genre/year pairs with 0
    year_genre_complete['count'] = year_genre_complete['count'].fillna(0)

    # Now sort for animation
    df_plot = year_genre_complete.sort_values(['year','count'], ascending=[True,False])

    # Stable color map
    colors = px.colors.qualitative.Plotly
    color_map = {g: colors[i % len(colors)] for i, g in enumerate(genres)}

    fig = px.bar(
        df_plot,
        x='count',
        y='genre',
        color='genre',
        color_discrete_map=color_map,
        animation_frame='year',
        animation_group='genre',
        orientation='h',
        range_x=[0, df_plot['count'].max() + 10],
    )

    # --- These are styling updates for Dash ---
    fig.update_layout(
        title='Top 10 Genre Popularity (2013-2023)',
        yaxis={'categoryorder': 'total ascending'},
        transition=dict(duration=600, easing='cubic-in-out'),
        plot_bgcolor='rgba(0,0,0,0)', # Transparent plot background
        paper_bgcolor='rgba(0,0,0,0)', # Transparent paper background
        font=dict(color='#fff') # White text
    )

    # Smooth slider
    for step in fig.layout.sliders[0].steps:
        step['args'][1]['frame']['duration'] = 600
        step['args'][1]['transition']['duration'] = 600
    
    return fig

@app.callback(
    Output('artist-line-chart', 'figure'),
    Input('artist-dropdown', 'value')
)
def update_artist_line_chart(selected_artists):
    
    # 1. Load data
    try:
        df = pd.read_csv("cleaned_data.csv")
    except FileNotFoundError:
        return px.line(title="Error: cleaned_data.csv not found").update_layout(
            plot_bgcolor='rgba(0,0,0,0)', 
            paper_bgcolor='rgba(0,0,0,0)', 
            font=dict(color='#fff')
        )

    # 2. Filter for Top 10
    df_top_10 = df[df['artist_name'].isin(TOP_10_ARTISTS_LIST)].copy()

    # 3. Group by year and artist
    yearly_top_artists_popularity = df_top_10.groupby(['year', 'artist_name'])['popularity'].mean().reset_index()

    # --- NEW: Convert year to numeric ---
    yearly_top_artists_popularity['year'] = pd.to_numeric(
        yearly_top_artists_popularity['year'], 
        errors='coerce'
    )

    # 4. Filter for selected artists
    if not selected_artists:
        # If nothing is selected, return an empty, styled plot
        fig_multi_artist = px.line(title='Average Song Popularity for Top 10 Artists Over Time')
    else:
        # Create the plot using only the selected artists
        df_filtered = yearly_top_artists_popularity[yearly_top_artists_popularity['artist_name'].isin(selected_artists)]
        
        # --- NEW: Sort values before plotting for correct line drawing ---
        df_filtered = df_filtered.sort_values(['artist_name', 'year'])
        
        fig_multi_artist = px.line(
            df_filtered, # Use the sorted, filtered data
            x='year',
            y='popularity',
            color='artist_name', 
            title='Average Song Popularity for Top 10 Artists Over Time',
            labels={'popularity': 'Average Song Popularity', 'year': 'Year', 'artist_name': 'Artist'},
            markers=True
        )
    
    # 5. Style the plot for the dashboard
    # --- REMOVED: fig_multi_artist.update_xaxes(type='category') ---
    fig_multi_artist.update_layout(
        plot_bgcolor='rgba(0,0,0,0)', 
        paper_bgcolor='rgba(0,0,0,0)', 
        font=dict(color='#fff'),
        legend_title_text='' # Hide "artist_name" title
    )
    
    return fig_multi_artist

@app.callback(
    Output('genre-box-plot', 'figure'),
    Input('year-filter', 'value')
)
def update_genre_box_plot(selected_year):
    
    # 1. Load data
    try:
        df = pd.read_csv("cleaned_data.csv")
    except FileNotFoundError:
        return px.box(title="Error: cleaned_data.csv not found").update_layout(
            plot_bgcolor='rgba(0,0,0,0)', 
            paper_bgcolor='rgba(0,0,0,0)', 
            font=dict(color='#fff')
        )

    # 2. Filter by selected year (if not 'all_time')
    title_suffix = " (All-Time)"
    if selected_year != 'all_time':
        try:
            df = df[df['year'] == int(selected_year)]
            title_suffix = f" ({selected_year})"
        except ValueError:
            pass # Keep all-time if value is invalid

    # 3. Get the list of the top 10 most frequent genres for that period
    top_10_genres = df['genre'].value_counts().head(10).index.tolist()

    # 4. Filter the DataFrame to include only these genres
    df_top_10_genres = df[df['genre'].isin(top_10_genres)].copy()

    # 5. Create the box plot
    fig = px.box(
        df_top_10_genres,
        x='genre',
        y='valence',
        color='genre', # Add color for clarity
        title='Distribution of "Happiness" (Valence) for Top 10 Genres',
        labels={'valence': 'Valence Score', 'genre': 'Genre'}
    )
    
    # 6. Style the plot for the dashboard
    fig.update_layout(
        plot_bgcolor='rgba(0,0,0,0)', 
        paper_bgcolor='rgba(0,0,0,0)', 
        font=dict(color='#fff'),
        showlegend=False # Don't need legend, x-axis is enough
    )
    
    return fig

@app.callback(
    Output('animated-radar-chart', 'figure'),
    Input('year-filter', 'value') # Triggers once on load
)
def update_animated_radar_chart(_load_trigger):
    
    # --- This is the missing logic to create 'df_long' ---
    try:
        df = pd.read_csv("cleaned_data.csv")
    except FileNotFoundError:
        return px.line_polar(title="Error: cleaned_data.csv not found").update_layout(
            plot_bgcolor='rgba(0,0,0,0)', 
            paper_bgcolor='rgba(0,0,0,0)', 
            font=dict(color='#fff')
        )

    # 1. Define the features for the radar
    audio_features = ['valence', 'energy', 'danceability', 'acousticness', 'speechiness', 'instrumentalness']

    # 2. Group by year and get the mean for each feature
    df_year_features = df.groupby('year')[audio_features].mean().reset_index()

    # 3. "Melt" the DataFrame into a "long" format for Plotly
    df_long = pd.melt(df_year_features, 
                      id_vars=['year'], 
                      value_vars=audio_features,
                      var_name='Audio Feature', 
                      value_name='Average Score')
    
    # --- This is your plotting code ---
    fig_radar_animated = px.line_polar(df_long,
                                       r='Average Score',
                                       theta='Audio Feature',
                                       line_close=True,
                                       animation_frame='year', # This is the key change
                                       title='ANIMATED: The Evolving "Sonic Fingerprint" of Music',
                                       color_discrete_sequence=['#1DB954'] # A nice Spotify green
                                      )

    # Set the axis to be 0-1 so it doesn't "jump"
    fig_radar_animated.update_layout(
        title_font_color='white',
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 1],  # Force the axis to be 0 to 1
                color='orange', # Color for the axis line
                tickfont=dict(color='blue') # Color for the numbers
            ),
            angularaxis=dict(
                color='orange', # Color for the axis line
                tickfont=dict(color='orange') # Color for the feature labels
            )
        ),
        # --- Add styling for the dark theme ---
        plot_bgcolor='rgba(0,0,0,0)', 
        paper_bgcolor='rgba(0,0,0,0)', 
        font=dict(color='#fff') # Fallback for other text
    )
    
    return fig_radar_animated

@app.callback(
    Output('corr-song-plot', 'figure'),
    Input('year-filter', 'value')
)
def update_corr_song_plot(selected_year):
    
    # 1. Load data
    try:
        df = pd.read_csv("cleaned_data.csv")
    except FileNotFoundError:
        return px.bar(title="Error: cleaned_data.csv not found").update_layout(
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color='#fff')
        )

    # 2. Filter by selected year
    title_suffix = " (All-Time)"
    if selected_year != 'all_time':
        try:
            df = df[df['year'] == int(selected_year)]
            title_suffix = f" ({selected_year})"
        except ValueError:
            pass # Keep all-time

    # 3. Define features and calculate correlation
    audio_features = ['danceability', 'energy', 'loudness', 'speechiness', 
                      'acousticness', 'instrumentalness', 'liveness', 'valence', 'tempo']
    
    try:
        correlations = df[audio_features + ['popularity']].corr()['popularity'].sort_values(ascending=False)
    except KeyError as e:
        return px.bar(title=f"Error: Missing column {e}").update_layout(
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color='#fff')
        )
        
    correlations = correlations.drop('popularity') # Drop self-correlation
    df_corr_song = correlations.reset_index()
    df_corr_song.columns = ['Feature', 'Correlation']

    # 4. Create the bar chart
    fig_corr_song = px.bar(
        df_corr_song,
        x='Correlation',
        y='Feature',
        orientation='h',
        title='Which Audio Features Correlate with a Hit Song?',
        labels={'Correlation': 'Correlation with Song Popularity', 'Feature': 'Audio Feature'},
        text='Correlation',
        color='Correlation',
        color_continuous_scale='RdBu_r' # Red/Blue diverging scale
    )

    # 5. Style for Dash
    fig_corr_song.update_traces(texttemplate='%{text:.2f}', textposition='outside')
    fig_corr_song.update_layout(
        yaxis={'categoryorder':'total ascending'},
        plot_bgcolor='rgba(0,0,0,0)', 
        paper_bgcolor='rgba(0,0,0,0)', 
        font=dict(color='#fff')
    )
    
    return fig_corr_song


@app.callback(
    Output('corr-artist-plot', 'figure'),
    Input('year-filter', 'value')
)
def update_corr_artist_plot(selected_year):
    
    # 1. Load data
    try:
        df = pd.read_csv("cleaned_data.csv")
    except FileNotFoundError:
        return px.bar(title="Error: cleaned_data.csv not found").update_layout(
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color='#fff')
        )

    # 2. Filter by selected year
    title_suffix = " (All-Time)"
    if selected_year != 'all_time':
        try:
            df = df[df['year'] == int(selected_year)]
            title_suffix = f" ({selected_year})"
        except ValueError:
            pass # Keep all-time

    # 3. Define features
    audio_features = ['danceability', 'energy', 'loudness', 'speechiness', 
                      'acousticness', 'instrumentalness', 'liveness', 'valence', 'tempo']

    # 4. Create the "artist profile" DataFrame
    try:
        df_artist_audio = df.groupby('artist_name')[audio_features].mean()
        df_artist_stats = df.drop_duplicates(subset=['artist_name'])[['artist_name', 'followers']]
        df_artist_stats = df_artist_stats.set_index('artist_name')
        df_profile = pd.merge(df_artist_audio, df_artist_stats, left_index=True, right_index=True)
    except KeyError as e:
        return px.bar(title=f"Error: Missing column {e}").update_layout(
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font=dict(color='#fff')
        )

    # 5. Calculate correlations
    correlations_artist = df_profile[audio_features + ['followers']].corr()['followers'].sort_values(ascending=False)
    correlations_artist = correlations_artist.drop('followers')
    df_corr_artist = correlations_artist.reset_index()
    df_corr_artist.columns = ['Feature', 'Correlation']

    # 6. Create the bar chart
    fig_corr_artist = px.bar(
        df_corr_artist,
        x='Correlation',
        y='Feature',
        orientation='h',
        title='What "Sound" Correlates with More Followers?',
        labels={'Correlation': 'Correlation with Artist Followers', 'Feature': 'Average Audio Feature'},
        text='Correlation',
        color='Correlation',
        color_continuous_scale='RdBu_r'
    )

    # 7. Style for Dash
    fig_corr_artist.update_traces(texttemplate='%{text:.2f}', textposition='outside')
    fig_corr_artist.update_layout(
        yaxis={'categoryorder':'total ascending'},
        plot_bgcolor='rgba(0,0,0,0)', 
        paper_bgcolor='rgba(0,0,0,0)', 
        font=dict(color='#fff')
    )
    
    return fig_corr_artist


if __name__ == "__main__":
    app.run(debug=True, port=8050)