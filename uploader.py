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


class YouTubeUploader:
    def __init__(self, client_secrets_file="client_secrets.json", token_file="token.pickle"):
        self.client_secrets_file = client_secrets_file
        self.token_file = token_file
        self.youtube = self._authenticate()

    def _authenticate(self):
        """מבצע אימות מול גוגל ומחזיר את שירות ה-API"""
        creds = None

        # ניסיון לטעון טוקן קיים (כדי לא לבקש לוגין כל פעם)
        if os.path.exists(self.token_file):
            with open(self.token_file, 'rb') as token:
                creds = pickle.load(token)

        # אם אין טוקן תקף, מבצעים לוגין חדש
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                print("🔄 Refreshing access token...")
                try:
                    creds.refresh(Request())
                except Exception:
                    # אם ה-Refresh נכשל, מבצעים לוגין מלא מחדש
                    creds = self._perform_full_login()
            else:
                creds = self._perform_full_login()

            # שמירת הטוקן החדש להרצות הבאות
            with open(self.token_file, 'wb') as token:
                pickle.dump(creds, token)

        return build('youtube', 'v3', credentials=creds)

    def _perform_full_login(self):
        """מבצע לוגין מלא בדפדפן"""
        print("🔐 Authenticating through browser...")
        if not os.path.exists(self.client_secrets_file):
            raise FileNotFoundError(f"🚨 Missing {self.client_secrets_file} in project folder!")

        flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_file, SCOPES)
        # מריץ שרת מקומי זמני לקבלת האישור
        creds = flow.run_local_server(port=0, prompt='consent', timeout_seconds=60)
        return creds

    def upload_video(self, file_path, title, description, tags, category_id="24", privacy_status="private"):
        """
        מעלה סרטון ליוטיוב.
        category_id: 24 (Entertainment), 22 (People & Blogs), 27 (Education)
        privacy_status: 'public', 'private', 'unlisted'
        """
        if not os.path.exists(file_path):
            print(f"🚨 Video file not found: {file_path}")
            return False

        print(f"🚀 Starting upload: {title}")

        # בניית גוף הבקשה (Metadata)
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
                # אם אתה רוצה שהסרטון יוגדר כ"מיועד לילדים" (חובה לבחור):
                'selfDeclaredMadeForKids': False
            }
        }

        # הגדרת המדיה להעלאה (עם אפשרות ל-Resumable אם הקובץ גדול)
        media = MediaFileUpload(file_path, chunksize=1024 * 1024, resumable=True, mimetype='video/mp4')

        try:
            request = self.youtube.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media
            )

            # ביצוע ההעלאה עם מד התקדמות
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f"⏳ Uploaded {int(status.progress() * 100)}%")

            print(f"✅ Success! Video ID: {response['id']}")
            print(f"🔗 URL: https://www.youtube.com/watch?v={response['id']}")
            return response['id']

        except HttpError as e:
            print(f"🚨 An HTTP error occurred: {e.resp.status} - {e.content}")
            return False
        except socket.error as e:
            print(f"🚨 A socket error occurred: {e}")
            return False