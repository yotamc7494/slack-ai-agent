import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from moviepy.editor import VideoClip, VideoFileClip, AudioFileClip, CompositeVideoClip, CompositeAudioClip,vfx
from moviepy.audio.fx.audio_fadeout import audio_fadeout
from moviepy.audio.fx.audio_loop import audio_loop
from moviepy.audio.fx.volumex import volumex
from scipy.interpolate import PchipInterpolator
import os
import requests
import tempfile
import time

# --- הגדרות עיצוב ---
BG_COLOR = "#131722"
GRID_COLOR = "#2A3447"
COLOR_1 = "#00E676"  # ירוק ניאון למניה א'
COLOR_2 = "#2979FF"  # כחול ניאון למניה ב'

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
  header_text = (
      f"IF YOU INVESTED ${investment}\nIN {ticker1} vs {ticker2} IN"
      f" {start_year}..."
  )
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
    ax.plot(sub_x, sub_y1, color=COLOR_1, linewidth=6, label=ticker1)
    ax.fill_between(sub_x, sub_y1, min(sub_y1), color=COLOR_1, alpha=0.1)

    ax.plot(sub_x, sub_y2, color=COLOR_2, linewidth=6, label=ticker2)
    ax.fill_between(sub_x, sub_y2, min(sub_y2), color=COLOR_2, alpha=0.1)

    # נקודות קצה
    ax.plot(sub_x[-1], sub_y1[-1], marker="o", markersize=12, color=COLOR_1)
    ax.plot(sub_x[-1], sub_y2[-1], marker="o", markersize=12, color=COLOR_2)

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
        f"{ticker1}\n${v1_curr:,.0f}",
        color=COLOR_1,
        fontsize=24,
        fontweight="bold",
        ha="center",
        va="bottom",
        bbox=dict(
            boxstyle="round,pad=0.3",
            facecolor=BG_COLOR,
            edgecolor=COLOR_1,
            alpha=0.85,
        ),
    )

    ax.text(
        sub_x[-1],
        v2_curr + (current_y_max * 0.03),
        f"{ticker2}\n${v2_curr:,.0f}",
        color=COLOR_2,
        fontsize=24,
        fontweight="bold",
        ha="center",
        va="bottom",
        bbox=dict(
            boxstyle="round,pad=0.3",
            facecolor=BG_COLOR,
            edgecolor=COLOR_2,
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
    ticker1, ticker2, music_path, output_filename="fomo_comparison.mp4"
):
  duration = 60
  fps = 15  # ⚡ 15 FPS מספק זרימה חלקה לגרפים ומקצר את זמן הרינדור ב-40%!
  investment = 1000

  v1, v2, start_year = get_comparison_data(ticker1, ticker2, investment)
  if v1 is None:
    print("❌ Could not generate video due to data fetch error.", flush=True)
    return

  print(f"🎬 Generating Video For {ticker1} vs {ticker2}", flush=True)

  # 1. יצירת קליפ הגרף
  chart_clip = make_animated_comparison_chart(
      v1, v2, ticker1, ticker2, start_year, investment, duration
  )

  # 2. רקע מוחשך
  background = (
      VideoFileClip("trading_floor_loop.mp4")
      .loop(duration=duration)
      .without_audio()
  )
  background = background.resize(height=1920).crop(
      x_center=background.w / 2, width=1080
  )
  background = background.fx(vfx.colorx, 0.1)

  # 3. הרכבה
  final_video = CompositeVideoClip(
      [background, chart_clip.set_position("center")], size=(1080, 1920)
  ).set_duration(duration)

  # 4. אודיו
  audio_tracks = []
  if final_video.audio is not None:
    existing_audio = final_video.audio
    if existing_audio.duration:
      existing_audio = existing_audio.subclip(
          0, min(existing_audio.duration, duration)
      )
    audio_tracks.append(existing_audio)

  if music_path and os.path.exists(music_path):
    bg_music = AudioFileClip(music_path)
    if bg_music.duration < duration:
      bg_music = bg_music.fx(vfx.audio_loop, duration=duration)

    bg_music = (
        bg_music.subclip(0, duration)
        .fx(vfx.volumex, 0.15)
        .fx(vfx.audio_fadeout, 2)
    )
    audio_tracks.append(bg_music)

  if audio_tracks:
    final_audio = CompositeAudioClip(audio_tracks).set_duration(duration)
    final_video = final_video.set_audio(final_audio)

  print(f"🎬 Rendering final video: {output_filename}...", flush=True)

  # ⚡ הרינדור הבטוח: ללא Deadlock ב-FFmpeg Pipe
  final_video.write_videofile(
      output_filename,
      fps=fps,
      codec="libx264",
      audio_codec="aac",
      temp_audiofile="temp-audio.m4a",
      remove_temp=True,
      threads=1,  # threads=1 מונע התנגשויות זיכרון ב-Streamlit Cloud
      preset="ultrafast",
      write_logfile=False,  # מונע כתיבת לוגים כבדים לדיסק
  )

  # ניקוי משאבים בסיום
  chart_clip.close()
  background.close()
  final_video.close()

  print("✅ Done!", flush=True)
  return output_filename


def run_generator(test_mode=False):
    MUSIC_PATH = "comparison_music.mp3"
    # במידה ואין קובץ מוזיקה עדיין
    if not os.path.exists(MUSIC_PATH):
        MUSIC_PATH = ""

    return create_comparison_fomo_video("NVDA", "TSLA", MUSIC_PATH, "nvda_vs_tsla.mp4")