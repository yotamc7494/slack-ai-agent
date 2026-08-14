import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from moviepy.editor import VideoClip, VideoFileClip, AudioFileClip, CompositeVideoClip, CompositeAudioClip
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
      ' via Yahoo API...'
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


def make_animated_comparison_chart(v1, v2, ticker1, ticker2, start_year, investment, duration, size=(1080, 1920)):
    n_original = len(v1)

    n_dense = 1000
    x_orig = np.arange(n_original)
    x_dense = np.linspace(0, n_original - 1, n_dense)

    interp_1 = PchipInterpolator(x_orig, v1.values)
    interp_2 = PchipInterpolator(x_orig, v2.values)

    y1_dense = interp_1(x_dense)
    y2_dense = interp_2(x_dense)

    y_max = max(max(y1_dense), max(y2_dense))
    y_min = 90

    fig, ax = plt.subplots(figsize=(size[0] / 100, size[1] / 100), dpi=100)
    canvas = FigureCanvasAgg(fig)

    def render_rgba_frame(t):
        ax.clear()

        fig.patch.set_facecolor(BG_COLOR)
        ax.set_facecolor(BG_COLOR)
        ax.grid(True, color=GRID_COLOR, linestyle='--', linewidth=1, alpha=0.5)

        idx = int((t / duration) * (n_dense - 1))
        idx = max(1, min(idx, n_dense - 1))

        sub_x = x_dense[:idx + 1]
        sub_y1 = y1_dense[:idx + 1]
        sub_y2 = y2_dense[:idx + 1]

        # ציור הקווים וההצללות
        ax.plot(sub_x, sub_y1, color=COLOR_1, linewidth=6, label=ticker1)
        ax.fill_between(sub_x, sub_y1, y_min, color=COLOR_1, alpha=0.1)

        ax.plot(sub_x, sub_y2, color=COLOR_2, linewidth=6, label=ticker2)
        ax.fill_between(sub_x, sub_y2, y_min, color=COLOR_2, alpha=0.1)

        # נקודות קצה
        ax.plot(sub_x[-1], sub_y1[-1], marker='o', markersize=12, color=COLOR_1)
        ax.plot(sub_x[-1], sub_y2[-1], marker='o', markersize=12, color=COLOR_2)

        v1_curr = sub_y1[-1]
        v2_curr = sub_y2[-1]

        # תוויות מחיר דינמיות
        ax.text(sub_x[-1], v1_curr + (y_max * 0.03), f"{ticker1}\n${v1_curr:,.0f}",
                color=COLOR_1, fontsize=24, fontweight='bold', ha='center', va='bottom',
                bbox=dict(boxstyle="round,pad=0.3", facecolor=BG_COLOR, edgecolor=COLOR_1, alpha=0.85))

        ax.text(sub_x[-1], v2_curr + (y_max * 0.03), f"{ticker2}\n${v2_curr:,.0f}",
                color=COLOR_2, fontsize=24, fontweight='bold', ha='center', va='bottom',
                bbox=dict(boxstyle="round,pad=0.3", facecolor=BG_COLOR, edgecolor=COLOR_2, alpha=0.85))

        ax.set_xlim(- (n_dense * 0.05), n_dense + (n_dense * 0.1))
        ax.set_ylim(y_min, y_max * 1.35)  # מרווח נשימה לכותרת

        ax.tick_params(axis='both', colors='white', labelsize=18)
        ax.set_xticks([])
        for spine in ax.spines.values(): spine.set_visible(False)

        # 🟢 כותרת עליונה מרכזית (במקום TextClip של MoviePy!)
        header_text = f"IF YOU INVESTED ${investment}\nIN {ticker1} vs {ticker2} IN {start_year}..."
        fig.text(0.5, 0.90, header_text, color='white', fontsize=26, fontweight='bold',
                 ha='center', va='top', bbox=dict(boxstyle="square,pad=0.5", facecolor="#141A26", edgecolor=GRID_COLOR, alpha=0.9))

        canvas.draw()
        return np.asarray(canvas.buffer_rgba())[:, :, :3]

    chart_clip = VideoClip(render_rgba_frame, duration=duration)
    plt.close(fig)
    return chart_clip


def create_comparison_fomo_video(ticker1, ticker2, music_path, output_filename="fomo_comparison.mp4"):
    duration = 30
    investment = 100

    v1, v2, start_year = get_comparison_data(ticker1, ticker2, investment)
    if v1 is None:
        print("❌ Could not generate video due to data fetch error.")
        return
    print(f"🎬 Generating Video For {ticker1} vs {ticker2}")
    # 1. יצירת קליפ הגרף (הכולל כעת גם את הכותרת בתוכו)
    chart_clip = make_animated_comparison_chart(v1, v2, ticker1, ticker2, start_year, investment, duration)

    # 2. רקע מוחשך
    background = VideoFileClip("trading_floor_loop.mp4").loop(duration=duration)
    background = background.resize(height=1920).crop(x_center=background.w / 2, width=1080)
    background = background.fl_image(lambda frame: (frame * 0.1).astype('uint8'))

    # 3. הרכבה (בלי TextClip!)
    final_video = CompositeVideoClip([
        background,
        chart_clip.set_position("center")
    ], size=(1080, 1920))

    # 4. אודיו
    if os.path.exists(music_path):
        bg_music = AudioFileClip(music_path)

        # 1. טיפול נכון באורך: אם קצר - בלופ, אם ארוך - נחתך
        if bg_music.duration < duration:
            bg_music = bg_music.fx(audio_loop, duration=duration)
        else:
            bg_music = bg_music.subclip(0, duration)

        # 2. הנמכת ווליום (כדי שרושם/דיבוב ישמעו) + Fade Out ב-2 השניות האחרונות
        bg_music = bg_music.fx(volumex, 0.15).fx(audio_fadeout, 2)

        # 3. שילוב המוזיקה עם הדיבוב הקיים (במקום לדרוס אותו)
        if final_video.audio is not None:
            final_audio = CompositeAudioClip([final_video.audio, bg_music])
        else:
            final_audio = bg_music

        final_video = final_video.set_audio(final_audio)

    print(f"🎬 Rendering final video: {output_filename}...")
    final_video.write_videofile(output_filename, fps=24, codec='libx264', audio_codec="aac",
            logger=None,
            threads=1,
            preset="ultrafast"
        )
    print("✅ Done!")
    return output_filename


def run_generator(test_mode=False):
    MUSIC_PATH = "comparison_music.mp3"
    # במידה ואין קובץ מוזיקה עדיין
    if not os.path.exists(MUSIC_PATH):
        MUSIC_PATH = ""

    return create_comparison_fomo_video("NVDA", "TSLA", MUSIC_PATH, "nvda_vs_tsla.mp4")