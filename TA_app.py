from datetime import datetime, timezone
import os
import altair as alt
import requests
import sqlite3
import pandas as pd
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import streamlit as st

# --- CONFIGURATION & SETUP ---
st.set_page_config(
    page_title="Objective Judgement Zone", page_icon="🎯", layout="wide"
)

# SECRETS / ENVIRONMENT CONFIGURATION (Pull from Streamlit Cloud Secrets)
SPOTIFY_CLIENT_ID = st.secrets.get("SPOTIFY_CLIENT_ID", "YOUR_CLIENT_ID_HERE")
SPOTIFY_CLIENT_SECRET = st.secrets.get(
    "SPOTIFY_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE"
)
EMBEDDED_PLAYLIST_ID = st.secrets.get(
    "EMBEDDED_PLAYLIST_ID", "7t0Gu2M5ZcwmVtidMb9RRR"
)

TURSO_URL = st.secrets.get("TURSO_URL", "")
TURSO_AUTH_TOKEN = st.secrets.get("TURSO_AUTH_TOKEN", "")

# Writable cache path for Streamlit Cloud filesystem constraints
SPOTIFY_CACHE_PATH = "/tmp/.cache" if os.path.exists("/tmp") else ".cache"


# --- TURSO HTTP API ADAPTER (Correct Hrana Pipeline Format) ---
class TursoCursor:

  def __init__(self, url, token):
    self.url = url.rstrip("/")
    self.token = token
    self.headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    self.lastrowid = None
    self.description = []
    self._fetchall_data = []

  def execute(self, query, params=()):
    self.description = []
    self._fetchall_data = []
    self.lastrowid = None

    if isinstance(params, tuple):
      params_list = list(params)
    elif isinstance(params, list):
      params_list = params
    else:
      params_list = [params] if params else []

    args = []
    for p in params_list:
      if p is None:
        args.append({"type": "null"})
      elif isinstance(p, (int, float)):
        args.append({
            "type": "float" if isinstance(p, float) else "integer",
            "value": str(p),
        })
      else:
        args.append({"type": "text", "value": str(p)})

    payload = {
        "requests": [
            {
                "type": "execute",
                "stmt": {"sql": query, "args": args},
            },
            {"type": "close"},
        ]
    }

    try:
      resp = requests.post(
          f"{self.url}/v2/pipeline", json=payload, headers=self.headers, timeout=15
      )
      if resp.status_code == 200:
        data = resp.json()
        results = data.get("results", [])
        if results and "response" in results[0]:
          res_body = results[0]["response"]
          cols = res_body.get("cols", [])
          self.description = [
              (col.get("name"), None, None, None, None, None, None)
              for col in cols
          ]

          rows = []
          for row in res_body.get("rows", []):
            row_vals = [
                cell.get("value") if isinstance(cell, dict) else cell
                for cell in row
            ]
            rows.append(row_vals)
          self._fetchall_data = rows
          self.lastrowid = res_body.get("last_insert_rowid")
    except Exception:
      pass

  def fetchone(self):
    if self._fetchall_data:
      return self._fetchall_data.pop(0)
    return None

  def fetchall(self):
    data = self._fetchall_data
    self._fetchall_data = []
    return data

  def close(self):
    pass


class TursoConnection:

  def __init__(self, url, token):
    self.url = url
    self.token = token

  def cursor(self):
    return TursoCursor(self.url, self.token)

  def commit(self):
    pass

  def close(self):
    pass


def get_db_connection():
  if TURSO_URL and TURSO_AUTH_TOKEN:
    return TursoConnection(TURSO_URL, TURSO_AUTH_TOKEN)
  else:
    return sqlite3.connect("spotify_tracker.db")


# --- REFINED PREMIUM CSS THEME ---
st.markdown(
    """
    <style>
        /* Overall App Background & Dark Text Setup */
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
            background-color: #0d0e12 !important;
            color: #ffffff !important;
        }

        /* General Typography & Headers */
        p, span, label, h1, h2, h3, h4, h5, h6, .stMarkdown {
            color: #f8fafc !important;
        }

        /* Sidebar Styling */
        [data-testid="stSidebar"] {
            background-color: #14161b !important;
            border-right: 1px solid #232631 !important;
            padding-top: 1rem;
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

        /* Tab Bar Outer Track */
        .stTabs [data-baseweb="tab-list"] {
            background-color: #14161b !important;
            border: 1px solid #2b3040 !important;
            border-radius: 9999px !important;
            padding: 8px 12px !important;
            gap: 12px !important;
        }

        /* FULLY ROUNDED TAB BUTTONS */
        .stTabs [data-baseweb="tab-list"] button,
        .stTabs button[role="tab"] {
            font-size: 16px !important;
            font-weight: 700 !important;
            padding: 12px 28px !important;
            color: #cbd5e1 !important;     
            border-radius: 9999px !important;
            background-color: #1a1e28 !important; 
            border: 1px solid #333d52 !important;
            transition: all 0.25s ease-in-out !important;
            outline: none !important;
            box-shadow: none !important;
        }

        .stTabs [data-baseweb="tab-highlight-container"],
        [data-baseweb="tab-border-bar"] {
            display: none !important;
        }

        .stTabs button[role="tab"]:hover {
            color: #ffffff !important;
            background-color: #252e3f !important;
            border-color: #60a5fa !important;
        }

        .stTabs button[role="tab"][aria-selected="true"] {
            color: #ffffff !important;
            background-color: #2563eb !important; 
            border: 1px solid #93c5fd !important;
            font-weight: 800 !important;
            box-shadow: 0 4px 18px rgba(37, 99, 235, 0.4) !important;
        }

        button[title="View fullscreen"], [data-testid="stImage"] button {
            display: none !important;
        }

        .stTextInput input {
            background-color: #1e222d !important;
            color: #ffffff !important;
            border: 1px solid #3b4254 !important;
            border-radius: 10px !important;
            padding: 10px 14px !important;
        }
        .stTextInput input:focus {
            border-color: #60a5fa !important;
            box-shadow: 0 0 0 1px #60a5fa !important;
        }

        [data-testid="stVerticalBlockBorderWrapper"] {
            border-color: #2b3040 !important;
            border-radius: 14px !important;
            background-color: #12151e !important;
            margin-bottom: 16px !important;
        }

        .stButton button, button {
            background-color: #1e2530 !important;
            color: #ffffff !important;
            border: 1px solid #4b5563 !important;
            border-radius: 10px !important;
            font-weight: 600 !important;
            padding: 8px 18px !important;
            transition: all 0.2s ease;
        }
        .stButton button:hover, button:hover {
            background-color: #2a3447 !important;
            border-color: #60a5fa !important;
            color: #ffffff !important;
        }

        button[key*="undo_"] {
            background-color: #2b1f1f !important;
            color: #fca5a5 !important;
            border: 1px solid #ef4444 !important;
        }
        button[key*="undo_"]:hover {
            background-color: #dc2626 !important;
            color: #ffffff !important;
        }

        .stDownloadButton button {
            background-color: #166534 !important;
            color: #ffffff !important;
            border: 1px solid #22c55e !important;
        }
        .stDownloadButton button:hover {
            background-color: #15803d !important;
            border-color: #4ade80 !important;
        }

        .feed-score {
            color: #cbd5e1 !important;
            font-weight: 600;
            font-size: 15px;
        }
    </style>
""",
    unsafe_allow_html=True,
)


# Initialize Database Safely
def init_db():
  conn = get_db_connection()
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
        cache_path=SPOTIFY_CACHE_PATH,
    )
    sp = spotipy.Spotify(auth_manager=auth_manager)
    user_info = sp.user(user_id)
    return user_info.get("display_name") or user_id
  except Exception:
    return user_id


def extract_cover_art(sp, track_info, track_id=None):
  if track_info and isinstance(track_info, dict):
    album = track_info.get("album")
    if isinstance(album, dict):
      images = album.get("images", [])
      if images and isinstance(images, list) and len(images) > 0:
        return images[0].get("url", "")

    images = track_info.get("images", [])
    if images and isinstance(images, list) and len(images) > 0:
      return images[0].get("url", "")

  if sp and track_id:
    try:
      full_track = sp.track(track_id)
      album = full_track.get("album", {})
      images = album.get("images", [])
      if images and len(images) > 0:
        return images[0].get("url", "")
    except Exception:
      pass

  return ""


# --- AUTOMATIC SPOTIFY SYNC LOGIC ---
def sync_spotify_playlist():
  if (
      not SPOTIFY_CLIENT_ID
      or not SPOTIFY_CLIENT_SECRET
      or SPOTIFY_CLIENT_ID == "YOUR_CLIENT_ID_HERE"
  ):
    return

  try:
    auth_manager = SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID.strip(),
        client_secret=SPOTIFY_CLIENT_SECRET.strip(),
        redirect_uri="http://127.0.0.1:8888/callback",
        scope="playlist-read-private playlist-read-collaborative",
        open_browser=False,
        cache_path=SPOTIFY_CACHE_PATH,
    )
    sp = spotipy.Spotify(auth_manager=auth_manager)
    user_market = "GB"

    results = sp.playlist_items(EMBEDDED_PLAYLIST_ID, market=user_market)
    items = results.get("items", [])

    conn = get_db_connection()
    cursor = conn.cursor()

    for item in items:
      if not item:
        continue

      track_info = item.get("item") or item.get("track")
      item_uri = item.get("uri")

      track_id = None
      song_name = "Unknown Track"
      artist = "Unknown Artist"

      if track_info and isinstance(track_info, dict):
        track_id = track_info.get("id")
        song_name = track_info.get("name", "Unknown Track")
        artists_list = track_info.get("artists", [])
        if artists_list:
          artist = ", ".join([ar.get("name", "Unknown") for ar in artists_list])

      if not track_id and item_uri and "spotify:track:" in item_uri:
        track_id = item_uri.split(":")[-1]

      if not track_id:
        continue

      image_url = extract_cover_art(sp, track_info, track_id)
      added_by_obj = item.get("added_by")
      added_by = (
          added_by_obj.get("id", "unknown") if added_by_obj else "unknown"
      )
      added_at = item.get("added_at")

      cursor.execute(
          "SELECT id, image_url FROM tracks WHERE id = ?", (track_id,)
      )
      exists = cursor.fetchone()

      if not exists:
        display_name = fetch_user_display_name(
            SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, added_by
        )
        cursor.execute(
            """
                INSERT INTO tracks (id, song_name, artist, uploader, uploader_display_name, image_url, added_at, score, is_saved, is_discovery)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
            """,
            (
                track_id,
                song_name,
                artist,
                added_by,
                display_name,
                image_url,
                added_at,
            ),
        )
      else:
        if image_url and (not exists[1] or str(exists[1]).strip() == ""):
          cursor.execute(
              "UPDATE tracks SET image_url = ? WHERE id = ?",
              (image_url, track_id),
          )

    conn.commit()
    conn.close()
  except Exception as e:
    st.error(f"❌ Spotify Sync Error: {e}")


# Run automatic sync on session startup
if "auto_synced" not in st.session_state:
  sync_spotify_playlist()
  st.session_state.auto_synced = True

# --- STREAMLIT UI ---
st.title("🎯 Objective Judgement Zone")

if "is_admin" not in st.session_state:
  st.session_state.is_admin = False

if st.session_state.is_admin:
  tab1, tab2, tab3, tab4, tab5 = st.tabs([
      "🎯 Judge New Tracks",
      "📜 Judgement History",
      "📊 Live Analytics",
      "📁 Database / Spreadsheet",
      "🔐 Access Control",
  ])
else:
  tab1 = None
  tab2, tab3, tab4, tab5 = st.tabs([
      "📜 Judgement History",
      "📊 Live Analytics",
      "📁 Database / Spreadsheet",
      "🔐 Access Control",
  ])

# --- TAB 1: JUDGE NEW TRACKS (Admin Only) ---
if tab1 is not None:
  with tab1:
    st.header("Rate and Review Unjudged Additions")

    conn = get_db_connection()
    df_tracks = pd.read_sql(
        "SELECT * FROM tracks WHERE score = 0 OR score IS NULL ORDER BY"
        " added_at DESC",
        conn,
    )
    conn.close()

    if df_tracks.empty:
      st.info("No unreviewed tracks left! Playlist is fully judged.")
    else:
      for index, row in df_tracks.iterrows():
        uploader_name = row.get("uploader_display_name") or row.get(
            "uploader", "Unknown"
        )
        with st.expander(
            f"{row['song_name']} — {row['artist']} (Uploader:"
            f" {uploader_name})"
        ):
          img_col, form_col = st.columns([1.2, 3])

          with img_col:
            if row.get("image_url") and str(row["image_url"]).strip():
              st.image(row["image_url"], use_container_width=True)
            else:
              st.caption("📷 No Cover")

          with form_col:
            col1, col2, col3 = st.columns(3)
            with col1:
              score = st.slider("Score (1-5)", 1, 5, 3, key=f"score_{row['id']}")
            with col2:
              is_saved = st.checkbox(
                  "Saved Song?", False, key=f"saved_{row['id']}"
              )
            with col3:
              is_discovery = st.checkbox(
                  "Is a Discovery?", False, key=f"disc_{row['id']}"
              )

            if st.button("Save Judgement", key=f"btn_{row['id']}"):
              current_time = datetime.now(timezone.utc).strftime(
                  "%Y-%m-%d %H:%M:%S UTC"
              )
              conn = get_db_connection()
              cursor = conn.cursor()

              cursor.execute(
                  """
                        UPDATE tracks 
                        SET score = ?, is_saved = ?, is_discovery = ?, judged_at = ?
                        WHERE id = ?
                    """,
                  (
                      score,
                      int(is_saved),
                      int(is_discovery),
                      current_time,
                      row["id"],
                  ),
              )

              cursor.execute(
                  """
                        INSERT INTO judgement_log (track_id, song_name, artist, image_url, score, is_saved, is_discovery, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                  (
                      row["id"],
                      row["song_name"],
                      row["artist"],
                      row.get("image_url", ""),
                      score,
                      int(is_saved),
                      int(is_discovery),
                      current_time,
                  ),
              )

              conn.commit()
              conn.close()

              st.success(f"Judgement saved for '{row['song_name']}'!")
              st.rerun()

PALETTE = ["#3b82f6", "#22c55e", "#eab308", "#ef4444", "#a855f7"]

# --- TAB 2: JUDGEMENT HISTORY (VERTICAL FEED) ---
with tab2:
  st.header("📜 Live Judgement History Feed")
  st.caption("A History of Failures (and successes)")

  conn = get_db_connection()
  df_history = pd.read_sql(
      """
      SELECT j.*, t.image_url as track_image_url, t.uploader, t.uploader_display_name 
      FROM judgement_log j 
      LEFT JOIN tracks t ON j.track_id = t.id 
      ORDER BY j.id DESC
  """,
      conn,
  )
  conn.close()

  if df_history.empty:
    st.info("No ratings have been submitted yet.")
  else:
    unique_uploaders = list(
        df_history["uploader_display_name"].fillna("Unknown").unique()
    )
    color_map = {
        u: PALETTE[i % len(PALETTE)] for i, u in enumerate(unique_uploaders)
    }

    for _, log in df_history.iterrows():
      uploader_name = (
          log.get("uploader_display_name") or log.get("uploader") or "Unknown"
      )
      uploader_color = color_map.get(uploader_name, "#3b82f6")

      with st.container(border=True):
        col_img, col_details, col_actions = st.columns([1.2, 3, 1.2])

        cover_url = log.get("image_url") or log.get("track_image_url")

        with col_img:
          if cover_url and str(cover_url).strip():
            st.image(cover_url, use_container_width=True)
          else:
            st.caption("📷 No Cover")

        with col_details:
          st.markdown(f"### **{log['song_name']}**")
          st.markdown(
              f"**Artist:** *{log['artist']}* | **Uploader:** <span"
              f" style='color:{uploader_color};"
              f" font-weight:bold;'>{uploader_name}</span>",
              unsafe_allow_html=True,
          )
          st.markdown(
              f"**Score Given:** <span class='feed-score'>⭐ {log['score']} /"
              " 5</span>",
              unsafe_allow_html=True,
          )

          st.checkbox(
              "Saved Song",
              value=bool(log["is_saved"]),
              disabled=True,
              key=f"feed_saved_{log['id']}",
          )
          st.checkbox(
              "Discovery Track",
              value=bool(log["is_discovery"]),
              disabled=True,
              key=f"feed_disc_{log['id']}",
          )

          st.caption(f"🕒 Judged on {log['timestamp']}")

        with col_actions:
          if st.session_state.is_admin:
            if st.button("↩️ Undo", key=f"undo_{log['id']}"):
              conn = get_db_connection()
              cursor = conn.cursor()
              cursor.execute(
                  """
                    UPDATE tracks 
                    SET score = 0, is_saved = 0, is_discovery = 0, judged_at = NULL
                    WHERE id = ?
                """,
                  (log["track_id"],),
              )
              cursor.execute(
                  "DELETE FROM judgement_log WHERE id = ?", (log["id"],)
              )
              conn.commit()
              conn.close()
              st.success(f"Reverted '{log['song_name']}'!")
              st.rerun()
          else:
            st.caption("🔒 Admin mode required")

# --- TAB 3: LIVE ANALYTICS ---
with tab3:
  st.header("Performance Review")

  conn = get_db_connection()
  df = pd.read_sql("SELECT * FROM tracks", conn)
  conn.close()

  if df.empty:
    st.info("Not enough data to display analytics yet.")
  else:
    if (
        "uploader_display_name" not in df.columns
        or df["uploader_display_name"].isna().all()
    ):
      df["uploader_display_name"] = df.get("uploader", "Unknown")
    else:
      df["uploader_display_name"] = df["uploader_display_name"].fillna(
          df["uploader"]
      )

    analytics = (
        df.groupby("uploader_display_name")
        .agg(
            total_uploads=("id", "count"),
            avg_score=("score", "mean"),
            total_saves=("is_saved", "sum"),
            total_discoveries=("is_discovery", "sum"),
        )
        .reset_index()
        .rename(
            columns={
                "uploader_display_name": "Uploader",
                "total_uploads": "Total Uploads",
                "avg_score": "Average Score",
                "total_saves": "Total Saves",
                "total_discoveries": "Total Discoveries",
            }
        )
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

      chart = (
          (boxplot + points)
          .properties(background="transparent")
          .configure_axis(
              labelColor="#ffffff", titleColor="#94a3b8", gridColor="#232631"
          )
          .configure_view(stroke="transparent")
      )

      st.altair_chart(chart, use_container_width=True)

# --- TAB 4: DATABASE / SPREADSHEET VIEW ---
with tab4:
  st.header("Database View & Spreadsheet Export")
  conn = get_db_connection()
  df_full = pd.read_sql("SELECT * FROM tracks", conn)
  conn.close()

  if df_full is None or df_full.empty:
    st.info("No data in the database yet. (Or table is still syncing)")
  else:
    if (
        "uploader_display_name" not in df_full.columns
        or df_full["uploader_display_name"].isna().all()
    ):
      df_full["uploader_display_name"] = df_full.get("uploader", "Unknown")
    else:
      df_full["uploader_display_name"] = df_full["uploader_display_name"].fillna(
          df_full["uploader"]
      )

    cols_to_drop = [
        c for c in ["id", "uploader", "image_url"] if c in df_full.columns
    ]
    df_full = df_full.drop(columns=cols_to_drop)

    if "added_at" in df_full.columns:
      df_full["added_at"] = (
          pd.to_datetime(df_full["added_at"], errors="coerce")
          .dt.strftime("%Y-%m-%d")
          .fillna(df_full["added_at"])
      )
      df_full = df_full.rename(columns={"added_at": "Added"})

    if "uploader_display_name" in df_full.columns:
      cols = ["uploader_display_name"] + [
          col for col in df_full.columns if col != "uploader_display_name"
      ]
      df_full = df_full[cols].rename(
          columns={"uploader_display_name": "Uploader"}
      )

    if "Uploader" not in df_full.columns:
      df_full["Uploader"] = "Unknown"

    unique_uploaders = df_full["Uploader"].unique()
    rgba_palette = [
        "rgba(59, 130, 246, 0.15)",
        "rgba(34, 197, 94, 0.15)",
        "rgba(234, 179, 8, 0.15)",
        "rgba(239, 68, 68, 0.15)",
        "rgba(168, 85, 247, 0.15)",
    ]
    uploader_color_map = {
        u: rgba_palette[i % len(rgba_palette)]
        for i, u in enumerate(unique_uploaders)
    }

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

# --- TAB 5: ACCESS CONTROL & ADMIN MANAGEMENT ---
with tab5:
  st.header("🔐 Access Control & Management")

  if st.session_state.is_admin:
    st.success("🔓 Admin Mode Active (Full Control)")
    if st.button("🔒 Exit Admin Mode / Logout", key="tab_logout_btn"):
      st.session_state.is_admin = False
      st.rerun()

    st.markdown("---")
    st.subheader("✏️ Manage Uploader Display Names")
    st.caption(
        "Change and publish custom display names for uploaders across"
        " analytics and charts."
    )

    conn = get_db_connection()
    uploaders_df = pd.read_sql(
        "SELECT DISTINCT uploader, uploader_display_name FROM tracks", conn
    )
    conn.close()

    for _, u_row in uploaders_df.iterrows():
      orig_id = u_row["uploader"]
      current_name = u_row["uploader_display_name"] or orig_id

      col_u1, col_u2 = st.columns([2, 1])
      with col_u1:
        new_display = st.text_input(
            f"Display name for uploader ID: `{orig_id}`",
            value=str(current_name),
            key=f"rename_{orig_id}",
        )
      with col_u2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Publish Name", key=f"pub_{orig_id}"):
          conn = get_db_connection()
          cursor = conn.cursor()
          cursor.execute(
              "UPDATE tracks SET uploader_display_name = ? WHERE uploader = ?",
              (new_display, orig_id),
          )
          conn.commit()
          conn.close()
          st.success(f"Updated uploader name to '{new_display}'!")
          st.rerun()

    st.markdown("---")
    if st.button("🗑️ Reset Entire Database", key="reset_db_btn"):
      conn = get_db_connection()
      cursor = conn.cursor()
      cursor.execute("DROP TABLE IF EXISTS tracks")
      cursor.execute("DROP TABLE IF EXISTS judgement_log")
      conn.commit()
      conn.close()
      init_db()
      st.success("Database wiped clean!")
      st.rerun()
  else:
    st.info("👁️ You are currently browsing in **Viewer Mode** (Read-Only).")
    admin_pass = st.text_input(
        "Enter Admin Password to Unlock Management",
        type="password",
        key="main_admin_pass",
    )
    if admin_pass == "admin123":
      st.session_state.is_admin = True
      st.success("Access granted!")
      st.rerun()