import os
import pickle
import socket
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# הסקופ שנותן רשות להעלות ולנהל סרטונים
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']


def upload_video(self, file_path, title, description, tags, category_id="24", privacy_status="private", auto_delete=True):
    """
    מעלה סרטון ליוטיוב ומוחק את הקובץ המקומי בסיום.
    """
    if not os.path.exists(file_path):
        print(f"🚨 Video file not found: {file_path}")
        return False

    print(f"🚀 Starting upload: {title}")

    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags,
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
        request = self.youtube.videos().insert(
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

        # --- מחיקת הקובץ המקומי בסיום ההעלאה ---
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