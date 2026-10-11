from datetime import datetime, timezone
import json
import os
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

SPOTIFY_CLIENT_ID = st.secrets.get("SPOTIFY_CLIENT_ID", "YOUR_CLIENT_ID_HERE")
SPOTIFY_CLIENT_SECRET = st.secrets.get(
    "SPOTIFY_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE"
)
EMBEDDED_PLAYLIST_ID = st.secrets.get(
    "EMBEDDED_PLAYLIST_ID", "7t0Gu2M5ZcwmVtidMb9RRR"
)

TURSO_URL = st.secrets.get("TURSO_URL", "")
TURSO_AUTH_TOKEN = st.secrets.get("TURSO_AUTH_TOKEN", "")

# --- SAFE CACHE LOADER (ROBUST FOR STRINGS OR DICTS) ---
SPOTIFY_CACHE_PATH = "/tmp/.cache"
if "SPOTIFY_CACHE_JSON" in st.secrets:
  try:
    cache_data = st.secrets["SPOTIFY_CACHE_JSON"]
    if isinstance(cache_data, str):
      parsed = json.loads(cache_data)
    else:
      parsed = dict(cache_data)
    with open(SPOTIFY_CACHE_PATH, "w") as f:
      json.dump(parsed, f)
  except Exception as e:
    st.error(f"⚠️ Cache JSON error: {e}")


# --- SAFE IMAGE EXTRACTOR HELPER ---
def extract_image_url(track_info):
  """Safely extracts image URL from track_info regardless of data type variations."""
  try:
    album = track_info.get("album", {})
    if isinstance(album, dict):
      images = album.get("images", [])
      if isinstance(images, list) and len(images) > 0:
        first_img = images[0]
        if isinstance(first_img, dict):
          return first_img.get("url", "")
        elif isinstance(first_img, str):
          return first_img
      elif isinstance(images, str):
        return images
  except Exception:
    pass
  return ""


# --- HARDENED TURSO HTTP API ADAPTER ---
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
          res_item = results[0]
          if res_item.get("type") == "error":
            print(f"Turso Pipeline Error: {res_item}")
            return

          res_body = res_item["response"]
          if res_body.get("type") == "error":
            print(f"Turso SQL Error: {res_body.get('error')}")
            return

          sql_result = res_body.get("result", res_body)

          cols = sql_result.get("cols", [])
          if cols:
            self.description = [
                (col.get("name"), None, None, None, None, None, None)
                for col in cols
            ]

          rows = []
          for row in sql_result.get("rows", []):
            row_vals = [
                cell.get("value") if isinstance(cell, dict) else cell
                for cell in row
            ]
            rows.append(row_vals)
          self._fetchall_data = rows
          self.lastrowid = sql_result.get("last_insert_rowid")
      else:
        print(f"Turso HTTP Error {resp.status_code}: {resp.text}")
    except Exception as e:
      print(f"Turso Request Exception: {e}")

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


def load_df_from_query(query, conn, params=()):
  """Safely loads query results into a pandas DataFrame using cursor execution."""
  cursor = conn.cursor()
  cursor.execute(query, params)
  rows = cursor.fetchall()
  cols = [desc[0] for desc in cursor.description] if cursor.description else []
  if not cols and rows:
    cols = [f"col_{i}" for i in range(len(rows[0]))]
  return pd.DataFrame(rows, columns=cols)


# --- STYLING ---
st.markdown(
    """
    <style>
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] { background-color: #0d0e12 !important; color: #ffffff !important; }
        p, span, label, h1, h2, h3, h4, h5, h6, .stMarkdown { color: #f8fafc !important; }
        [data-testid="stSidebar"] { background-color: #14161b !important; border-right: 1px solid #232631 !important; }
        .stTabs { position: sticky; top: 0px; z-index: 99999; background-color: #0d0e12 !important; padding-top: 12px; padding-bottom: 16px; }
        .stTabs [data-baseweb="tab-list"] { background-color: #14161b !important; border: 1px solid #2b3040 !important; border-radius: 9999px !important; padding: 8px 12px !important; gap: 12px !important; }
        .stTabs [data-baseweb="tab-list"] button, .stTabs button[role="tab"] { font-size: 16px !important; font-weight: 700 !important; padding: 12px 28px !important; color: #cbd5e1 !important; border-radius: 9999px !important; background-color: #1a1e28 !important; border: 1px solid #333d52 !important; }
        .stTabs button[role="tab"][aria-selected="true"] { color: #ffffff !important; background-color: #2563eb !important; border: 1px solid #93c5fd !important; }
        .feed-score { color: #cbd5e1 !important; font-weight: 600; font-size: 15px; }
    </style>
""",
    unsafe_allow_html=True,
)


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
    results = sp.playlist_items(EMBEDDED_PLAYLIST_ID, market="GB")
    items = results.get("items", [])

    conn = get_db_connection()
    cursor = conn.cursor()

    for item in items:
      if not item:
        continue
      track_info = item.get("item") or item.get("track")
      if not track_info:
        continue
      track_id = track_info.get("id")
      song_name = track_info.get("name", "Unknown Track")
      artist = ", ".join(
          [ar.get("name", "Unknown") for ar in track_info.get("artists", [])]
      )

      image_url = extract_image_url(track_info)

      added_by_obj = item.get("added_by")
      added_by = (
          added_by_obj.get("id", "unknown") if added_by_obj else "unknown"
      )
      added_at = item.get("added_at")

      cursor.execute("SELECT id FROM tracks WHERE id = ?", (track_id,))
      if not cursor.fetchone():
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
                added_by,
                image_url,
                added_at,
            ),
        )
    conn.commit()
    conn.close()
  except Exception as e:
    st.sidebar.error(
        f"Spotify Sync Notice: {e}. (If invalid_grant, please refresh your"
        " SPOTIFY_CACHE_JSON secret)"
    )


if "auto_synced" not in st.session_state:
  sync_spotify_playlist()
  st.session_state.auto_synced = True

st.title("🎯 Objective Judgement Zone")

if "is_admin" not in st.session_state:
  st.session_state.is_admin = False

if st.session_state.is_admin:
  tab1, tab2, tab3, tab4, tab5 = st.tabs([
      "🎯 Judge & Rejudge",
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

# --- TAB 1: JUDGE & REJUDGE ALL TRACKS ---
if tab1 is not None:
  with tab1:
    st.header("Rate, Review & Rejudge Tracks")
    st.caption(
        "All playlist tracks are listed below. You can update your ratings or"
        " score new ones at any time."
    )

    conn = get_db_connection()
    df_tracks = load_df_from_query(
        "SELECT * FROM tracks ORDER BY added_at DESC", conn
    )
    conn.close()

    if df_tracks.empty:
      st.info("No tracks found in the database.")
    else:
      for _, row in df_tracks.iterrows():
        current_score = (
            int(row["score"]) if row["score"] and row["score"] > 0 else 3
        )
        current_saved = bool(row["is_saved"])
        current_disc = bool(row["is_discovery"])
        uploader_name = row.get("uploader_display_name") or row.get(
            "uploader", "Unknown"
        )

        with st.expander(
            f"{row['song_name']} — {row['artist']} (Uploader: {uploader_name})"
            f" | ⭐ {row['score'] if row['score'] else 'Unjudged'}"
        ):
          img_col, form_col = st.columns([1.2, 3])
          with img_col:
            if row.get("image_url"):
              st.image(row["image_url"], width="stretch")
            else:
              st.caption("No Cover")
          with form_col:
            c1, c2, c3 = st.columns(3)
            with c1:
              score = st.slider(
                  "Score (1-5)",
                  1,
                  5,
                  current_score,
                  key=f"score_{row['id']}",
              )
            with c2:
              is_saved = st.checkbox(
                  "Saved Song?",
                  current_saved,
                  key=f"saved_{row['id']}",
              )
            with c3:
              is_discovery = st.checkbox(
                  "Is a Discovery?",
                  current_disc,
                  key=f"disc_{row['id']}",
              )

            if st.button("Save / Update Judgement", key=f"btn_{row['id']}"):
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
              st.success(f"Updated judgement for '{row['song_name']}'!")
              st.rerun()

PALETTE = ["#3b82f6", "#22c55e", "#eab308", "#ef4444", "#a855f7"]

# --- TAB 2: HISTORY ---
with tab2:
  st.header("📜 Live Judgement History Feed")
  conn = get_db_connection()
  df_history = load_df_from_query(
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
    st.info(
        "No ratings submitted yet. Rate tracks in Tab 1 to populate the history"
        " log."
    )
  else:
    for _, log in df_history.iterrows():
      with st.container(border=True):
        c1, c2, c3 = st.columns([1.2, 3, 1.2])
        with c1:
          if log.get("image_url") or log.get("track_image_url"):
            st.image(
                log.get("image_url") or log.get("track_image_url"),
                width="stretch",
            )
        with c2:
          st.markdown(f"### **{log['song_name']}**")
          st.markdown(
              f"**Artist:** *{log['artist']}* | **Score:** ⭐ {log['score']}/5"
          )
          st.caption(f"🕒 Judged on {log['timestamp']}")
        with c3:
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
              st.rerun()

# --- TAB 3: ANALYTICS ---
with tab3:
  st.header("Performance Review")
  conn = get_db_connection()
  df = load_df_from_query("SELECT * FROM tracks", conn)
  conn.close()
  if df.empty or df["score"].sum() == 0:
    st.info("Not enough judged data for analytics yet.")
  else:
    df_judged = df[df["score"] > 0]
    st.dataframe(df_judged[["song_name", "artist", "score"]], width="stretch")

# --- TAB 4: DATABASE ---
with tab4:
  st.header("Database View")
  conn = get_db_connection()
  df_full = load_df_from_query("SELECT * FROM tracks", conn)
  conn.close()
  if df_full.empty:
    st.info("Database is currently empty.")
  else:
    st.dataframe(df_full, width="stretch")
    st.download_button(
        "Download CSV",
        df_full.to_csv(index=False).encode("utf-8"),
        "tracks.csv",
        "text/csv",
    )

# --- TAB 5: ACCESS CONTROL ---
with tab5:
  st.header("🔐 Access Control")
  if st.session_state.is_admin:
    st.success("🔓 Admin Mode Active")
    if st.button("🔒 Logout"):
      st.session_state.is_admin = False
      st.rerun()

    st.markdown("---")
    if st.button("🗑️ Wipe Database"):
      conn = get_db_connection()
      cursor = conn.cursor()
      cursor.execute("DROP TABLE IF EXISTS tracks")
      cursor.execute("DROP TABLE IF EXISTS judgement_log")
      conn.commit()
      conn.close()
      init_db()
      st.success("Wiped clean.")
      st.rerun()
  else:
    st.info("Enter admin password (`admin123`) to access tools.")
    p = st.text_input("Password", type="password")
    if p == "admin123":
      st.session_state.is_admin = True
      st.rerun()