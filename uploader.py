import base64
import io
import mimetypes
import os
import pickle
import socket
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
import streamlit as st

# סקופים: הרשאה להעלאת סרטונים + הרשאה לניהול/פרסום תגובות
SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.force-ssl',
]


def add_affiliate_comment(youtube_client, video_id):
  """מפרסם תגובת אפילייט מובילה עם CTA חזק מיד לאחר העלאת הסרטון."""
  comment_text = """🚀 Upgrade your stock research! Get $15 OFF TradingView here:
👉 https://www.tradingview.com/?aff_id=169872&source=yt

📊 Real-time charts, stock screeners & market data used for all channel updates!"""

  try:
    print(f"💬 Posting affiliate comment to video {video_id}...", flush=True)
    youtube_client.commentThreads().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {
                    "snippet": {"textOriginal": comment_text}
                },
            }
        },
    ).execute()
    print("✅ Affiliate comment posted successfully!", flush=True)
  except Exception as e:
    print(f"⚠️ Failed to post affiliate comment: {e}", flush=True)


def upload_video(
    file_path,
    title,
    description,
    tags,
    category_id="24",
    privacy_status="public",
    auto_delete=True,
    thumbnail_path=None,
    language="en",
    localizations=None,
    affiliate_comment=True
):
  """מעלה סרטון ליוטיוב, מגדיר שפה, תמונה ממוזערת, מפרסם תגובת אפילייט, ומוחק את הקובץ המקומי בסיום."""
  if not os.path.exists(file_path):
    print(f"🚨 Video file not found: {file_path}")
    return False

  # --- 1. טעינת הרשאות ואימות מול יוטיוב ---
  creds = None

  if "YOUTUBE_TOKEN_PICKLE_BASE64" in st.secrets:
    try:
      token_base64 = st.secrets["YOUTUBE_TOKEN_PICKLE_BASE64"]
      token_bytes = base64.b64decode(token_base64)
      creds = pickle.load(io.BytesIO(token_bytes))
    except Exception as e:
      print(f"⚠️ Failed to decode token from st.secrets: {e}")
  elif os.path.exists("token.pickle"):
    with open("token.pickle", "rb") as token:
      creds = pickle.load(token)

  if creds and creds.expired and creds.refresh_token:
    try:
      creds.refresh(Request())
    except Exception as e:
      print(f"🚨 Token refresh failed: {e}")
      creds = None

  if not creds or not creds.valid:
    print("🚨 No valid YouTube credentials found!")
    return False

  youtube = build("youtube", "v3", credentials=creds)

  # --- 2. טיפול בטאגים ---
  if isinstance(tags, str):
    parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]
  elif isinstance(tags, list):
    parsed_tags = tags
  else:
    parsed_tags = []

  print(f"🚀 Starting upload: {title}", flush=True)

  # --- 3. בניית גוף הבקשה (body) ---
  description = f"""📊 Best Stock Charting Tool (Get $15 Off):
👉 https://www.tradingview.com/?aff_id=169872&source=yt
---
{description}
"""
  body = {
      "snippet": {
          "title": title,
          "description": description,
          "tags": parsed_tags,
          "categoryId": category_id,
          "defaultLanguage": language,
          "defaultAudioLanguage": language,
      },
      "status": {
          "privacyStatus": privacy_status,
          "selfDeclaredMadeForKids": False,
      },
  }

  if localizations and isinstance(localizations, dict):
    body["localizations"] = localizations

  media = MediaFileUpload(
      file_path, chunksize=1024 * 1024, resumable=True, mimetype="video/mp4"
  )

  try:
    # יצירת בקשת ההעלאה
    request = youtube.videos().insert(
        part=",".join(body.keys()), body=body, media_body=media
    )

    # ביצוע ההעלאה בצ'אנקים
    response = None
    while response is None:
      status, response = request.next_chunk()
      if status:
        print(f"⏳ Uploaded {int(status.progress() * 100)}%", flush=True)

    video_id = response["id"]
    print(f"✅ Success! Video ID: {video_id}", flush=True)

    # --- 4. העלאת תמונה ממוזערת (Thumbnail) אם סופקה ---
    if thumbnail_path and os.path.exists(thumbnail_path):
      try:
        print(f"🖼️ Uploading thumbnail: {thumbnail_path}", flush=True)
        mime_type, _ = mimetypes.guess_type(thumbnail_path)
        if mime_type is None:
          mime_type = "application/octet-stream"

        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_path, mimetype=mime_type),
        ).execute()
        print("✅ Thumbnail uploaded successfully!", flush=True)
      except Exception as e:
        print(f"⚠️ Failed to upload thumbnail: {e}", flush=True)

    # --- 5. NEW: פרסום תגובת אפילייט אוטומטית ---
    if affiliate_comment:
        add_affiliate_comment(youtube, video_id)

    print(f"🔗 URL: https://www.youtube.com/watch?v={video_id}", flush=True)

    # מחיקת הקובץ המקומי בסיום
    if auto_delete and os.path.exists(file_path):
      os.remove(file_path)
      print(f"🗑️ Cleaned up and deleted local file: {file_path}", flush=True)

    return video_id

  except HttpError as e:
    print(f"🚨 An HTTP error occurred: {e.resp.status} - {e.content}")
    return False
  except socket.error as e:
    print(f"🚨 A socket error occurred: {e}")
    return False