import os
import pickle
import socket
import base64
import io
import mimetypes
import streamlit as st
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# הסקופ שנותן רשות להעלות ולנהל סרטונים
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']


def upload_video(file_path, title, description, tags, category_id="24", privacy_status="public", auto_delete=True, thumbnail_path=None, language='en', localizations=None):
    """
    מעלה סרטון ליוטיוב, מגדיר שפה ותמונה ממוזערת (אופציונלי), ומוחק את הקובץ המקומי בסיום.
    """
    if not os.path.exists(file_path):
        print(f"🚨 Video file not found: {file_path}")
        return False

    # --- 1. טעינת הרשאות ואימות מול יוטיוב (נשאר ללא שינוי) ---
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

    youtube = build('youtube', 'v3', credentials=creds)

    # --- 2. טיפול בטאגים (נשאר ללא שינוי) ---
    if isinstance(tags, str):
        parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]
    elif isinstance(tags, list):
        parsed_tags = tags
    else:
        parsed_tags = []

    print(f"🚀 Starting upload: {title}", flush=True)

    # --- 3. בניית גוף הבקשה (body) עם שפה ותרגומים ---
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': parsed_tags,
            'categoryId': category_id,
            # הגדרת השפה (דיפולט 'en')
            'defaultLanguage': language,
            'defaultAudioLanguage': language
        },
        'status': {
            'privacyStatus': privacy_status,
            'selfDeclaredMadeForKids': False
        }
    }

    # הוספת תרגומים אם סופקו
    if localizations and isinstance(localizations, dict):
        body['localizations'] = localizations

    media = MediaFileUpload(file_path, chunksize=1024 * 1024, resumable=True, mimetype='video/mp4')

    try:
        # יצירת בקשת ההעלאה
        request = youtube.videos().insert(
            part=','.join(body.keys()),
            body=body,
            media_body=media
        )

        # ביצוע ההעלאה בצ'אנקים (נשאר ללא שינוי)
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"⏳ Uploaded {int(status.progress() * 100)}%", flush=True)

        video_id = response['id']
        print(f"✅ Success! Video ID: {video_id}", flush=True)

        # --- 4. NEW: העלאת תמונה ממוזערת (Thumbnail) אם סופקה ---
        if thumbnail_path and os.path.exists(thumbnail_path):
            try:
                print(f"🖼️ Uploading thumbnail: {thumbnail_path}", flush=True)

                # זיהוי אוטומטי של mimetype (image/jpeg או image/png)
                mime_type, _ = mimetypes.guess_type(thumbnail_path)
                if mime_type is None:
                    mime_type = 'application/octet-stream'  # Fallback

                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(thumbnail_path, mimetype=mime_type)
                ).execute()
                print("✅ Thumbnail uploaded successfully!", flush=True)

            except Exception as e:
                print(f"⚠️ Failed to upload thumbnail: {e}", flush=True)
                # לא מחזירים False, כי הוידאו עצמו עלה בהצלחה

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