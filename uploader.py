import os
import pickle
import socket
import base64
import io
import streamlit as st
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# הסקופ שנותן רשות להעלות ולנהל סרטונים
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']


def upload_video(file_path, title, description, tags, category_id="24", privacy_status="private", auto_delete=True):
    """
    מעלה סרטון ליוטיוב ומוחק את הקובץ המקומי בסיום.
    """
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

    youtube = build('youtube', 'v3', credentials=creds)

    # --- 2. טיפול בטאגים ---
    if isinstance(tags, str):
        parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]
    elif isinstance(tags, list):
        parsed_tags = tags
    else:
        parsed_tags = []

    print(f"🚀 Starting upload: {title}")

    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': parsed_tags,
            'categoryId': category_id,
            'defaultLanguage': 'en'
        },
        'status': {
            'privacyStatus': privacy_status,
            'selfDeclaredMadeForKids': False
        }
    }

    media = MediaFileUpload(file_path, chunksize=1024 * 1024, resumable=True, mimetype='video/mp4')

    try:
        request = youtube.videos().insert(
            part=','.join(body.keys()),
            body=body,
            media_body=media
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"⏳ Uploaded {int(status.progress() * 100)}%")

        print(f"✅ Success! Video ID: {response['id']}")
        print(f"🔗 URL: https://www.youtube.com/watch?v={response['id']}")

        # מחיקת הקובץ המקומי בסיום
        if auto_delete and os.path.exists(file_path):
            os.remove(file_path)
            print(f"🗑️ Cleaned up and deleted local file: {file_path}")

        return response['id']

    except HttpError as e:
        print(f"🚨 An HTTP error occurred: {e.resp.status} - {e.content}")
        return False
    except socket.error as e:
        print(f"🚨 A socket error occurred: {e}")
        return False