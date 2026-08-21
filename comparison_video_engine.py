import os
import time
import tempfile
import random
import json
import urllib.request
import numpy as np
from io import BytesIO
from google import genai
from google.genai import types
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from scipy.interpolate import PchipInterpolator
import requests
from PIL import Image, ImageDraw, ImageEnhance
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.LANCZOS
from dotenv import load_dotenv
import yfinance as yf

# Imports מעודכנים של MoviePy
import moviepy.audio.fx.all as afx
import moviepy.video.fx.all as vfx  # חובה לאפקטים של ווידאו
from moviepy.editor import VideoClip, AudioFileClip, concatenate_videoclips, VideoFileClip, CompositeVideoClip

from uploader import upload_video

SECTORS = {
    "Semiconductors & Chips": ["NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM", "MU", "AMAT", "ASML"],
    "Big Tech & Cloud": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "ORCL", "CRM", "ADBE"],
    "Electric Vehicles & Auto": ["TSLA", "RIVN", "LCID", "F", "GM", "TM"],
    "Fintech & Banking": ["V", "MA", "PYPL", "SQ", "JPM", "BAC", "GS", "MS", "COIN"],
    "Streaming & Media": ["NFLX", "DIS", "WBD", "SPOT", "ROKU"],
    "Retail & E-commerce": ["WMT", "TGT", "COST", "BABA", "SHOP", "MELI"],
    "Pharma & Healthcare": ["LLY", "NVO", "PFE", "JNJ", "UNH", "ABBV"],
    "Energy & Defense": ["XOM", "CVX", "LMT", "RTX", "NOC"]
}

# --- פלטות צבעים כהות ויוקרתיות לרקע ---
BACKGROUND_PALETTES = [
    # 1. Slate Blue / Dark Navy (הקלאסי)
    {
        "bg1": (24, 32, 47, 255),
        "bg2": (15, 19, 28, 255),
        "line": (42, 52, 71, 255),
        "card_bg": "#141A26",
        "grid": "#2A3447",
    },
    # 2. Midnight Purple (סגול כהה עמוק)
    {
        "bg1": (32, 22, 48, 255),
        "bg2": (18, 12, 28, 255),
        "line": (60, 42, 85, 255),
        "card_bg": "#1B1226",
        "grid": "#3B2854",
    },
    # 3. Dark Emerald / Forest (ירוק אמרלד כהה - מומלץ למניות)
    {
        "bg1": (18, 38, 32, 255),
        "bg2": (10, 22, 18, 255),
        "line": (35, 70, 58, 255),
        "card_bg": "#0F211C",
        "grid": "#22453A",
    },
    # 4. Deep Crimson / Wine (בורדו/יין כהה)
    {
        "bg1": (42, 20, 28, 255),
        "bg2": (25, 11, 16, 255),
        "line": (75, 35, 50, 255),
        "card_bg": "#210F16",
        "grid": "#4A2231",
    },
    # 5. Obsidian Charcoal (אפור פחם / ניטרלי)
    {
        "bg1": (35, 35, 38, 255),
        "bg2": (18, 18, 20, 255),
        "line": (60, 60, 65, 255),
        "card_bg": "#1C1C1E",
        "grid": "#3A3A3C",
    },
    # 6. Deep Indigo / Cyber Dark (אינדיגו/סייבר)
    {
        "bg1": (20, 28, 55, 255),
        "bg2": (12, 16, 32, 255),
        "line": (45, 60, 105, 255),
        "card_bg": "#11182E",
        "grid": "#2C3A66",
    },
]

DYNAMIC_FONTS = ["DejaVu Sans", "Arial", "Impact", "Trebuchet MS", "Verdana"]

load_dotenv()

# --- הגדרות עיצוב ומסלולים ---
BG_COLOR = "#131722"
GRID_COLOR = "#2A3447"
# מסלולים לתיקיות נכסים
LOGOS_DIR = "assets/logos"
TRADING_FLOOR_DIR = "assets/trading_floor_videos"

# הגדרת פונט תומך Unicode באופן גלובלי
plt.rcParams['font.family'] = ['Segoe UI Emoji', 'DejaVu Sans']

try:
    cache_dir = os.path.join(tempfile.gettempdir(), "yf_cache")
    os.makedirs(cache_dir, exist_ok=True)
    yf.set_tz_cache_location(cache_dir)
except Exception:
    pass


def get_ticker_logo(ticker):
    """מורידה לוגו שקוף אוטומטית מ-CDN עם אימות תקינות הקובץ."""
    logos_dir = "assets/logos"
    os.makedirs(logos_dir, exist_ok=True)
    logo_path = os.path.join(logos_dir, f"{ticker}.png")

    # בדיקה אם הקובץ קיים ותקין
    if os.path.exists(logo_path):
        try:
            with Image.open(logo_path) as img:
                img.verify()
            return logo_path
        except Exception:
            # הקובץ קיים אך פגום - נמחק אותו כדי להוריד מחדש
            try:
                os.remove(logo_path)
            except Exception:
                pass

    # ניסיונות משיכה מ-APIs ציבוריים
    urls = [
        f"https://assets.parqet.com/logos/symbol/{ticker}",
        f"https://financialmodelingprep.com/image-stock/{ticker}.png",
        f"https://logo.clearbit.com/{ticker.lower()}.com",
    ]

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for url in urls:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
                if len(data) < 500:
                    continue

                # אימות שהנתונים שהתקבלו הם תמונה תקינה לפני שמירה
                img = Image.open(BytesIO(data))
                img.verify()

                # המרה ל-RGBA ושמירה כ-PNG תקין
                img = Image.open(BytesIO(data)).convert("RGBA")
                img.save(logo_path, "PNG")
                return logo_path
        except Exception:
            continue

    return None


def prepare_image_background_and_thumbnail(
    ticker1, ticker2, palette=None, width=1080, height=1920
):
    """
    יוצרת Thumbnail מוארת ותמונת רקע מושחרת לפי פלטת צבעים דינמית.
    """
    if palette is None:
        palette = random.choice(BACKGROUND_PALETTES)

    bg1 = palette["bg1"]
    bg2 = palette["bg2"]
    line_color = palette["line"]

    # יצירת בסיס הרקע
    bg = Image.new("RGBA", (width, height), bg2)
    draw = ImageDraw.Draw(bg)

    comp_type = random.choice(["diagonal", "horizontal", "vertical"])

    # ציור הגרפיקה לפי הפלטה הדינמית
    if comp_type == "diagonal":
        poly_tl = [(0, 0), (width, 0), (0, height)]
        poly_br = [(width, 0), (width, height), (0, height)]
        draw.polygon(poly_tl, fill=bg1)
        draw.polygon(poly_br, fill=bg2)
        draw.line([(width, 0), (0, height)], fill=line_color, width=12)
    elif comp_type == "horizontal":
        draw.rectangle([(0, 0), (width, height // 2)], fill=bg1)
        draw.rectangle([(0, height // 2), (width, height)], fill=bg2)
        draw.line(
            [(0, height // 2), (width, height // 2)], fill=line_color, width=12
        )
    else:  # vertical
        draw.rectangle([(0, 0), (width // 2, height)], fill=bg1)
        draw.rectangle([(width // 2, 0), (width, height)], fill=bg2)
        draw.line(
            [(width // 2, 0), (width // 2, height)], fill=line_color, width=12
        )

    # מיקום הלוגואים
    logo1_path = get_ticker_logo(ticker1)
    logo2_path = get_ticker_logo(ticker2)
    logo_size = 380

    def paste_logo(bg_img, logo_path, center_pos):
        if logo_path and os.path.exists(logo_path):
            try:
                img = Image.open(logo_path).convert("RGBA")
                img.thumbnail((logo_size, logo_size), Image.Resampling.LANCZOS)
                pos = (
                    int(center_pos[0] - img.width / 2),
                    int(center_pos[1] - img.height / 2),
                )
                bg_img.paste(img, pos, img)
            except Exception as e:
                print(f"⚠️ Failed to paste logo {logo_path}: {e}")

    if comp_type == "diagonal":
        paste_logo(bg, logo2_path, (width * 0.25, height * 0.30))
        paste_logo(bg, logo1_path, (width * 0.75, height * 0.70))
    elif comp_type == "horizontal":
        paste_logo(bg, logo2_path, (width * 0.5, height * 0.25))
        paste_logo(bg, logo1_path, (width * 0.5, height * 0.75))
    else:  # vertical
        paste_logo(bg, logo2_path, (width * 0.25, height * 0.5))
        paste_logo(bg, logo1_path, (width * 0.75, height * 0.5))

    temp_dir = tempfile.gettempdir()
    unique_id = f"{ticker1}_vs_{ticker2}_{int(time.time())}"
    thumb_path = os.path.join(temp_dir, f"thumb_{unique_id}.png")
    dark_bg_path = os.path.join(temp_dir, f"dark_bg_{unique_id}.png")

    # 1. שמירת Thumbnail (בהיר)
    bg.convert("RGB").save(thumb_path, quality=95)

    # 2. שמירת רקע מושחר (35% בהירות)
    enhancer = ImageEnhance.Brightness(bg)
    dark_bg = enhancer.enhance(0.35)
    dark_bg.convert("RGB").save(dark_bg_path)

    return thumb_path, dark_bg_path


def fetch_yahoo_chart_direct(ticker, period="max", interval="1wk"):
    """מושך נתוני מניה ישירות מ-API ה-Chart של Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={period}&interval={interval}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }

    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                result = data["chart"]["result"][0]
                timestamps = result["timestamp"]
                closes = result["indicators"]["quote"][0]["close"]

                df = pd.DataFrame(
                    {"Close": closes},
                    index=pd.to_datetime(timestamps, unit="s", utc=True),
                )
                df.index = df.index.tz_localize(None)
                df = df.dropna()

                if not df.empty:
                    return df["Close"]
            elif response.status_code == 429:
                time.sleep(3)
        except Exception:
            time.sleep(2)

    return pd.Series(dtype=float)


def prepare_video_background(target_duration, width=1080, height=1920):
    """
    בוחרת ווידאו אקראי מהתיקייה, הופכת אותו ללופ כדי להתאים לזמן היעד,
    ומשחירה אותו.
    """
    if not os.path.exists(TRADING_FLOOR_DIR):
        print(f"⚠️ Folder {TRADING_FLOOR_DIR} not found.")
        return None

    video_files = [f for f in os.listdir(TRADING_FLOOR_DIR) if f.endswith(".mp4")]
    if not video_files:
        print(f"⚠️ No trading floor videos found in {TRADING_FLOOR_DIR}, using image fallback.")
        return None

    # בחירת ווידאו אקראי (1, 2, או 3)
    selected_video = random.choice(video_files)
    video_path = os.path.join(TRADING_FLOOR_DIR, selected_video)

    try:
        # טעינת הווידאו
        bg_clip = VideoFileClip(video_path)

        # התאמת גודל: קודם resize לגובה, ואז crop למרכז כדי לקבל 1080x1920
        bg_clip = bg_clip.resize(height=height) # גובה 1920
        current_w = bg_clip.w
        left_crop = (current_w - width) / 2
        bg_clip = bg_clip.crop(x1=left_crop, width=width, height=height)

        # יצירת לופ במידה והווידאו קצר מדי
        if bg_clip.duration < target_duration:
            bg_clip = bg_clip.fx(afx.audio_loop, duration=target_duration)

        # חיתוך מדויק לזמן היעד
        bg_clip = bg_clip.subclip(0, target_duration)

        # השחרה / עמעום (vfx.colorx - מכפיל את הצבעים ב-0.25 להכהיה משמעותית)
        bg_clip = bg_clip.fx(vfx.colorx, 0.25)

        # הסרת שמע מקורי מהרקע
        bg_clip = bg_clip.set_audio(None)

        return bg_clip
    except Exception as e:
        print(f"⚠️ Error preparing video background {video_path}: {e}")
        return None


def get_comparison_data(ticker1, ticker2, initial_investment=100):
    print(f"📥 Fetching historical data for {ticker1} and {ticker2}...", flush=True)

    h1 = fetch_yahoo_chart_direct(ticker1, period="max", interval="1wk")
    time.sleep(1)
    h2 = fetch_yahoo_chart_direct(ticker2, period="max", interval="1wk")

    if h1.empty or h2.empty:
        return None, None, None

    start_date = max(h1.index[0], h2.index[0])
    h1_aligned = h1[h1.index >= start_date]
    h2_aligned = h2[h2.index >= start_date]

    common_index = h1_aligned.index.intersection(h2_aligned.index)
    h1_final = h1_aligned.loc[common_index]
    h2_final = h2_aligned.loc[common_index]

    if h1_final.empty or h2_final.empty:
        return None, None, None

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
    palette,  # <-- מקבל את פלטת הצבעים
    dark_bg_path=None,
    bg_clip=None,
    show_fill=True,
    size=(1080, 1920),
):
    size = (int(size[0]), int(size[1]))

    n_original = len(v1)
    n_dense = 1000
    x_orig = np.arange(n_original)
    x_dense = np.linspace(0, n_original - 1, n_dense)

    interp_1 = PchipInterpolator(x_orig, v1.values)
    interp_2 = PchipInterpolator(x_orig, v2.values)

    y1_dense = interp_1(x_dense)
    y2_dense = interp_2(x_dense)

    bg_array = None
    if dark_bg_path and os.path.exists(dark_bg_path):
        bg_pil = Image.open(dark_bg_path).convert("RGB").resize(size)
        bg_array = np.array(bg_pil, dtype=np.float32)

    fig, ax = plt.subplots(figsize=(size[0] / 100, size[1] / 100), dpi=100)
    canvas = FigureCanvasAgg(fig)

    # כותרת עליונה משתמשת ב-card_bg ו-grid מתוך הפלטה
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
            facecolor=palette["card_bg"],
            edgecolor=palette["grid"],
            alpha=0.9,
        ),
    )

    date_text_obj = fig.text(
        0.5,
        0.82,
        "",
        color="white",
        fontsize=24,
        fontweight="bold",
        ha="center",
        va="top",
    )

    try:
        dates = v1.index.strftime("%b %Y")
    except AttributeError:
        dates = [str(start_year)] * n_original

    def render_rgba_frame(t):
        ax.clear()

        fig.patch.set_alpha(0.0)
        ax.set_facecolor("none")

        # גריד דינמי לפי הפלטה
        ax.grid(
            True,
            color=palette["grid"],
            linestyle="--",
            linewidth=1,
            alpha=0.5,
        )

        progress = min(t / duration, 1.0)
        idx = max(1, int(progress * (n_dense - 1)))

        idx_orig = int(progress * (n_original - 1))
        idx_orig = min(max(0, idx_orig), n_original - 1)
        date_text_obj.set_text(dates[idx_orig])

        sub_x = x_dense[: idx + 1]
        sub_y1 = y1_dense[: idx + 1]
        sub_y2 = y2_dense[: idx + 1]

        ax.plot(sub_x, sub_y1, color=color1, linewidth=6, label=ticker1)
        ax.plot(sub_x, sub_y2, color=color2, linewidth=6, label=ticker2)

        if show_fill:
            ax.fill_between(
                sub_x, sub_y1, min(sub_y1), color=color1, alpha=0.15
            )
            ax.fill_between(
                sub_x, sub_y2, min(sub_y2), color=color2, alpha=0.15
            )

        ax.plot(sub_x[-1], sub_y1[-1], marker="o", markersize=12, color=color1)
        ax.plot(sub_x[-1], sub_y2[-1], marker="o", markersize=12, color=color2)

        v1_curr = sub_y1[-1]
        v2_curr = sub_y2[-1]

        crown_icon = "\U0001F451"

        if v1_curr >= v2_curr:
            label1_str = f"{ticker1} {crown_icon}\n${v1_curr:,.1f}"
            label2_str = f"{ticker2}\n${v2_curr:,.1f}"
        else:
            label1_str = f"{ticker1}\n${v1_curr:,.1f}"
            label2_str = f"{ticker2} {crown_icon}\n${v2_curr:,.1f}"

        current_y_max = max(np.max(sub_y1), np.max(sub_y2))
        current_y_min = min(np.min(sub_y1), np.min(sub_y2))
        ax.set_ylim(current_y_min * 0.85, current_y_max * 1.35)

        x_max = max(10, sub_x[-1])
        ax.set_xlim(-(x_max * 0.05), x_max + (x_max * 0.15))

        # תיבות טקסט משתמשות ב-card_bg מתוך הפלטה
        ax.text(
            sub_x[-1],
            v1_curr + (current_y_max * 0.03),
            label1_str,
            color=color1,
            fontsize=24,
            fontweight="bold",
            ha="center",
            va="bottom",
            bbox=dict(
                boxstyle="round,pad=0.3",
                facecolor=palette["card_bg"],
                edgecolor=color1,
                alpha=0.85,
            ),
        )

        ax.text(
            sub_x[-1],
            v2_curr + (current_y_max * 0.03),
            label2_str,
            color=color2,
            fontsize=24,
            fontweight="bold",
            ha="center",
            va="bottom",
            bbox=dict(
                boxstyle="round,pad=0.3",
                facecolor=palette["card_bg"],
                edgecolor=color2,
                alpha=0.85,
            ),
        )

        ax.tick_params(axis="both", colors="white", labelsize=18)
        ax.set_xticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

        canvas.draw()

        chart_rgba = np.asarray(canvas.buffer_rgba())
        alpha = (chart_rgba[:, :, 3:4].astype(np.float32)) / 255.0
        chart_rgb = chart_rgba[:, :, :3].astype(np.float32)

        if bg_clip is not None:
            current_bg = bg_clip.get_frame(t).astype(np.float32)
        elif bg_array is not None:
            current_bg = bg_array
        else:
            # פולבק לצבע הרקע הראשון מהפלטה
            current_bg = np.full(
                (size[1], size[0], 3), palette["bg2"][:3], dtype=np.float32
            )

        blended = (chart_rgb * alpha + current_bg * (1.0 - alpha)).astype(
            np.uint8
        )
        return blended

    chart_clip = VideoClip(render_rgba_frame, duration=duration)
    plt.close(fig)
    return chart_clip

def create_comparison_fomo_video(
    ticker1,
    ticker2,
    sector_name,
    music_path,
    investment,
    output_filename="fomo_comparison.mp4",
):
    duration = random.randint(25, 35)
    fps = 15
    width, height = 1080, 1920

    v1, v2, start_year = get_comparison_data(ticker1, ticker2, investment)
    if v1 is None or v2 is None or len(v1) < 2 or len(v2) < 2:
        print(
            f"❌ Insufficient price data for {ticker1} vs {ticker2}. Skipping...",
            flush=True,
        )
        return None, None

    # 🟢 1. הגרלת פלטת צבעים אחת לכל הרינדור (Thumbnail + Video)
    selected_palette = random.choice(BACKGROUND_PALETTES)

    print(
        f"🎬 Generating {duration}s Video For {ticker1} vs {ticker2} ({sector_name})",
        flush=True,
    )

    # 🟢 2. הכנת Thumbnail והרקע הסטטי עם הפלטה שנבחרה
    thumb_path, dark_image_bg_path = prepare_image_background_and_thumbnail(
        ticker1, ticker2, palette=selected_palette, width=width, height=height
    )

    palette = [
        "#00E676",
        "#FF1744",
        "#29B6F6",
        "#FFA000",
        "#E040FB",
        "#1DE9B6",
        "#FFEA00",
    ]
    c1, c2 = random.sample(palette, 2)

    ai_data = generate_fomo_metadata_and_header_with_ai(
        ticker1, ticker2, sector_name, investment, start_year
    )

    show_fill = random.random() > 0.30

    background_type = random.choice(["video", "logos"])

    bg_clip = None
    dark_bg_for_chart = None

    if background_type == "video":
        print("🟢 Using darkened trading floor video background.", flush=True)
        bg_clip = prepare_video_background(duration, width, height)
        if bg_clip is None:
            background_type = "logos"

    if background_type == "logos":
        print(
            "🟢 Using static darkened logo composition background.", flush=True
        )
        dark_bg_for_chart = dark_image_bg_path

    # 🟢 3. יצירת הגרף תוך שימוש בפלטה שנבחרה
    final_video = make_animated_comparison_chart(
        v1,
        v2,
        ticker1,
        ticker2,
        start_year,
        investment,
        duration,
        c1,
        c2,
        ai_data["video_header"],
        palette=selected_palette,  # <-- העברת הפלטה
        dark_bg_path=dark_bg_for_chart,
        bg_clip=bg_clip,
        show_fill=show_fill,
        size=(width, height),
    )

    freeze_frame = final_video.to_ImageClip(t=duration - 0.1).set_duration(1.0)
    final_video = concatenate_videoclips([final_video, freeze_frame])

    total_duration = duration + 1.0

    zoom_type = random.choice(["in", "out"])
    if zoom_type == "in":
        final_video = final_video.fx(vfx.resize, lambda t: 1 + 0.002 * t)
    else:
        final_video = final_video.fx(vfx.resize, lambda t: 1.08 - 0.002 * t)

    final_video = final_video.crop(
        x_center=final_video.w / 2,
        y_center=final_video.h / 2,
        width=width,
        height=height,
    )

    if music_path and os.path.exists(music_path):
        bg_music = AudioFileClip(music_path)
        if bg_music.duration < total_duration:
            bg_music = bg_music.fx(afx.audio_loop, duration=total_duration)

        bg_music = (
            bg_music.subclip(0, total_duration)
            .fx(afx.volumex, 0.15)
            .fx(afx.audio_fadeout, 2)
        )
        final_video = final_video.set_audio(bg_music)

    print(f"🎬 Rendering final video: {output_filename}...", flush=True)

    final_video.write_videofile(
        output_filename,
        fps=fps,
        codec="libx264",
        audio_codec="aac",
        audio_fps=44100,
        temp_audiofile="temp-audio.m4a",
        remove_temp=True,
        threads=os.cpu_count() or 4,
        preset="ultrafast",
        write_logfile=False,
    )

    final_video.close()
    if bg_clip is not None:
        bg_clip.close()

    print("✅ Done!", flush=True)
    return ai_data, thumb_path


def generate_fomo_metadata_and_header_with_ai(
        ticker1, ticker2, sector_name, investment, start_year
):
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

    # 1. הגרלת זווית/סגנון כתיבה שונה בכל הרצה למניעת חזרתיות
    CREATIVE_ANGLES = [
        f"REGRET & FOMO: Focus on the pain of choosing the wrong stock in {start_year} (e.g. 'If only you picked...')",
        f"BRUTAL WAR: Frame it as an aggressive battle between {sector_name} giants (e.g. 'DESTROYED', 'CRUSHED')",
        f"WEALTH / ROI: Focus purely on the massive stack of money made from ${investment}",
        f"MYSTERY / SHOCK: Frame it as a surprising twist that nobody expected",
        f"INVESTOR COMPARISON: Ask a direct, provocative question to investors in this sector",
    ]
    chosen_angle = random.choice(CREATIVE_ANGLES)

    # 2. הגרלת פלטת אימוג'ים מועדפת כדי שלא יחזור על 🚀 בכל כותרת
    EMOJI_SETS = [
        "⚔️, 💥, 🥊, 💣",
        "👑, 🏆, 🥇, 💰",
        "🤯, 🚨, 🔥, 😱",
        "📊, 📉, 📈, 💵",
    ]
    chosen_emojis = random.choice(EMOJI_SETS)

    prompt = f"""
        You are a top-tier viral financial content creator for TikTok, Shorts, and Reels.
        Create the ON-SCREEN HEADER and YouTube metadata for an animated stock race video.

        Video Details:
        - Stocks: {ticker1} vs {ticker2}
        - Sector: {sector_name}
        - Investment: ${investment} starting in {start_year}

        CREATIVE ANGLE FOR THIS VIDEO:
        {chosen_angle}

        STRICT RULES FOR DIVERSITY:
        1. "video_header": 3 to 5 words MAX in ALL CAPS for the overlay on top of the video. Make it punchy!
        2. "youtube_title": NO CLICHÉS! DO NOT use boring formats like "{ticker1} vs {ticker2}: Who Won?". 
           - Use diverse hook styles (Questions, Shocking Statements, Regret Hooks).
           - Primary emojis to draw inspiration from for this video: {chosen_emojis}
        3. "description": Punchy summary ending with an engaging question to force viewers to comment.
        4. "tags": 5-7 comma-separated tags.

        STRICT OUTPUT FORMAT:
        Return ONLY a valid JSON object with the following 4 fields:
        {{
          "video_header": "SHORT ON-SCREEN HEADER IN ALL CAPS",
          "youtube_title": "Highly creative and unique title with emojis",
          "description": "Engaging description ending with a comment question",
          "tags": "tag1,tag2,tag3,tag4,tag5"
        }}
        """

    # 3. שימוש ב-temperature=1.0 כדי להבטיח יצירתיות ואקראיות גבוהה
    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=1.0,  # <-- מעלה את רמת הגיוון והאקראיות
        ),
    )

    return json.loads(response.text)


def run_generator(test_mode=False):
    MUSIC_PATH = f"assets/suspense_music/{random.choice([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15])}.mp3"
    if not os.path.exists(MUSIC_PATH):
        MUSIC_PATH = ""

    # 1. בחירת סקטור אקראי
    sector_name, tickers = random.choice(list(SECTORS.items()))

    # 2. בחירת שני טיקרים מתוך אותו סקטור
    ticker1, ticker2 = random.sample(tickers, 2)

    output_filename = f"{ticker1}_vs_{ticker2}.mp4"
    investment = random.choice([100, 200, 500, 1000])
    upload_data, thumb_path = None, None
    attempts = 0
    while upload_data is None and thumb_path is None:
        attempts += 1
        upload_data, thumb_path = create_comparison_fomo_video(
            ticker1, ticker2, sector_name, MUSIC_PATH, investment, output_filename
        )
        if attempts > 10:
            break

    if test_mode:
        return output_filename
    else:
        if upload_data:
            upload_video(
                output_filename,
                upload_data["youtube_title"],
                upload_data["description"],
                upload_data["tags"],
                thumbnail_path=thumb_path,
            )
            return output_filename

if __name__ == "__main__":
    for i in range(5):
        run_generator(test_mode=True)