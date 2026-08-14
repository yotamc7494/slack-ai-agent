import time
import yfinance as yf
import pandas as pd
import numpy as np
import time
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from moviepy.editor import VideoClip, VideoFileClip, AudioFileClip, CompositeVideoClip, TextClip
from scipy.interpolate import PchipInterpolator
import os

# --- הגדרות עיצוב (TradingView Dark Style) ---
BG_COLOR = "#131722"
GRID_COLOR = "#2A3447"
COLOR_1 = "#00E676"  # ירוק ניאון למניה א'
COLOR_2 = "#2979FF"  # כחול ניאון למניה ב'
FONT_NAME = "Arial"  # וודא שהפונט מותקן במערכת


# --- חלק 1: משיכת נתונים וסנכרון (The Logic) ---
def get_comparison_data(ticker1, ticker2, initial_investment=100):
    print(f"📥 Fetching historical data for {ticker1} and {ticker2} in a single batch...")

    # 💡 קריאה מרוכזת אחת ל-2 הטיקרים ביחד כדי למנוע YFRateLimitError
    df = None
    for attempt in range(3):  # מנגנון ניסיונות חוזרים אם יאהו עמוס
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
            time.sleep(2)  # השהייה קצרה בין ניסיון לניסיון

    if df is None or df.empty:
        print("❌ Failed to fetch data due to Yahoo rate limits.")
        return None, None, None

    # חילוץ עמודות ה-Close של שתי המניות
    try:
        if isinstance(df.columns, pd.MultiIndex):
            close_df = df['Close']
        else:
            close_df = df

        h1 = close_df[ticker1].dropna()
        h2 = close_df[ticker2].dropna()
    except KeyError as e:
        print(f"❌ Could not find ticker column in response: {e}")
        return None, None, None

    if h1.empty or h2.empty:
        return None, None, None

    # מציאת תאריך התחלה משותף (ה-IPO המאוחר מבין השניים)
    start_date = max(h1.index[0], h2.index[0])

    # חיתוך הנתונים שיתחילו מאותו יום
    h1_aligned = h1[h1.index >= start_date]
    h2_aligned = h2[h2.index >= start_date]

    # סנכרון אינדקסים
    common_index = h1_aligned.index.intersection(h2_aligned.index)
    h1_final = h1_aligned.loc[common_index]
    h2_final = h2_aligned.loc[common_index]

    # נרמול ל-100$ (הפיכה לתשואה)
    v1 = (h1_final / h1_final.iloc[0]) * initial_investment
    v2 = (h2_final / h2_final.iloc[0]) * initial_investment

    start_year = start_date.year

    return v1, v2, start_year


# --- חלק 2: יצירת הגרף המונפש (The Visuals) ---
def make_animated_comparison_chart(v1, v2, ticker1, ticker2, start_year, duration, size=(1080, 1920)):
    n_original = len(v1)

    # 🌊 עיבוי דאטה מסיבי להחלקה (1000 נקודות לגלישה מושלמת)
    n_dense = 1000
    x_orig = np.arange(n_original)
    x_dense = np.linspace(0, n_original - 1, n_dense)

    # אינטרפולציה לשתי המניות
    interp_1 = PchipInterpolator(x_orig, v1.values)
    interp_2 = PchipInterpolator(x_orig, v2.values)

    y1_dense = interp_1(x_dense)
    y2_dense = interp_2(x_dense)

    # מציאת גבולות גמישים לציר Y (לוגריתמי לרוב מתאים להשוואות ארוכות)
    y_max = max(max(y1_dense), max(y2_dense))
    y_min = 90  # מתחילים קצת מתחת ל-100$

    fig, ax = plt.subplots(figsize=(size[0] / 100, size[1] / 100), dpi=100)
    canvas = FigureCanvasAgg(fig)

    def render_rgba_frame(t):
        ax.clear()

        # הגדרות רקע ורשת
        fig.patch.set_facecolor(BG_COLOR)
        ax.set_facecolor(BG_COLOR)
        ax.grid(True, color=GRID_COLOR, linestyle='--', linewidth=1, alpha=0.5)

        # חישוב האינדקס המעובה לפי הזמן
        idx = int((t / duration) * (n_dense - 1))
        idx = max(1, min(idx, n_dense - 1))

        # חיתוך הדאטה המעובה עד הפריים הנוכחי
        sub_x = x_dense[:idx + 1]
        sub_y1 = y1_dense[:idx + 1]
        sub_y2 = y2_dense[:idx + 1]

        # --- ציור הקווים הגולשים ---
        # מניה 1
        ax.plot(sub_x, sub_y1, color=COLOR_1, linewidth=6, label=ticker1)
        ax.fill_between(sub_x, sub_y1, y_min, color=COLOR_1, alpha=0.1)
        # מניה 2
        ax.plot(sub_x, sub_y2, color=COLOR_2, linewidth=6, label=ticker2)
        ax.fill_between(sub_x, sub_y2, y_min, color=COLOR_2, alpha=0.1)

        # נקודות קצה וזוהר
        ax.plot(sub_x[-1], sub_y1[-1], marker='o', markersize=12, color=COLOR_1)
        ax.plot(sub_x[-1], sub_y2[-1], marker='o', markersize=12, color=COLOR_2)

        # --- תוויות מחיר דינמיות (כמה שווה ה-100$ עכשיו) ---
        v1_curr = sub_y1[-1]
        v2_curr = sub_y2[-1]

        # הגדרת ציר Y כלוגריתמי אם יש פערים עצומים (אופציונלי, נתחיל בלי)
        # ax.set_yscale('log')

        # תווית למניה 1
        ax.text(sub_x[-1], v1_curr + (y_max * 0.02), f"{ticker1}\n${v1_curr:,.0f}",
                color=COLOR_1, fontsize=26, fontweight='bold', ha='center', va='bottom',
                bbox=dict(boxstyle="round,pad=0.3", facecolor=BG_COLOR, edgecolor=COLOR_1, alpha=0.8))

        # תווית למניה 2
        ax.text(sub_x[-1], v2_curr + (y_max * 0.02), f"{ticker2}\n${v2_curr:,.0f}",
                color=COLOR_2, fontsize=26, fontweight='bold', ha='center', va='bottom',
                bbox=dict(boxstyle="round,pad=0.3", facecolor=BG_COLOR, edgecolor=COLOR_2, alpha=0.8))

        # הגדרות צירים
        ax.set_xlim(- (n_dense * 0.05), n_dense + (n_dense * 0.1))
        # מרווח נשימה למעלה בשביל התוויות
        ax.set_ylim(y_min, y_max * 1.2)

        ax.tick_params(axis='both', colors='white', labelsize=20)
        # להעלים את המספרים על ציר X (הם מייצגים אינדקס מעובה, לא שנה)
        ax.set_xticks([])

        for spine in ax.spines.values(): spine.set_visible(False)

        # הוספת כותרת משנה בפנים
        ax.text(0.5, 0.93, f"Performance since {start_year}", transform=ax.transAxes,
                color='white', fontsize=28, ha='center', alpha=0.6)

        canvas.draw()
        return np.asarray(canvas.buffer_rgba())[:, :, :3]  # הפיכה ל-RGB עבור MoviePy

    # יצירת קליפ הוידאו מהפריימים של Matplotlib
    chart_clip = VideoClip(render_rgba_frame, duration=duration)
    plt.close(fig)
    return chart_clip


# --- חלק 3: הרכבת הוידאו הסופי (The Production) ---
def create_comparison_fomo_video(ticker1, ticker2, music_path, output_filename="fomo_comparison.mp4"):
    duration = 30  # סרטון קצר ומהיר
    investment = 100

    # 1. השגת הנתונים
    v1, v2, start_year = get_comparison_data(ticker1, ticker2, investment)
    if v1 is None: return

    # 2. יצירת קליפ הגרף המונפש
    chart_clip = make_animated_comparison_chart(v1, v2, ticker1, ticker2, start_year, duration)

    # 3. יצירת כותרת טקסט עליונה (TextClip)
    # הערה: דורש ש-ImageMagick יהיה מותקן ומקונפג עבור MoviePy
    header_text = f"IF YOU INVESTED ${investment}\nIN {ticker1} vs {ticker2} IN {start_year}..."
    header_clip = TextClip(header_text, fontsize=70, color='white', font=FONT_NAME,
                           method='caption', size=(900, None), align='center')
    header_clip = header_clip.set_position(('center', 100)).set_duration(duration)

    # 4. יצירת וידאו רקע שחור (או וידאו מטושטש)
    background = VideoFileClip("trading_floor_loop.mp4").loop(duration=duration)
    background = background.resize(height=1920).crop(x_center=background.w / 2, width=1080)
    background = background.colorx(0.1)  # החשכה כמעט מוחלטת

    # 5. הרכבת הקליפים
    final_video = CompositeVideoClip([
        background,
        chart_clip.set_position("center"),
        header_clip
    ], size=(1080, 1920))

    # 6. הוספת מוזיקה
    if os.path.exists(music_path):
        audio = AudioFileClip(music_path).set_duration(duration)
        # הוספת Fade Out עדין בסוף
        audio = audio.audio_fadeout(2)
        final_video = final_video.set_audio(audio)

    # 7. רינדור
    print(f"🎬 Rendering final video: {output_filename}...")
    final_video.write_videofile(output_filename, fps=24, codec='libx264', audio_codec='aac')
    print("✅ Done!")


def run_generator(test_mode):
    create_comparison_fomo_video("NVDA", "TSLA", "comparison_music.mp3", "nvda_vs_tsla.mp4")

# --- הרצה לדוגמה ---
if __name__ == "__main__":

    create_comparison_fomo_video("NVDA", "TSLA", "comparison_music.mp3", "nvda_vs_tsla.mp4")
