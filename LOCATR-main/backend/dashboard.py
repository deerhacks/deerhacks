import streamlit as st
import pandas as pd
import pydeck as pdk
import plotly.graph_objects as go
import numpy as np

try:
    from snowflake.snowpark.context import get_active_session
except ImportError:
    st.error("snowflake-snowpark-python is missing. Please install it.")
    get_active_session = None

VIBE_KEYWORDS = [
    "aesthetic", "cozy", "chill", "trendy", "hipster", "romantic", "classy", 
    "upscale", "fancy", "elegant", "modern", "rustic", "bohemian", "artsy", 
    "quirky", "retro", "vintage", "minimalist", "industrial", "dark academia", 
    "cottagecore", "cyberpunk", "neon", "instagrammable", "photogenic", "cute",
    "charming", "intimate", "lively", "energetic", "fun", "exciting", "relaxing",
    "peaceful", "calm", "serene", "warm", "inviting", "atmosphere", "ambiance",
    "mood", "theme", "decor", "design", "beautiful", "pretty", "gorgeous",
    "stunning", "spacious", "unique"
]

st.set_page_config(layout="wide", page_title="Pathfinder: Aesthetic DNA")

@st.cache_resource
def init_connection():
    try:
        if get_active_session is not None:
            return get_active_session()
    except Exception:
        pass
    
    from snowflake.snowpark import Session
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    connection_parameters = {
        "user": os.getenv("SNOWFLAKE_USER"),
        "password": os.getenv("SNOWFLAKE_PASSWORD"),
        "account": os.getenv("SNOWFLAKE_ACCOUNT"),
        "warehouse": "PATHFINDER_WH",
        "database": "PATHFINDER_DB",
        "schema": "INTELLIGENCE",
        "autocommit": True
    }
    return Session.builder.configs(connection_parameters).create()

session = init_connection()

# 1. Fetch Data & Unpack Vector
@st.cache_data
def get_vibe_data():
    # Notice we bypass VECTOR_L2_NORM here completely to avoid SQL errors
    # We will do the math in pandas if Snowflake functions are blocked
    pdf = session.sql("""
        SELECT 
            NAME, 
            PRIMARY_VIBE, 
            H3_INDEX,
            LATITUDE, LONGITUDE,
            CAST(VIBE_VECTOR AS ARRAY) as DNA_STR
        FROM CAFE_VIBE_VECTORS
    """).to_pandas()
    
    # Process the strings back into python arrays
    import json
    pdf['DNA'] = pdf['DNA_STR'].apply(lambda x: json.loads(x) if isinstance(x, str) else x)
    
    # Calculate Magnitude (STRENGTH) in Python safely
    pdf['STRENGTH'] = pdf['DNA'].apply(lambda vec: float(np.linalg.norm(vec)))
    return pdf

@st.cache_data
def get_risk_data():
    try:
        return session.sql("""
            SELECT 
                vr.VENUE_NAME, 
                vr.RISK_DESCRIPTION,
                c.LATITUDE as lat,
                c.LONGITUDE as lng
            FROM VENUE_RISK_EVENTS vr
            JOIN CAFE_VIBE_VECTORS c ON vr.VENUE_ID = c.VENUE_ID
        """).to_pandas()
    except Exception:
        return pd.DataFrame()

df = get_vibe_data()
risk_df = get_risk_data()

# 2. Sidebar: Comparison Mode
st.sidebar.header("🧬 DNA Comparison")
selected_cafes = st.sidebar.multiselect("Pick two cafes to compare DNA:", df['NAME'].tolist(), max_selections=2)

st.sidebar.markdown("---")
st.sidebar.header("🏜️ Vibe Opportunity")

if not df.empty:
    # Aggregate to find the desert (Lowest average strength per H3 hexagon)
    h3_stats = df.groupby('H3_INDEX')['STRENGTH'].agg(['mean', 'count']).reset_index()
    # Filter for areas with at least 2 cafes to be a "desert" not just an empty tile
    deserts = h3_stats[h3_stats['count'] >= 2].sort_values('mean')
    if not deserts.empty:
        lowest_h3 = deserts.iloc[0]['H3_INDEX']
        lowest_score = deserts.iloc[0]['mean']
        st.sidebar.error(f"**Aesthetic Desert Alert!**\nH3 Hexagon: `{lowest_h3}`\nAverage Strength: **{lowest_score:.2f}**\n\n*High opportunity for a new vibe injection here!*")

# 3. The 3D Vibe Landscape
st.title("🏙️ Toronto Aesthetic Topography")
st.markdown("Height represents **Aesthetic Intensity**. Color represents **Primary Vibe**.")

layers = []

# Base Map Layer
if not df.empty:
    # The PyDeck Color requirement: [STRENGTH * 255, 100, 255 - (STRENGTH * 255), 160]
    # We construct a color column so it's statically evaluated
    def make_color(strength):
        r = int(min(255, max(0, strength * 255)))
        b = int(min(255, max(0, 255 - (strength * 255))))
        return [r, 100, b, 160]
        
    df['fill_color'] = df['STRENGTH'].apply(make_color)
    
    layer = pdk.Layer(
        "ColumnLayer",
        df,
        get_position=["LONGITUDE", "LATITUDE"],
        get_elevation="STRENGTH * 1000",
        elevation_scale=1,
        radius=50,
        get_fill_color="fill_color",
        pickable=True,
        auto_highlight=True,
    )
    layers.append(layer)

# The Danger Overlay
if not risk_df.empty:
    danger_layer = pdk.Layer(
        "ScatterplotLayer",
        risk_df,
        get_position=["lng", "lat"],
        get_radius=150,
        get_fill_color=[255, 0, 0, 255], # Pulsing Red Circles
        get_line_color=[255, 255, 255, 100],
        line_width_min_pixels=3,
        pickable=True,
    )
    layers.append(danger_layer)

view_state = pdk.ViewState(latitude=43.65, longitude=-79.38, zoom=13, pitch=45)
st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view_state, tooltip={"text": "{NAME} ({PRIMARY_VIBE})"}))

# 4. The Radar DNA Comparison
if len(selected_cafes) == 2:
    st.subheader("🧬 Aesthetic DNA Overlap")
    fig = go.Figure()

    for cafe in selected_cafes:
        cafe_data = df[df['NAME'] == cafe].iloc[0]
        fig.add_trace(go.Scatterpolar(
            r=cafe_data['DNA'],
            theta=VIBE_KEYWORDS, # Mapped Keywords instead of Dim 1...
            fill='toself',
            name=cafe
        ))

    fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 1])), showlegend=True)
    st.plotly_chart(fig, use_container_width=True)
