import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from moviepy.editor import VideoClip, VideoFileClip, AudioFileClip, CompositeVideoClip
from scipy.interpolate import PchipInterpolator
import os
import time

# --- הגדרות עיצוב ---
BG_COLOR = "#131722"
GRID_COLOR = "#2A3447"
COLOR_1 = "#00E676"  # ירוק ניאון למניה א'
COLOR_2 = "#2979FF"  # כחול ניאון למניה ב'


def get_comparison_data(ticker1, ticker2, initial_investment=100):
    print(f"📥 Fetching historical data for {ticker1} and {ticker2}...")

    df = None
    for attempt in range(3):
        try:
            df = yf.download(
                tickers=f"{ticker1} {ticker2}",
                period="max",
                interval="1wk",
                progress=False,
                auto_adjust=True
            )
            if not df.empty:
                break
        except Exception as e:
            print(f"⚠️ Attempt {attempt + 1} failed: {e}")
            time.sleep(2)

    if df is None or df.empty:
        return None, None, None

    try:
        close_df = df['Close'] if isinstance(df.columns, pd.MultiIndex) else df
        h1 = close_df[ticker1].dropna()
        h2 = close_df[ticker2].dropna()
    except KeyError as e:
        print(f"❌ Could not find ticker column: {e}")
        return None, None, None

    if h1.empty or h2.empty:
        return None, None, None

    start_date = max(h1.index[0], h2.index[0])
    h1_aligned = h1[h1.index >= start_date]
    h2_aligned = h2[h2.index >= start_date]

    common_index = h1_aligned.index.intersection(h2_aligned.index)
    h1_final = h1_aligned.loc[common_index]
    h2_final = h2_aligned.loc[common_index]

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
        audio = AudioFileClip(music_path).set_duration(duration).audio_fadeout(2)
        final_video = final_video.set_audio(audio)

    print(f"🎬 Rendering final video: {output_filename}...")
    final_video.write_videofile(output_filename, fps=24, codec='libx264', audio_codec='aac')
    print("✅ Done!")


def run_generator(test_mode=False):
    MUSIC_PATH = "comparison_music.mp3"
    # במידה ואין קובץ מוזיקה עדיין
    if not os.path.exists(MUSIC_PATH):
        MUSIC_PATH = ""

    create_comparison_fomo_video("NVDA", "TSLA", MUSIC_PATH, "nvda_vs_tsla.mp4")