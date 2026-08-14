import os
from datetime import date
import json
import asyncio
import random
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
import matplotlib
matplotlib.use('Agg')  # חובה להופיע לפני היבוא של pyplot!
import matplotlib.pyplot as plt
import yfinance as yf
import edge_tts
import whisper
import shutil
from dotenv import load_dotenv
import streamlit as st
import PIL.Image
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types

from moviepy.editor import (
    AudioFileClip, ImageClip, VideoClip, CompositeVideoClip, VideoFileClip
)
from uploader import upload_video
import imageio_ffmpeg

# -----------------------------------------------------------------------------
# 0. התאמת FFmpeg לחלונות (בלינוקס/Streamlit יילקח ה-FFmpeg המערכתי)
# -----------------------------------------------------------------------------
if os.name == 'nt':  # Windows בלבד
    ffmpeg_src = imageio_ffmpeg.get_ffmpeg_exe()
    ffmpeg_dst = os.path.join(os.getcwd(), "ffmpeg.exe")
    if not os.path.exists(ffmpeg_dst):
        shutil.copy(ffmpeg_src, ffmpeg_dst)
        print("✅ Created local ffmpeg.exe for Whisper!")

load_dotenv()
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.Resampling.LANCZOS

TICKERS_TO_CHECK = [
    # 🚀 AI, שבבים וטכנולוגיה ענקית (Mega-Tech & AI)
    "NVDA", "TSLA", "AAPL", "AMD", "PLTR", "AMZN", "MSFT", "GOOGL",
    "META", "NFLX", "AVGO", "TSM", "SMCI", "INTC", "ORCL", "CRM", "QCOM", "MU",

    # 🪙 קריפטו, פינטק ומניות תנודתיות (Crypto & FinTech)
    "MSTR", "COIN", "HOOD", "SOFI", "PYPL",

    # ⚡ צמיחה, רכבים חשמליים וטרנדים (Growth & Retail Favorites)
    "RIVN", "NIO", "BABA", "UBER", "RBLX", "SHOP", "LLY"
]
USED_STOCKS_FILE = "used_stocks.json"

# -----------------------------------------------------------------------------
# 1. איתור מניה זזה ברשת
# -----------------------------------------------------------------------------
def get_used_stocks_today():
    """טוען את רשימת המניות שכבר נעשה בהן שימוש היום. מאפס אם התחלף יום."""
    today_str = str(date.today())
    if os.path.exists(USED_STOCKS_FILE):
        try:
            with open(USED_STOCKS_FILE, "r") as f:
                data = json.load(f)
                if data.get("date") == today_str:
                    return set(data.get("used", []))
        except Exception:
            pass
    return set()


def mark_stock_as_used(ticker_symbol):
    """רושם את המניה כמשומשת עבור היום הנוכחי"""
    today_str = str(date.today())
    used_stocks = get_used_stocks_today()
    used_stocks.add(ticker_symbol)

    with open(USED_STOCKS_FILE, "w") as f:
        json.dump({"date": today_str, "used": list(used_stocks)}, f)


def extract_news_context(news_data, ticker_symbol="", max_articles=3):
    """
    מחלצת כותרות ותקצירים מתוך מבנה החדשות החדש של yfinance.
    """
    if not news_data or not isinstance(news_data, list):
        return "No recent breaking news available."

    formatted_articles = []
    count = 0

    for item in news_data:
        if count >= max_articles:
            break

        # המידע של הכתבה עטוף בתוך 'content'
        content = item.get('content', {})
        if not content:
            continue

        title = content.get('title', '').strip()
        summary = content.get('summary', '').strip()
        provider = content.get('provider', {}).get('displayName', 'Market News')

        if not title:
            continue

        # אם העברנו סימול מניה (כמו NVDA), נעדיף כתבות שמוזכרות בהן המניה
        # (אופציונלי - אם רוצים לסנן כתבות לא קשורות)
        article_text = f"• [{provider}] {title}"
        if summary:
            article_text += f"\n  Context: {summary}"

        formatted_articles.append(article_text)
        count += 1

    if not formatted_articles:
        return "No breaking news found for this ticker today."

    return "\n\n".join(formatted_articles)

def get_top_moving_stock(test=False):
    used_today = get_used_stocks_today()
    print(f"📋 Stocks already used today ({date.today()}): {list(used_today) if used_today else 'None'}")

    best_ticker = None
    max_change = -1
    top_data = None

    print("🔍 Searching for today's top-moving unused stock...")
    for ticker_symbol in TICKERS_TO_CHECK:
        if ticker_symbol in used_today:
            print(f"⏭️ Skipping {ticker_symbol} (Already used today)")
            continue

        try:
            ticker = yf.Ticker(ticker_symbol)
            hist = ticker.history(period="5d", interval="15m")
            if hist.empty:
                continue

            prev_close = hist['Close'].iloc[-10]
            curr_price = hist['Close'].iloc[-1]
            pct_change = abs((curr_price - prev_close) / prev_close) * 100

            if pct_change > max_change:

                news = extract_news_context(ticker.news)
                max_change = pct_change
                best_ticker = ticker
                raw_pct = ((curr_price - prev_close) / prev_close) * 100
                top_data = {
                    "symbol": ticker_symbol,
                    "current_price": round(curr_price, 2),
                    "change_pct": round(raw_pct, 2),
                    "history": hist['Close'],
                    "news": news
                }
        except Exception as e:
            print(f"Error While Fetching Symbol: {e}")

    if not top_data and used_today:
        print("⚠️ All stocks in TICKERS_TO_CHECK were already used today! Resetting selection...")
        return get_top_moving_stock_fallback()

    if top_data:
        if not test:
            mark_stock_as_used(top_data['symbol'])
        print(f"🎯 Selected: {top_data['symbol']} with {top_data['change_pct']}% change")
    return top_data, ticker


def get_top_moving_stock_fallback():
    if os.path.exists(USED_STOCKS_FILE):
        os.remove(USED_STOCKS_FILE)
    return get_top_moving_stock()


def get_market_metrics(stock):
    """
    שולף שווי שוק של המניה, מחיר S&P 500 ומחיר ביטקוין.
    """
    try:
        mcap = stock.info.get('marketCap', 0)

        if mcap >= 1e12:
            mcap_str = f"${mcap / 1e12:.2f}T"
        elif mcap >= 1e9:
            mcap_str = f"${mcap / 1e9:.2f}B"
        elif mcap >= 1e6:
            mcap_str = f"${mcap / 1e6:.2f}M"
        else:
            mcap_str = "N/A"

        # 2. מדדים וביטקוין
        sp500_price = yf.Ticker("^GSPC").fast_info.last_price
        btc_price = yf.Ticker("BTC-USD").fast_info.last_price

        return {
            "mcap": mcap_str,
            "sp500": f"${sp500_price:,.0f}" if sp500_price else "N/A",
            "btc": f"${btc_price:,.0f}" if btc_price else "N/A"
        }
    except Exception as e:
        print(f"⚠️ Error fetching market metrics: {e}")
        return {"mcap": "N/A", "sp500": "N/A", "btc": "N/A"}

# -----------------------------------------------------------------------------
# 2. יצירת תסריט + כותרות ב-Gemini Flash Lite
# -----------------------------------------------------------------------------
def generate_script_and_titles_with_ai(stock_data):
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
    You are a high-energy financial content creator for TikTok/Shorts/Reels.
    Create a 1 minute video script about this stock movement:
    - Symbol: {stock_data['symbol']}
    - Current Price: ${stock_data['current_price']}
    - Today's Change: {stock_data['change_pct']}%
    - News: {stock_data['news']}

    Requirements:
    1. Strong, scroll-stopping hook in the first second.
    2. Explain the price movement in exciting, clear English.
    3. Avoid Using Filler Words and Gaps, jst alot of engaging data
    3. Call to Action question at the end to generate comments.
    4. Return ONLY valid JSON with 5 specific fields:
    {{
      "youtube_title": "Catchy YouTube Short title with emojis (e.g. NVDA Surges +8.45%! Buy Now? 🚀)",
      "overlay_headline": "2 to 4 WORDS IN ALL CAPS FOR TOP OVERLAY (e.g. NVDA EXPLODES!)",
      "voiceover_text": "The full spoken script for narration",
      "description": "A short, engaging description for the stock video",
      "tags": "5-7 tags separated by commas (e.g. NVDA,Stocks,Investing,AI)"
    }}
    """

    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )

    return json.loads(response.text)

# -----------------------------------------------------------------------------
# 3. קריינות + חילוץ כתוביות בעזרת Whisper
# -----------------------------------------------------------------------------
async def create_tts_async(text, audio_file="voiceover.mp3"):
    voice = "en-GB-RyanNeural"
    communicate = edge_tts.Communicate(text, voice, rate="+15%")
    await communicate.save(audio_file)

def get_exact_captions_with_whisper(audio_file, words_per_caption=2):
    print("🎧 Aligning captions directly from audio stream with Whisper...")
    model = whisper.load_model("tiny.en")
    result = model.transcribe(audio_file, word_timestamps=True)

    word_events = []
    for segment in result.get("segments", []):
        for word_info in segment.get("words", []):
            word_events.append({
                "word": word_info["word"].strip(),
                "start": word_info["start"],
                "end": word_info["end"]
            })

    if not word_events:
        return []

    captions = []
    for i in range(0, len(word_events), words_per_caption):
        group = word_events[i : i + words_per_caption]
        start_t = group[0]["start"]
        end_t = group[-1]["end"]

        if i + words_per_caption < len(word_events):
            next_start = word_events[i + words_per_caption]["start"]
            end_t = min(end_t + 0.05, next_start)

        text = " ".join([w["word"] for w in group])
        captions.append({
            "start": start_t,
            "end": end_t,
            "text": text
        })

    return captions

# -----------------------------------------------------------------------------
# 4. מחולל הגרפיקה
# -----------------------------------------------------------------------------
def load_system_font(size):
    # 1. עדיפות ראשונה: פונט מקומי בתיקיית הפרויקט (תוריד קובץ ttf לתיקייה)
    local_fonts = ["Roboto-Bold.ttf", "Montserrat-Bold.ttf", "arial.ttf"]
    for font_file in local_fonts:
        if os.path.exists(font_file):
            try:
                return ImageFont.truetype(font_file, size)
            except Exception:
                pass

    # 2. עדיפות שנייה: נתיבים של Linux/Ubuntu בשרתי ענן
    linux_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
    ]
    for font_path in linux_fonts:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            continue

    # 3. עדיפות שלישית: שמות פונטים של Windows
    windows_fonts = ["impact.ttf", "ariblk.ttf", "arialbd.ttf", "trebucbd.ttf"]
    for font_name in windows_fonts:
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue

    # 4. Fallback אחרון עם הגדרת גודל מפורשת (נתמך ב-Pillow מעל גרסה 10.1)
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()

def create_overlay_graphics(script_data, stock_data, canvas_size=(1080, 1920)):
    canvas = Image.new('RGBA', canvas_size, (0, 0, 0, 0))

    headline_text = script_data.get("overlay_headline", f"{stock_data['symbol']} MOVES!").upper()
    font_size = 75 if len(headline_text) < 15 else 60
    font = load_system_font(font_size)

    neon_colors = ["#FFD700", "#00FFFF", "#FF3366", "#33FF57", "#FF9900", "#FFFFFF"]
    chosen_color = random.choice(neon_colors)
    rotation_angle = random.uniform(-6.0, 6.0)

    text_box_size = (950, 250)
    text_img = Image.new('RGBA', text_box_size, (0, 0, 0, 0))
    draw_text = ImageDraw.Draw(text_img)

    bbox = draw_text.textbbox((0, 0), headline_text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx, ty = (text_box_size[0] - tw) / 2, (text_box_size[1] - th) / 2

    draw_text.text((tx, ty), headline_text, font=font, fill=chosen_color, stroke_width=10, stroke_fill="black")
    rotated_text = text_img.rotate(rotation_angle, expand=True, resample=Image.Resampling.BICUBIC)

    # הזזנו את הכותרת ל-ry = 380 כדי שתשב בול מתחת לבאנרים העליונים!
    rx, ry = int((canvas_size[0] - rotated_text.width) / 2), 380
    canvas.paste(rotated_text, (rx, ry), rotated_text)

    # באדג' האחוזים והמחיר במרכז
    pct = stock_data['change_pct']
    pct_text = f"+{pct:.2f}%" if pct >= 0 else f"{pct:.2f}%"
    pct_color = "#00E676" if pct >= 0 else "#FF1744"
    price_text = f"${stock_data['current_price']:.2f}"

    badge_img = Image.new('RGBA', (900, 400), (0, 0, 0, 0))
    draw_badge = ImageDraw.Draw(badge_img)

    pct_font = load_system_font(120)
    price_font = load_system_font(70)

    p_bbox = draw_badge.textbbox((0, 0), pct_text, font=pct_font)
    pw = p_bbox[2] - p_bbox[0]
    draw_badge.text(((900 - pw) / 2, 20), pct_text, font=pct_font, fill=pct_color, stroke_width=12, stroke_fill="black")

    pr_bbox = draw_badge.textbbox((0, 0), price_text, font=price_font)
    prw = pr_bbox[2] - pr_bbox[0]
    draw_badge.text(((900 - prw) / 2, 220), price_text, font=price_font, fill="white", stroke_width=8, stroke_fill="black")

    canvas.paste(badge_img, (90, 750), badge_img)

    output_path = "overlay_graphics.png"
    canvas.save(output_path)
    return output_path

# -----------------------------------------------------------------------------
# 5. יצירת אלמנט הכתוביות
# -----------------------------------------------------------------------------
def create_caption_clip(text, duration, canvas_size=(1000, 220)):
    img = Image.new('RGBA', canvas_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = load_system_font(52)

    display_text = text.upper()

    bbox = draw.textbbox((0, 0), display_text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx, ty = (canvas_size[0] - tw) / 2, (canvas_size[1] - th) / 2

    draw.text(
        (tx, ty),
        display_text,
        font=font,
        fill="#FFE600",
        stroke_width=8,
        stroke_fill="black"
    )

    img_filename = f"temp_cap_{abs(hash(text))}.png"
    img.save(img_filename)

    clip = ImageClip(img_filename).set_duration(duration)
    return clip, img_filename

# -----------------------------------------------------------------------------
# 6. הנפשת הגרף
# -----------------------------------------------------------------------------


def make_animated_chart_video(stock_data, duration, market_metrics=None, size=(1080, 1920)):
    prices = stock_data['history'].values
    n_points = len(prices)
    start_points = min(5, n_points)

    is_positive = stock_data['change_pct'] >= 0
    line_color = "#00E676" if is_positive else "#FF1744"
    bg_color = "#0B0E14"
    grid_color = "#1E2638"

    fig, ax = plt.subplots(figsize=(10.8, 19.2), dpi=100)
    canvas = FigureCanvasAgg(fig)

    y_min, y_max = min(prices), max(prices)
    y_range = y_max - y_min if y_max != y_min else 1.0
    y_padding = y_range * 0.30

    def make_frame(t):
        ax.clear()
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)

        # 1. רשת בורסה
        ax.grid(True, color=grid_color, linestyle='--', linewidth=1.5, alpha=0.4)
        ax.set_axisbelow(True)

        idx = int(start_points + (t / duration) * (n_points - start_points))
        idx = min(max(start_points, idx), n_points)

        sub_prices = prices[:idx]
        curr_price = sub_prices[-1]

        # 2. קו הגרף (עובי מאוזן = 8)
        ax.plot(sub_prices, color=line_color, linewidth=8)
        ax.fill_between(range(len(sub_prices)), sub_prices, y_min - y_padding, color=line_color, alpha=0.15)

        # 3. נקודה בקצה הקו
        curr_x = len(sub_prices) - 1
        ax.plot(curr_x, curr_price, marker='o', markersize=14, color=line_color)

        # 4. תווית מחיר זזה קומפקטית מעל הנקודה (fontsize=28 במקום 42)
        ax.text(
            curr_x,
            curr_price + (y_padding * 0.12),
            f" ${curr_price:.2f} ",
            color="white",
            fontsize=28,
            fontweight="bold",
            ha="center",
            va="bottom",
            bbox=dict(boxstyle="round,pad=0.3", facecolor=line_color, edgecolor="none", alpha=0.95)
        )

        # 5. באנרים עליונים קומפקטיים (לא מפריעים לכותרות)
        if market_metrics:
            # S&P 500 | BTC בגודל נקי מעלה (fontsize=24)
            ticker_text = f"S&P 500: {market_metrics.get('sp500')}   |   BTC: {market_metrics.get('btc')}"
            ax.text(
                0.5, 0.96, ticker_text,
                transform=ax.transAxes,
                color="#FFFFFF", fontsize=24, fontweight="bold", ha="center", va="top",
                bbox=dict(boxstyle="square,pad=0.5", facecolor="#141A26", edgecolor="#2A3447", alpha=0.9, linewidth=1.5)
            )

            # MARKET CAP קטן בפינה השמאלית העליונה (fontsize=24, y=0.90)
            mcap_text = f"MARKET CAP: {market_metrics.get('mcap')}"
            ax.text(
                0.5, 0.89, mcap_text,  # x=0.5 מעמיד אותה במרכז האופקי
                transform=ax.transAxes,
                color="white",
                fontsize=24,
                fontweight="bold",
                ha="center", va="top",  # ha="center" מיישר את התיבה למרכז
                bbox=dict(boxstyle="round,pad=0.4", facecolor="#141A26", edgecolor=line_color, alpha=0.9, linewidth=1.5)
            )

        ax.set_xticks(np.linspace(0, n_points, 6))
        ax.set_yticks(np.linspace(y_min - y_padding, y_max + y_padding, 8))

        # מעלימים את המספרים והסרגלים, אך שומרים על הרשת!
        ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)

        # הגדרת הרשת
        ax.grid(True, color="#1E2638", linestyle='--', linewidth=1.8, alpha=0.6)
        ax.set_axisbelow(True)  # דוחף את הרשת אל מאחורי הגרף והשכבות

        ax.set_xlim(-1, n_points + 1)
        ax.set_ylim(y_min - y_padding, y_max + y_padding)

        for spine in ax.spines.values():
            spine.set_visible(False)

        canvas.draw()
        rgba = np.asarray(canvas.buffer_rgba())
        return rgba[:, :, :3]

    video_clip = VideoClip(make_frame, duration=duration)
    plt.close(fig)
    return video_clip

# -----------------------------------------------------------------------------
# 7. הרכבה ורינדור סופי של הווידאו
# -----------------------------------------------------------------------------
def render_final_video():
    stock_data, ticker = get_top_moving_stock()
    clean_symbol = stock_data['symbol']
    market_metrics = get_market_metrics(ticker)
    print("🤖 Generating script with gemini-flash-lite-latest...")
    script_data = generate_script_and_titles_with_ai(stock_data)

    print("\n" + "=" * 60)
    print(f"📌 YOUTUBE TITLE: {script_data.get('youtube_title')}")
    print(f"🎬 OVERLAY HEADLINE: {script_data.get('overlay_headline')}")
    print("=" * 60 + "\n")

    print("🎙️ Generating Voiceover...")
    audio_file = "voiceover.mp3"
    asyncio.run(create_tts_async(script_data['voiceover_text'], audio_file))

    audio_clip = AudioFileClip(audio_file)
    duration = audio_clip.duration

    print("🎯 Syncing captions with Whisper...")
    captions = get_exact_captions_with_whisper(audio_file, words_per_caption=2)

    caption_clips = []
    temp_cap_files = []

    print(f"💬 Creating {len(captions)} frame-accurate caption overlays...")
    for cap in captions:
        c_dur = cap['end'] - cap['start']
        if c_dur <= 0.05:
            continue
        c_clip, tmp_img = create_caption_clip(cap['text'], c_dur)
        c_clip = c_clip.set_start(cap['start']).set_position(('center', 1420))
        caption_clips.append(c_clip)
        temp_cap_files.append(tmp_img)

    print("🎨 Creating High-Energy Graphics Overlay...")
    overlay_img_path = create_overlay_graphics(script_data, stock_data)
    overlay_clip = ImageClip(overlay_img_path).set_duration(duration)

    print("📊 Rendering Animated Stock Chart...")
    chart_clip = make_animated_chart_video(stock_data, duration=duration, market_metrics=market_metrics)

    print("🎬 Compositing Video with Captions...")
    all_layers = [chart_clip, overlay_clip] + caption_clips
    final_video = CompositeVideoClip(all_layers).set_audio(audio_clip).set_duration(duration)


    output_filename = f"STOCK_{clean_symbol}_{int(stock_data['change_pct'])}pct.mp4"

    final_video.write_videofile(
        output_filename,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        logger=None,  # ⬅️ קריטי: מכבה את מד ההתקדמות שחוסם את Streamlit
        threads=1,  # ⬅️ קריטי: מונע התנגשות תהליכונים (Threads) בתוך Streamlit
        preset="ultrafast"
    )

    # --- ניקוי כל קבצי התמונות והאודיו הזמניים ---
    for tmp in temp_cap_files + [overlay_img_path, audio_file]:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass

    print(f"\n✅ SUCCESS! Video saved as: {output_filename}")
    tags = script_data.get('tags')
    if isinstance(tags, str):
        parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]
    elif isinstance(tags, list):
        parsed_tags = tags
    else:
        parsed_tags = []
    upload_video(
        file_path=output_filename,
        title=script_data.get('youtube_title'),
        description=script_data.get('description'),
        tags=parsed_tags
    )
    print(f"🚀 Uploaded To YouTube: {script_data.get('youtube_title')}")


def view_final_video():
    stock_data, ticker = get_top_moving_stock()
    market_metrics = get_market_metrics(ticker)
    print("🤖 Generating script with gemini-flash-lite-latest...")
    script_data = generate_script_and_titles_with_ai(stock_data)

    print("\n" + "=" * 60)
    print(f"📌 YOUTUBE TITLE: {script_data.get('youtube_title')}")
    print(f"🎬 OVERLAY HEADLINE: {script_data.get('overlay_headline')}")
    print("=" * 60 + "\n")

    print("🎙️ Generating Voiceover...")
    audio_file = "voiceover.mp3"
    asyncio.run(create_tts_async(script_data['voiceover_text'], audio_file))

    audio_clip = AudioFileClip(audio_file)
    duration = audio_clip.duration

    print("🎯 Syncing captions with Whisper...")
    captions = get_exact_captions_with_whisper(audio_file, words_per_caption=2)

    caption_clips = []
    temp_cap_files = []

    print(f"💬 Creating {len(captions)} frame-accurate caption overlays...")
    for cap in captions:
        c_dur = cap['end'] - cap['start']
        if c_dur <= 0.05:
            continue
        c_clip, tmp_img = create_caption_clip(cap['text'], c_dur)
        c_clip = c_clip.set_start(cap['start']).set_position(('center', 1420))
        caption_clips.append(c_clip)
        temp_cap_files.append(tmp_img)

    print("🎨 Creating High-Energy Graphics Overlay...")
    overlay_img_path = create_overlay_graphics(script_data, stock_data)
    overlay_clip = ImageClip(overlay_img_path).set_duration(duration)

    print("📊 Rendering Animated Stock Chart...")
    chart_clip = make_animated_chart_video(stock_data, duration=duration, market_metrics=market_metrics)
    bg_video = VideoFileClip("trading_floor_loop.mp4")
    bg_video = bg_video.loop(duration=duration)  # התאמה לאורך הסרטון
    bg_video = bg_video.resize(height=1920).crop(x_center=bg_video.w / 2, width=1080)  # התאמה ל-9:16
    bg_video = bg_video.colorx(0.22)

    print("🎬 Compositing Video with Captions...")
    all_layers = [bg_video,chart_clip, overlay_clip] + caption_clips
    final_video = CompositeVideoClip(all_layers).set_audio(audio_clip).set_duration(duration)



    clean_symbol = stock_data['symbol']
    output_filename = f"STOCK_{clean_symbol}_{int(stock_data['change_pct'])}pct.mp4"
    preview_frame = final_video.get_frame(t=2.0)
    st.image(
        preview_frame,
        caption="📸 תמונה מקדימה מתוך final_video (לפני הרינדור)",
        use_container_width=True
    )
    try:
        final_video.write_videofile(
            output_filename,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            logger=None,  # ⬅️ קריטי: מכבה את מד ההתקדמות שחוסם את Streamlit
            threads=1,  # ⬅️ קריטי: מונע התנגשות תהליכונים (Threads) בתוך Streamlit
            preset="ultrafast"
        )
    except Exception as e:
        print(e)

    # --- ניקוי כל קבצי התמונות והאודיו הזמניים ---
    for tmp in temp_cap_files + [overlay_img_path, audio_file]:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass

    print(f"\n✅ SUCCESS! Video saved as: {output_filename}")
    return output_filename

if __name__ == "__main__":
    render_final_video()