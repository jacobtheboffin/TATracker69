from datetime import datetime, timezone
import altair as alt
import sqlite3
import pandas as pd
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import streamlit as st

# --- CONFIGURATION & SETUP ---
st.set_page_config(
    page_title="Objective Judgement Zone", page_icon="🎯", layout="wide"
)

# EMBEDDED PLAYLIST CONFIGURATION
EMBEDDED_PLAYLIST_ID = "7t0Gu2M5ZcwmVtidMb9RRR"

# --- REFINED PREMIUM CSS THEME (FIXED TABS) ---
st.markdown("""
    <style>
        /* Overall App Background & Text */
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
            background-color: #0d0e12 !important;
            color: #f1f3f7 !important;
        }

        /* Sidebar Styling */
        [data-testid="stSidebar"] {
            background-color: #14161b !important;
            border-right: 1px solid #232631 !important;
            padding-top: 1rem;
        }
        
        /* Sidebar Section Headers */
        [data-testid="stSidebar"] h2 {
            color: #ffffff !important;
            font-size: 1.15rem !important;
            font-weight: 700 !important;
            border-bottom: 2px solid #3b82f6 !important;
            padding-bottom: 6px !important;
            margin-top: 1.5rem !important;
            margin-bottom: 1rem !important;
            letter-spacing: 0.5px;
        }

        /* Sidebar Labels & Text Box Titles */
        [data-testid="stSidebar"] label, .stTextInput label, .stCheckbox label {
            color: #cbd5e1 !important;
            font-weight: 500 !important;
            font-size: 14px !important;
        }

        /* Input Fields */
        .stTextInput input {
            background-color: #1a1d26 !important;
            color: #ffffff !important;
            border: 1px solid #2e3445 !important;
            border-radius: 8px !important;
        }
        .stTextInput input:focus {
            border-color: #3b82f6 !important;
            box-shadow: 0 0 0 1px #3b82f6 !important;
        }

        /* Viewport Sticky Tabs Container */
        .main, .block-container {
            overflow: visible !important;
        }

        .stTabs {
            position: sticky;
            top: 0px;
            z-index: 99999;
            background-color: #0d0e12 !important;
            padding-top: 12px;
            padding-bottom: 16px;
            margin-bottom: 24px;
        }
        .stTabs [data-baseweb="tab-list"] {
            background-color: #14161b !important;
            border: 1px solid #2b3040 !important;
            border-radius: 18px !important;
            padding: 10px !important;
            gap: 16px !important;
        }

        /* Smooth, Spacious & Highly Visible Navigation Pills */
        .stTabs [data-baseweb="tab"] {
            font-size: 17px !important;
            font-weight: 600 !important;
            padding: 16px 36px !important; /* Generous breathing room around text */
            color: #e2e8f0 !important;     /* Bright readable text when unselected */
            border-radius: 16px !important;/* Smooth rounded pill shape */
            background-color: #1e2230 !important; /* Soft dark container for contrast */
            border: 1px solid #33394d !important;
            transition: all 0.25s ease-in-out !important;
            margin: 0px !important;
        }
        .stTabs [data-baseweb="tab"]:hover {
            color: #ffffff !important;
            background-color: #2a3145 !important;
            border-color: #60a5fa !important;
            transform: translateY(-1px);
        }
        .stTabs [aria-selected="true"] {
            color: #ffffff !important;
            background-color: #3b82f6 !important; /* Vibrant primary accent */
            border: 1px solid #93c5fd !important;
            font-weight: 700 !important;
            box-shadow: 0 4px 16px rgba(59, 130, 246, 0.4) !important;
        }

        /* Legible Undo Button Styling */
        button[key*="undo_"] {
            background-color: #1f1a1a !important;
            color: #fca5a5 !important;
            border: 1px solid #ef4444 !important;
            border-radius: 6px !important;
            font-weight: 600 !important;
        }
        button[key*="undo_"]:hover {
            background-color: #dc2626 !important;
            color: #ffffff !important;
            border-color: #f87171 !important;
        }

        /* CSV Download Button Styling */
        .stDownloadButton button {
            background-color: #166534 !important;
            color: #ffffff !important;
            border: 1px solid #22c55e !important;
            font-weight: 600 !important;
            padding: 10px 20px !important;
            border-radius: 8px !important;
        }
        .stDownloadButton button:hover {
            background-color: #15803d !important;
            border-color: #4ade80 !important;
        }
    </style>
""", unsafe_allow_html=True)

DB_FILE = "spotify_tracker.db"

# Initialize Database Safely with all required columns
def init_db():
  conn = sqlite3.connect(DB_FILE)
  cursor = conn.cursor()
  
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            id TEXT PRIMARY KEY,
            song_name TEXT,
            artist TEXT,
            uploader TEXT,
            uploader_display_name TEXT,
            image_url TEXT,
            added_at TEXT,
            score INTEGER DEFAULT 0,
            is_saved INTEGER DEFAULT 0,
            is_discovery INTEGER DEFAULT 0,
            judged_at TEXT
        )
    """)
  
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS judgement_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id TEXT,
            song_name TEXT,
            artist TEXT,
            image_url TEXT,
            score INTEGER,
            is_saved INTEGER,
            is_discovery INTEGER,
            timestamp TEXT
        )
    """)

  # Safely ensure missing columns exist on older DB files
  cursor.execute("PRAGMA table_info(tracks)")
  track_columns = [col[1] for col in cursor.fetchall()]
  if "uploader_display_name" not in track_columns:
    cursor.execute("ALTER TABLE tracks ADD COLUMN uploader_display_name TEXT")
  if "image_url" not in track_columns:
    cursor.execute("ALTER TABLE tracks ADD COLUMN image_url TEXT")

  cursor.execute("PRAGMA table_info(judgement_log)")
  log_columns = [col[1] for col in cursor.fetchall()]
  if "image_url" not in log_columns:
    cursor.execute("ALTER TABLE judgement_log ADD COLUMN image_url TEXT")

  conn.commit()
  conn.close()

init_db()

@st.cache_data(show_spinner=False, ttl=3600)
def fetch_user_display_name(client_id, client_secret, user_id):
  if not user_id or user_id == "unknown":
    return "Unknown"
  try:
    auth_manager = SpotifyOAuth(
        client_id=client_id.strip(),
        client_secret=client_secret.strip(),
        redirect_uri="http://127.0.0.1:8888/callback",
        scope="playlist-read-private",
        cache_path=".cache",
    )
    sp = spotipy.Spotify(auth_manager=auth_manager)
    user_info = sp.user(user_id)
    return user_info.get("display_name") or user_id
  except Exception:
    return user_id

# --- SPOTIFY SYNC LOGIC (Using Embedded Playlist) ---
def sync_spotify_playlist(client_id, client_secret, exclude_self):
  if not client_id or not client_secret:
    return 0, 0, 0, ["⚠️ Please fill in your Spotify Client ID and Client Secret."]

  skip_reasons = []

  try:
    auth_manager = SpotifyOAuth(
        client_id=client_id.strip(),
        client_secret=client_secret.strip(),
        redirect_uri="http://127.0.0.1:8888/callback",
        scope="playlist-read-private playlist-read-collaborative",
        open_browser=True,
        cache_path=".cache",
    )
    sp = spotipy.Spotify(auth_manager=auth_manager)

    current_user_id = ""
    user_market = "GB"
    try:
      user_profile = sp.current_user()
      current_user_id = user_profile.get("id", "").lower()
      user_market = user_profile.get("country", "GB")
    except Exception:
      pass

    results = sp.playlist_items(EMBEDDED_PLAYLIST_ID, market=user_market)
    items = results.get("items", [])
    total_found = len(items)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    new_count = 0
    skipped_count = 0

    for item in items:
      if not item:
        continue

      track_info = item.get("item") or item.get("track")
      item_uri = item.get("uri")

      track_id = None
      song_name = "Unknown Track"
      artist = "Unknown Artist"
      image_url = ""

      if track_info and isinstance(track_info, dict):
        track_id = track_info.get("id")
        song_name = track_info.get("name", "Unknown Track")
        artists_list = track_info.get("artists", [])
        if artists_list:
          artist = ", ".join([ar.get("name", "Unknown") for ar in artists_list])
        
        album = track_info.get("album", {})
        images = album.get("images", [])
        if images:
          image_url = images[0].get("url", "")

      if not track_id and item_uri and "spotify:track:" in item_uri:
        track_id = item_uri.split(":")[-1]

      if not track_id:
        skipped_count += 1
        continue

      added_by_obj = item.get("added_by")
      added_by = added_by_obj.get("id", "unknown") if added_by_obj else "unknown"
      added_at = item.get("added_at")

      if exclude_self and current_user_id and added_by.lower() == current_user_id:
        skipped_count += 1
        skip_reasons.append(f"🚫 '{song_name}' — Skipped: Added by you")
        continue

      cursor.execute("SELECT id FROM tracks WHERE id = ?", (track_id,))
      exists = cursor.fetchone()

      if not exists:
        display_name = fetch_user_display_name(client_id, client_secret, added_by)
        cursor.execute(
            """
                INSERT INTO tracks (id, song_name, artist, uploader, uploader_display_name, image_url, added_at, score, is_saved, is_discovery)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
            """,
            (track_id, song_name, artist, added_by, display_name, image_url, added_at),
        )
        new_count += 1
        skip_reasons.append(f"✅ '{song_name}' by {artist} — Successfully Added!")
      else:
        cursor.execute("UPDATE tracks SET image_url = ? WHERE id = ? AND (image_url IS NULL OR image_url = '')", (image_url, track_id))
        skipped_count += 1
        skip_reasons.append(f"⚠️ '{song_name}' — Skipped: Already exists in database")

    conn.commit()
    conn.close()
    return total_found, new_count, skipped_count, skip_reasons
  except Exception as e:
    return 0, 0, 0, [f"❌ Spotify Error: {e}"]

# --- STREAMLIT UI ---
st.title("🎯 Objective Judgement Zone")

# Initialize Session State
if "client_id" not in st.session_state:
  st.session_state.client_id = ""
if "client_secret" not in st.session_state:
  st.session_state.client_secret = ""
if "last_sync_log" not in st.session_state:
  st.session_state.last_sync_log = []
if "last_sync_summary" not in st.session_state:
  st.session_state.last_sync_summary = None
if "is_admin" not in st.session_state:
  st.session_state.is_admin = False

# --- SIDEBAR: ACCESS CONTROL & SETTINGS ---
st.sidebar.header("🔐 Access Control")

if st.session_state.is_admin:
  st.sidebar.success("🔓 Admin Mode Active")
  if st.sidebar.button("🔒 Exit Admin Mode", key="logout_btn"):
    st.session_state.is_admin = False
    st.rerun()
else:
  admin_pass = st.sidebar.text_input("Admin Password", type="password", key="admin_pass_input")
  if admin_pass == "admin123": 
    st.session_state.is_admin = True
    st.rerun()
  else:
    st.sidebar.info("👁️ Viewer Mode (Read-Only)")

st.sidebar.header("⚙️ Settings & Sync")
st.session_state.client_id = st.sidebar.text_input(
    "Spotify Client ID",
    value=st.session_state.client_id,
    type="password",
)
st.session_state.client_secret = st.sidebar.text_input(
    "Spotify Client Secret",
    value=st.session_state.client_secret,
    type="password",
)

exclude_self = st.sidebar.checkbox(
    "Exclude my own added tracks",
    value=False,
    help="Automatically filters out tracks added by your logged-in Spotify account.",
)

if st.sidebar.button("🔄 Sync Playlist Now", type="primary", key="sync_playlist_btn"):
  if not st.session_state.is_admin:
    st.sidebar.warning("⚠️ Admin access required to sync playlist.")
  else:
    with st.spinner("Fetching updates from Spotify..."):
      total_found, added, skipped, reasons = sync_spotify_playlist(
          st.session_state.client_id,
          st.session_state.client_secret,
          exclude_self,
      )
      st.session_state.last_sync_summary = {
          "total": total_found,
          "added": added,
          "skipped": skipped,
      }
      st.session_state.last_sync_log = reasons
      st.rerun()

if st.session_state.is_admin and st.sidebar.button("🗑️ Reset Database", key="reset_db_btn"):
  conn = sqlite3.connect(DB_FILE)
  cursor = conn.cursor()
  cursor.execute("DROP TABLE IF EXISTS tracks")
  cursor.execute("DROP TABLE IF EXISTS judgement_log")
  conn.commit()
  conn.close()
  init_db()
  st.session_state.last_sync_summary = None
  st.session_state.last_sync_log = ["Database wiped clean!"]
  st.sidebar.success("Database wiped clean!")
  st.rerun()

# Persistent Sync Status Box
if st.session_state.last_sync_summary:
  summary = st.session_state.last_sync_summary
  st.success(
      f"Last Sync Complete — Found: {summary['total']} | Added: {summary['added']}"
      f" | Skipped: {summary['skipped']}"
  )

if st.session_state.last_sync_log:
  with st.expander("🔍 Persistent Sync & Skip Details Log", expanded=False):
    for log_entry in st.session_state.last_sync_log:
      st.write(log_entry)

# Navigation Tabs (Conditionally rendered based on Admin status)
if st.session_state.is_admin:
  tab1, tab2, tab3, tab4 = st.tabs([
      "🎯 Judge New Tracks",
      "📜 Judgement History",
      "📊 Live Analytics",
      "📁 Database / Spreadsheet",
  ])
else:
  tab1 = None
  tab2, tab3, tab4 = st.tabs([
      "📜 Judgement History",
      "📊 Live Analytics",
      "📁 Database / Spreadsheet",
  ])

# --- TAB 1: JUDGE NEW TRACKS (Admin Only) ---
if tab1 is not None:
  with tab1:
    st.header("Rate and Review Unjudged Additions")
    
    conn = sqlite3.connect(DB_FILE)
    df_tracks = pd.read_sql(
        "SELECT * FROM tracks WHERE score = 0 OR score IS NULL ORDER BY added_at DESC",
        conn,
    )
    conn.close()

    if df_tracks.empty:
      st.info("No unreviewed tracks left! Sync your playlist for new songs.")
    else:
      for index, row in df_tracks.iterrows():
        uploader_name = row.get('uploader_display_name') or row.get('uploader', 'Unknown')
        with st.expander(f"{row['song_name']} — {row['artist']} (Uploader: {uploader_name})"):
          img_col, form_col = st.columns([1, 4])

          with img_col:
            if row.get("image_url"):
              st.image(row["image_url"], width=130)
            else:
              st.caption("📷 No Cover")

          with form_col:
            col1, col2, col3 = st.columns(3)
            with col1:
              score = st.slider("Score (1-5)", 1, 5, 3, key=f"score_{row['id']}")
            with col2:
              is_saved = st.checkbox("Saved Song?", False, key=f"saved_{row['id']}")
            with col3:
              is_discovery = st.checkbox("Is a Discovery?", False, key=f"disc_{row['id']}")

            if st.button("Save Judgement", key=f"btn_{row['id']}"):
              current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
              conn = sqlite3.connect(DB_FILE)
              cursor = conn.cursor()

              cursor.execute(
                  """
                        UPDATE tracks 
                        SET score = ?, is_saved = ?, is_discovery = ?, judged_at = ?
                        WHERE id = ?
                    """,
                  (score, int(is_saved), int(is_discovery), current_time, row["id"]),
              )

              cursor.execute(
                  """
                        INSERT INTO judgement_log (track_id, song_name, artist, image_url, score, is_saved, is_discovery, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                  (row["id"], row["song_name"], row["artist"], row.get("image_url", ""), score, int(is_saved), int(is_discovery), current_time),
              )

              conn.commit()
              conn.close()

              st.success(f"Judgement saved for '{row['song_name']}'!")
              st.rerun()

# --- TAB 2: JUDGEMENT HISTORY (VERTICAL FEED) ---
with tab2:
  st.header("📜 Live Judgement History Feed")
  st.caption("A History of Failures (and successes)")

  conn = sqlite3.connect(DB_FILE)
  df_history = pd.read_sql("""
      SELECT j.*, t.image_url as track_image_url 
      FROM judgement_log j 
      LEFT JOIN tracks t ON j.track_id = t.id 
      ORDER BY j.id DESC
  """, conn)
  conn.close()

  if df_history.empty:
    st.info("No ratings have been submitted yet.")
  else:
    for _, log in df_history.iterrows():
      with st.container(border=True):
        col_img, col_details, col_actions = st.columns([1, 3.5, 1.2])

        cover_url = log.get("image_url") or log.get("track_image_url")

        with col_img:
          if cover_url:
            st.image(cover_url, width=110)
          else:
            st.caption("📷 No Cover")

        with col_details:
          st.markdown(f"### **{log['song_name']}**")
          st.markdown(f"**Artist:** *{log['artist']}*")
          st.markdown(f"**Score Given:** ⭐ `{log['score']} / 5`")
          
          st.checkbox("Saved Song", value=bool(log["is_saved"]), disabled=True, key=f"feed_saved_{log['id']}")
          st.checkbox("Discovery Track", value=bool(log["is_discovery"]), disabled=True, key=f"feed_disc_{log['id']}")
          
          st.caption(f"🕒 Judged on {log['timestamp']}")

        with col_actions:
          if st.session_state.is_admin:
            if st.button("↩️ Undo", key=f"undo_{log['id']}"):
              conn = sqlite3.connect(DB_FILE)
              cursor = conn.cursor()
              cursor.execute("""
                    UPDATE tracks 
                    SET score = 0, is_saved = 0, is_discovery = 0, judged_at = NULL
                    WHERE id = ?
                """, (log['track_id'],))
              cursor.execute("DELETE FROM judgement_log WHERE id = ?", (log['id'],))
              conn.commit()
              conn.close()
              st.success(f"Reverted '{log['song_name']}'!")
              st.rerun()
          else:
            st.caption("🔒 Admin mode required")

# --- TAB 3: LIVE ANALYTICS ---
with tab3:
  st.header("Performance Review")
  
  if st.session_state.is_admin:
    with st.expander("✏️ Manage Uploader Display Names", expanded=False):
      conn = sqlite3.connect(DB_FILE)
      uploaders_df = pd.read_sql("SELECT DISTINCT uploader, uploader_display_name FROM tracks", conn)
      conn.close()
      
      for _, u_row in uploaders_df.iterrows():
        orig_id = u_row['uploader']
        current_name = u_row['uploader_display_name'] or orig_id
        
        col_u1, col_u2 = st.columns([2, 1])
        with col_u1:
          new_display = st.text_input(f"Display name for: `{orig_id}`", value=current_name, key=f"rename_{orig_id}")
        with col_u2:
          st.markdown("<br>", unsafe_allow_html=True)
          if st.button("Publish Name", key=f"pub_{orig_id}"):
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("UPDATE tracks SET uploader_display_name = ? WHERE uploader = ?", (new_display, orig_id))
            conn.commit()
            conn.close()
            st.success(f"Updated uploader name to '{new_display}'!")
            st.rerun()

  conn = sqlite3.connect(DB_FILE)
  df = pd.read_sql("SELECT * FROM tracks", conn)
  conn.close()

  if df.empty:
    st.info("Not enough data to display analytics yet.")
  else:
    if "uploader_display_name" not in df.columns:
      df["uploader_display_name"] = df.get("uploader", "Unknown")

    analytics = (
        df.groupby("uploader_display_name")
        .agg(
            total_uploads=("id", "count"),
            avg_score=("score", "mean"),
            total_saves=("is_saved", "sum"),
            total_discoveries=("is_discovery", "sum"),
        )
        .reset_index()
        .rename(columns={
            "uploader_display_name": "Uploader",
            "total_uploads": "Total Uploads",
            "avg_score": "Average Score",
            "total_saves": "Total Saves",
            "total_discoveries": "Total Discoveries"
        })
    )
    analytics["Average Score"] = analytics["Average Score"].round(2)

    for _, row in analytics.iterrows():
      with st.container(border=True):
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
          st.markdown(f"**Uploader**\n### {row['Uploader']}")
        with c2:
          st.markdown(f"**Total Uploads**\n### {row['Total Uploads']}")
        with c3:
          st.markdown(f"**Average Score**\n### ⭐ {row['Average Score']}")
        with c4:
          st.markdown(f"**Total Saves**\n### 💾 {row['Total Saves']}")
        with c5:
          st.markdown(f"**Discoveries**\n### ✨ {row['Total Discoveries']}")

    st.subheader("Objectivity Distribution")
    df_judged = df[df["score"] > 0]
    if df_judged.empty:
      st.info("Rate some tracks to view the score distribution graph.")
    else:
      base = alt.Chart(df_judged).encode(
          x=alt.X("uploader_display_name:N", title="Uploader"),
          y=alt.Y("score:Q", title="Score", scale=alt.Scale(domain=[0.5, 5.5])),
          color=alt.Color("uploader_display_name:N", legend=None),
      )
      boxplot = base.mark_boxplot(opacity=0.5, color="#3b82f6")
      points = base.mark_circle(size=80, opacity=0.85, color="#22c55e")
      
      chart = (boxplot + points).properties(
          background="transparent"
      ).configure_axis(
          labelColor="#cbd5e1",
          titleColor="#94a3b8",
          gridColor="#232631"
      ).configure_view(
          stroke="transparent"
      )
      
      st.altair_chart(chart, use_container_width=True)

# --- TAB 4: DATABASE / SPREADSHEET VIEW ---
with tab4:
  st.header("Database View & Spreadsheet Export")
  conn = sqlite3.connect(DB_FILE)
  df_full = pd.read_sql("SELECT * FROM tracks", conn)
  conn.close()

  if df_full.empty:
    st.info("No data in the database yet.")
  else:
    if "uploader_display_name" not in df_full.columns:
      df_full["uploader_display_name"] = df_full.get("uploader", "Unknown")

    cols_to_drop = [c for c in ["id", "uploader", "image_url"] if c in df_full.columns]
    df_full = df_full.drop(columns=cols_to_drop)

    if "added_at" in df_full.columns:
      df_full["added_at"] = (
          pd.to_datetime(df_full["added_at"], errors="coerce")
          .dt.strftime("%Y-%m-%d")
          .fillna(df_full["added_at"])
      )

    if "uploader_display_name" in df_full.columns:
      cols = ["uploader_display_name"] + [col for col in df_full.columns if col != "uploader_display_name"]
      df_full = df_full[cols].rename(columns={"uploader_display_name": "Uploader"})

    if "Uploader" not in df_full.columns:
      df_full["Uploader"] = "Unknown"

    unique_uploaders = df_full["Uploader"].unique()
    palette = [
        "rgba(59, 130, 246, 0.12)",
        "rgba(34, 197, 94, 0.12)",
        "rgba(234, 179, 8, 0.12)",
        "rgba(239, 68, 68, 0.12)",
        "rgba(168, 85, 247, 0.12)",
    ]
    uploader_color_map = {u: palette[i % len(palette)] for i, u in enumerate(unique_uploaders)}

    def style_rows(row):
      color = uploader_color_map.get(row["Uploader"], "")
      return [f"background-color: {color}"] * len(row)

    styled_df = df_full.style.apply(style_rows, axis=1)
    st.dataframe(styled_df, hide_index=True, width="stretch")

    st.markdown("---")
    csv_data = df_full.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download Database as Spreadsheet (CSV)",
        data=csv_data,
        file_name="spotify_tracker_database.csv",
        mime="text/csv",
    )