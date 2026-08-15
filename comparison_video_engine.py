import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from moviepy.editor import VideoClip
from scipy.interpolate import PchipInterpolator
import requests
import tempfile
import time
import os
from uploader import upload_video
import random
import moviepy.audio.fx.all as afx
from moviepy.editor import (
    AudioFileClip,
    concatenate_videoclips
)
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv
load_dotenv()

# --- הגדרות עיצוב ---
BG_COLOR = "#131722"
GRID_COLOR = "#2A3447"

try:
  cache_dir = os.path.join(tempfile.gettempdir(), "yf_cache")
  os.makedirs(cache_dir, exist_ok=True)
  yf.set_tz_cache_location(cache_dir)
except Exception:
  pass


def fetch_yahoo_chart_direct(ticker, period='max', interval='1wk'):
  """מושך נתוני מניה ישירות מ-API ה-Chart של Yahoo Finance ללא תלות ב-yfinance."""
  url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={period}&interval={interval}'
  headers = {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
          ' (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
      )
  }

  for attempt in range(3):
    try:
      response = requests.get(url, headers=headers, timeout=10)
      if response.status_code == 200:
        data = response.json()
        result = data['chart']['result'][0]

        timestamps = result['timestamp']
        closes = result['indicators']['quote'][0]['close']

        # יצירת DataFrame נקי
        df = pd.DataFrame(
            {'Close': closes},
            index=pd.to_datetime(timestamps, unit='s', utc=True),
        )
        df.index = df.index.tz_localize(
            None
        )  # הסרת Timezone לסנכרון קל בין מניות
        df = df.dropna()

        if not df.empty:
          return df['Close']
      elif response.status_code == 429:
        print(f'⚠️ Rate limit hit for {ticker}, retrying in 3s...')
        time.sleep(3)
    except Exception as e:
      print(f'⚠️ Error fetching {ticker} (attempt {attempt+1}): {e}')
      time.sleep(2)

  return pd.Series(dtype=float)


def get_comparison_data(ticker1, ticker2, initial_investment=100):
  print(
      f'📥 Fetching historical data for {ticker1} and {ticker2} directly'
      ' via Yahoo API...',flush=True
  )

  # משיכה ישירה של שתי המניות
  h1 = fetch_yahoo_chart_direct(ticker1, period='max', interval='1wk')
  time.sleep(1)  # השהייה קצרה מונעת עומס על ה-API
  h2 = fetch_yahoo_chart_direct(ticker2, period='max', interval='1wk')

  if h1.empty or h2.empty:
    print('❌ Failed to fetch data from Yahoo Finance API.')
    return None, None, None

  # מציאת תאריך התחלה משותף (ה-IPO המאוחר מבין השניים)
  start_date = max(h1.index[0], h2.index[0])

  h1_aligned = h1[h1.index >= start_date]
  h2_aligned = h2[h2.index >= start_date]

  # סנכרון אינדקסים לפי תאריכים משותפים בלבד
  common_index = h1_aligned.index.intersection(h2_aligned.index)
  h1_final = h1_aligned.loc[common_index]
  h2_final = h2_aligned.loc[common_index]

  if h1_final.empty or h2_final.empty:
    return None, None, None

  # נרמול ל-100$
  v1 = (h1_final / h1_final.iloc[0]) * initial_investment
  v2 = (h2_final / h2_final.iloc[0]) * initial_investment

  return v1, v2, start_date.year


def make_animated_comparison_chart(
    v1,
    v2,
    ticker1,
    ticker2,
    start_year,
    investment,
    duration,
    color1,
    color2,
    header_text,
    size=(1080, 1920),
):
  n_original = len(v1)
  n_dense = 1000
  x_orig = np.arange(n_original)
  x_dense = np.linspace(0, n_original - 1, n_dense)

  interp_1 = PchipInterpolator(x_orig, v1.values)
  interp_2 = PchipInterpolator(x_orig, v2.values)

  y1_dense = interp_1(x_dense)
  y2_dense = interp_2(x_dense)

  fig, ax = plt.subplots(figsize=(size[0] / 100, size[1] / 100), dpi=100)
  canvas = FigureCanvasAgg(fig)

  fig.patch.set_facecolor(BG_COLOR)
  fig.text(
      0.5,
      0.90,
      header_text,
      color="white",
      fontsize=26,
      fontweight="bold",
      ha="center",
      va="top",
      bbox=dict(
          boxstyle="square,pad=0.5",
          facecolor="#141A26",
          edgecolor=GRID_COLOR,
          alpha=0.9,
      ),
  )

  # 🟢 אובייקט הטקסט של התאריך (מוגדר פעם אחת בחוץ כדי למנוע זליגת זיכרון)
  date_text_obj = fig.text(
      0.5,
      0.82,  # מיקום קצת מתחת לכותרת הראשית
      "",
      color="white",
      fontsize=24,
      fontweight="bold",
      ha="center",
      va="top",
  )

  # חילוץ התאריכים (בהנחה ש-v1 הוא Pandas Series מ-yfinance)
  try:
    dates = v1.index.strftime("%b %Y")  # פורמט לדוגמה: Jan 2020
  except AttributeError:
    # גיבוי למקרה שאין אינדקס תאריכים
    dates = [str(start_year)] * n_original

  def render_rgba_frame(t):
    ax.clear()

    ax.set_facecolor(BG_COLOR)
    ax.grid(True, color=GRID_COLOR, linestyle="--", linewidth=1, alpha=0.5)

    # 1. חישוב מיקום נוכחי וקצב ההתקדמות (מ-0 עד 1)
    progress = min(t / duration, 1.0)
    idx = int(progress * (n_dense - 1))
    idx = max(1, idx)

    # 2. עדכון התאריך על המסך לפי המיקום המקורי
    idx_orig = int(progress * (n_original - 1))
    idx_orig = min(max(0, idx_orig), n_original - 1)
    date_text_obj.set_text(dates[idx_orig])

    sub_x = x_dense[: idx + 1]
    sub_y1 = y1_dense[: idx + 1]
    sub_y2 = y2_dense[: idx + 1]

    # ציור הקווים
    ax.plot(sub_x, sub_y1, color=color1, linewidth=6, label=ticker1)
    ax.fill_between(sub_x, sub_y1, min(sub_y1), color=color1, alpha=0.1)

    ax.plot(sub_x, sub_y2, color=color2, linewidth=6, label=ticker2)
    ax.fill_between(sub_x, sub_y2, min(sub_y2), color=color2, alpha=0.1)

    # נקודות קצה
    ax.plot(sub_x[-1], sub_y1[-1], marker="o", markersize=12, color=color1)
    ax.plot(sub_x[-1], sub_y2[-1], marker="o", markersize=12, color=color2)

    v1_curr = sub_y1[-1]
    v2_curr = sub_y2[-1]

    # 3. 🟢 סקייל Y דינמי לחלוטין - מבוסס על הערכים הנוכחיים בלבד
    current_y_max = max(np.max(sub_y1), np.max(sub_y2))
    current_y_min = min(np.min(sub_y1), np.min(sub_y2))
    ax.set_ylim(current_y_min * 0.85, current_y_max * 1.35)

    # 4. 🟢 סקייל X דינמי - הגרף תמיד ייפרס על פני כל המסך
    x_max = max(10, sub_x[-1])
    ax.set_xlim(-(x_max * 0.05), x_max + (x_max * 0.15))

    # תוויות מחיר
    ax.text(
        sub_x[-1],
        v1_curr + (current_y_max * 0.03),
        f"{ticker1}\n${v1_curr:,.1f}",
        color=color1,
        fontsize=24,
        fontweight="bold",
        ha="center",
        va="bottom",
        bbox=dict(
            boxstyle="round,pad=0.3",
            facecolor=BG_COLOR,
            edgecolor=color1,
            alpha=0.85,
        ),
    )

    ax.text(
        sub_x[-1],
        v2_curr + (current_y_max * 0.03),
        f"{ticker2}\n${v2_curr:,.1f}",
        color=color2,
        fontsize=24,
        fontweight="bold",
        ha="center",
        va="bottom",
        bbox=dict(
            boxstyle="round,pad=0.3",
            facecolor=BG_COLOR,
            edgecolor=color2,
            alpha=0.85,
        ),
    )

    ax.tick_params(axis="both", colors="white", labelsize=18)
    ax.set_xticks([])
    for spine in ax.spines.values():
      spine.set_visible(False)

    canvas.draw()
    return np.asarray(canvas.buffer_rgba())[:, :, :3]

  chart_clip = VideoClip(render_rgba_frame, duration=duration)
  plt.close(fig)  # ניקוי מהותי למניעת תקיעות RAM
  return chart_clip


def create_comparison_fomo_video(
        ticker1, ticker2, music_path, investment,output_filename="fomo_comparison.mp4"
):
    duration = 60
    fps = 15


    v1, v2, start_year = get_comparison_data(ticker1, ticker2, investment)
    if v1 is None:
        print("❌ Could not generate video due to data fetch error.", flush=True)
        return

    print(f"🎬 Generating Video For {ticker1} vs {ticker2}", flush=True)

    # 🟢 4. צבעים אקראיים וייחודיים מתוך פלטה
    palette = ['#00E676', '#FF1744', '#29B6F6', '#FFA000', '#E040FB', '#1DE9B6', '#FFEA00']
    c1, c2 = random.sample(palette, 2)

    # 🟢 2. יצירת הגרף (הוא עצמו משמש כוידאו, אין צורך ב-Trading floor ברקע)
    ai_data = generate_fomo_metadata_and_header_with_ai(ticker1, ticker2, investment, start_year)
    chart_clip = make_animated_comparison_chart(
        v1, v2, ticker1, ticker2, start_year, investment, duration, c1, c2, ai_data["video_header"]
    )

    # 🟢 3. הקפאת הפריים האחרון לשנייה נוספת
    freeze_frame = chart_clip.to_ImageClip(t=duration - 0.1).set_duration(1.0)
    final_video = concatenate_videoclips([chart_clip, freeze_frame])

    # האורך הכולל עכשיו הוא 31 שניות
    total_duration = duration + 1.0

    # 🟢 1. אודיו מתוקן (מבוסס על total_duration כדי שהמוזיקה תמשיך גם בשנייה הקפואה)
    if music_path and os.path.exists(music_path):
        print("🎵 Adding background music...", flush=True)
        bg_music = AudioFileClip(music_path)

        # לופ במידת הצורך
        if bg_music.duration < total_duration:
            bg_music = bg_music.fx(afx.audio_loop, duration=total_duration)

        # חיתוך מדויק והנמכת ווליום באמצעות fx
        bg_music = (
            bg_music.subclip(0, total_duration)
            .fx(afx.volumex, 0.15)
            .fx(afx.audio_fadeout, 2)
        )

        # הדבקה ישירה של השמע לווידאו
        final_video = final_video.set_audio(bg_music)
    else:
        print("⚠️ Music file not found!", flush=True)

    print(f"🎬 Rendering final video: {output_filename}...", flush=True)

    final_video.write_videofile(
        output_filename,
        fps=fps,
        codec="libx264",
        audio_codec="aac",
        audio_fps=44100,  # ⚡ מבטיח קידוד אודיו סטנדרטי למניעת השתקה בנגנים מסוימים
        temp_audiofile="temp-audio.m4a",
        remove_temp=True,
        threads=1,
        preset="ultrafast",
        write_logfile=False,
    )

    # ניקוי
    chart_clip.close()
    final_video.close()

    print("✅ Done!", flush=True)
    return ai_data


def generate_fomo_metadata_and_header_with_ai(
    ticker1, ticker2, investment, start_year
):
  # תמיכה בכתיבה גם מקובץ env וגם מ-Streamlit Secrets
  api_key = os.environ.get("GEMINI_API_KEY")
  if not api_key:
    try:
      import streamlit as st

      api_key = st.secrets.get("GEMINI_API_KEY")
    except Exception:
      pass

  if not api_key:
    raise ValueError("🚨 GEMINI_API_KEY is missing!")

  client = genai.Client(api_key=api_key)

  prompt = f"""
        You are a viral financial content creator for TikTok, YouTube Shorts, and Instagram Reels.
        Create both the ON-SCREEN HEADER text and the social media metadata for an animated racing-chart video.

        Video Context:
        - Ticker 1: {ticker1}
        - Ticker 2: {ticker2}
        - Scenario: What happens if you invested ${investment} in {ticker1} vs {ticker2} in {start_year}.
        - Vibe: FOMO (Fear Of Missing Out), high-stakes financial comparison.

        CRITICAL RULES:
        1. "video_header": SHORT, 3 to 6 words maximum in ALL CAPS for the top overlay inside the video frame. Must be high-energy (e.g. "IF YOU INVESTED $100 IN...", "$100 IN NVDA VS TSLA", "WHICH ONE CREATED MORE MILLIONAIRES?").
        2. "youtube_title": Clickbait-y title with emojis (e.g., $100 in NVDA vs TSLA! 🤯 Who Won?).
        3. "description": Short, punchy summary ending with an engaging question to drive comments.
        4. "tags": 5-7 comma-separated tags without spaces after commas (e.g., {ticker1},{ticker2},Stocks,Investing,Trading,Wealth).

        STRICT OUTPUT FORMAT:
        Return ONLY a valid JSON object with the following 4 fields:
        {{
          "video_header": "SHORT IN-VIDEO HEADER TEXT IN ALL CAPS",
          "youtube_title": "High-CTR title with emojis",
          "description": "Short summary ending with a question for comments",
          "tags": "5-7 tags separated by commas"
        }}
        """

  response = client.models.generate_content(
      model="gemini-flash-lite-latest",
      contents=prompt,
      config=types.GenerateContentConfig(response_mime_type="application/json"),
  )

  return json.loads(response.text)


def run_generator(test_mode=False):
    MUSIC_PATH = f"assets/suspense_music/{random.choice([1,2,3])}.mp3"
    # במידה ואין קובץ מוזיקה עדיין
    if not os.path.exists(MUSIC_PATH):
        MUSIC_PATH = ""

    TICKERS = [
        # טכנולוגיה ושבבים (הונפקו בשנות ה-80 וה-90)
        "AAPL",  # Apple (1980)
        "MSFT",  # Microsoft (1986)
        "AMZN",  # Amazon (1997)
        "NVDA",  # Nvidia (1999)
        "AMD",  # AMD (1972)
        "INTC",  # Intel (1971)
        "CSCO",  # Cisco Systems (1990)
        "ORCL",  # Oracle (1986)
        "QCOM",  # Qualcomm (1991)
        "ADBE",  # Adobe (1986)
        "MU",  # Micron (1984)
        "MSTR",  # MicroStrategy (1998)

        # צרכנות, מותגים וקמעונאות מוכרים
        "WMT",  # Walmart (1972)
        "COST",  # Costco (1985)
        "HD",  # Home Depot (1981)
        "KO",  # Coca-Cola (1919)
        "PEP",  # PepsiCo (1919)
        "MCD",  # McDonald's (1965)
        "NKE",  # Nike (1980)
        "SBUX",  # Starbucks (1992)
        "DIS",  # Disney (1957)

        # פיננסים, בריאות ותעשייה
        "BRK-B",  # Berkshire Hathaway Class B (1996)
        "JPM",  # JPMorgan Chase (לפני 2000)
        "LLY",  # Eli Lilly (1952)
        "JNJ",  # Johnson & Johnson (1944)
        "PFE",  # Pfizer (1942)
        "XOM",  # ExxonMobil (לפני 2000)
        "UNH",  # UnitedHealth (1984)

        # מדדים ותעודות סל שהושקו לפני 2000
        "SPY",  # SPDR S&P 500 ETF (הושקה ב-1993, החליפה את VOO שהושקה ב-2010)
        "QQQ"  # Invesco QQQ (הושקה ב מרץ 1999)
    ]

    # בחירה אקראית של 2 טיקרים שונים
    ticker1, ticker2 = random.sample(TICKERS, 2)

    # יצירת שם קובץ דינמי
    output_filename = f"{ticker1}_vs_{ticker2}.mp4"
    investment = random.choice([100, 200, 500, 1000])
    upload_data = create_comparison_fomo_video(ticker1, ticker2, MUSIC_PATH, investment, output_filename)

    if test_mode:
        return output_filename
    else:
        upload_video(output_filename, upload_data["youtube_title"], upload_data["description"], upload_data['tags'])
        return output_filename


