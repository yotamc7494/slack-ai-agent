import os
from datetime import date
import json
import asyncio
import random
import numpy as np
import matplotlib.pyplot as plt
import yfinance as yf
import edge_tts
import whisper
import shutil
from dotenv import load_dotenv

import PIL.Image
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types

from moviepy.editor import (
    AudioFileClip, ImageClip, VideoClip, CompositeVideoClip
)

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

TICKERS_TO_CHECK = ["NVDA", "TSLA", "AAPL", "AMD", "PLTR", "AMZN", "MSFT", "GOOGL"]
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


def get_top_moving_stock():
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
                max_change = pct_change
                best_ticker = ticker_symbol
                raw_pct = ((curr_price - prev_close) / prev_close) * 100
                top_data = {
                    "symbol": ticker_symbol,
                    "current_price": round(curr_price, 2),
                    "change_pct": round(raw_pct, 2),
                    "history": hist['Close']
                }
        except Exception:
            continue

    if not top_data and used_today:
        print("⚠️ All stocks in TICKERS_TO_CHECK were already used today! Resetting selection...")
        return get_top_moving_stock_fallback()

    if top_data:
        mark_stock_as_used(best_ticker)
        print(f"🎯 Selected: {best_ticker} with {top_data['change_pct']}% change")

    return top_data


def get_top_moving_stock_fallback():
    if os.path.exists(USED_STOCKS_FILE):
        os.remove(USED_STOCKS_FILE)
    return get_top_moving_stock()

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

    Requirements:
    1. Strong, scroll-stopping hook in the first second.
    2. Explain the price movement in exciting, clear English.
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
    font_candidates = ["impact.ttf", "ariblk.ttf", "arialbd.ttf", "trebucbd.ttf", "verdana.ttf"]
    for font_name in font_candidates:
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue
    return ImageFont.load_default()

def create_overlay_graphics(script_data, stock_data, canvas_size=(1080, 1920)):
    canvas = Image.new('RGBA', canvas_size, (0, 0, 0, 0))

    headline_text = script_data.get("overlay_headline", f"{stock_data['symbol']} MOVES!").upper()
    font_size = 90 if len(headline_text) < 15 else 70
    font = load_system_font(font_size)

    neon_colors = ["#FFD700", "#00FFFF", "#FF3366", "#33FF57", "#FF9900", "#FFFFFF"]
    chosen_color = random.choice(neon_colors)
    rotation_angle = random.uniform(-12.0, 12.0)

    text_box_size = (1000, 300)
    text_img = Image.new('RGBA', text_box_size, (0, 0, 0, 0))
    draw_text = ImageDraw.Draw(text_img)

    bbox = draw_text.textbbox((0, 0), headline_text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx, ty = (text_box_size[0] - tw) / 2, (text_box_size[1] - th) / 2

    draw_text.text((tx, ty), headline_text, font=font, fill=chosen_color, stroke_width=10, stroke_fill="black")
    rotated_text = text_img.rotate(rotation_angle, expand=True, resample=Image.Resampling.BICUBIC)

    rx, ry = int((canvas_size[0] - rotated_text.width) / 2), 180
    canvas.paste(rotated_text, (rx, ry), rotated_text)

    pct = stock_data['change_pct']
    pct_text = f"+{pct}%" if pct >= 0 else f"{pct}%"
    pct_color = "#00E676" if pct >= 0 else "#FF1744"
    price_text = f"${stock_data['current_price']}"

    badge_img = Image.new('RGBA', (900, 450), (0, 0, 0, 0))
    draw_badge = ImageDraw.Draw(badge_img)

    pct_font = load_system_font(140)
    price_font = load_system_font(75)

    p_bbox = draw_badge.textbbox((0, 0), pct_text, font=pct_font)
    pw = p_bbox[2] - p_bbox[0]
    draw_badge.text(((900 - pw) / 2, 40), pct_text, font=pct_font, fill=pct_color, stroke_width=12, stroke_fill="black")

    pr_bbox = draw_badge.textbbox((0, 0), price_text, font=price_font)
    prw = pr_bbox[2] - pr_bbox[0]
    draw_badge.text(((900 - prw) / 2, 260), price_text, font=price_font, fill="white", stroke_width=8, stroke_fill="black")

    canvas.paste(badge_img, (90, 800), badge_img)

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
def make_animated_chart_video(stock_data, duration, size=(1080, 1920)):
    prices = stock_data['history'].values
    n_points = len(prices)

    is_positive = stock_data['change_pct'] >= 0
    line_color = "#00E676" if is_positive else "#FF1744"
    bg_color = "#0B0E14"

    fig, ax = plt.subplots(figsize=(10.8, 19.2), dpi=100)

    def make_frame(t):
        ax.clear()
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)

        idx = int((t / duration) * n_points)
        idx = max(2, min(idx, n_points))
        sub_prices = prices[:idx]

        ax.plot(sub_prices, color=line_color, linewidth=6)
        ax.fill_between(range(len(sub_prices)), sub_prices, min(prices), color=line_color, alpha=0.18)

        ax.axis("off")
        fig.canvas.draw()

        rgba = np.asarray(fig.canvas.buffer_rgba())
        return rgba[:, :, :3]

    video_clip = VideoClip(make_frame, duration=duration)
    plt.close(fig)
    return video_clip


def upload_to_youtube(filename, title, description, tags):
    uploader = YouTubeUploader()

    # טיפול בטאגים (המרה מרשימה או מחרוזת מופרדת בפסיקים)
    if isinstance(tags, str):
        parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]
    else:
        parsed_tags = tags

    video_to_upload = {
        'file_path': filename,
        'title': title,
        'description': description,
        'tags': parsed_tags,
        'category_id': '24',
        'privacy_status': 'public',
        'auto_delete': True  # מוחק את הקובץ בסיום ההעלאה
    }

    uploader.upload_video(**video_to_upload)

# -----------------------------------------------------------------------------
# 7. הרכבה ורינדור סופי של הווידאו
# -----------------------------------------------------------------------------
def render_final_video():
    stock_data = get_top_moving_stock()

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
    chart_clip = make_animated_chart_video(stock_data, duration=duration)

    print("🎬 Compositing Video with Captions...")
    all_layers = [chart_clip, overlay_clip] + caption_clips
    final_video = CompositeVideoClip(all_layers).set_audio(audio_clip).set_duration(duration)

    clean_symbol = stock_data['symbol']
    output_filename = f"STOCK_{clean_symbol}_{int(stock_data['change_pct'])}pct.mp4"

    final_video.write_videofile(
        output_filename,
        fps=24,
        codec="libx264",
        audio_codec="aac"
    )

    # --- ניקוי כל קבצי התמונות והאודיו הזמניים ---
    for tmp in temp_cap_files + [overlay_img_path, audio_file]:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass

    print(f"\n✅ SUCCESS! Video saved as: {output_filename}")
    upload_to_youtube(
        output_filename,
        script_data.get('youtube_title'),
        script_data.get('description'),
        script_data.get('tags')
    )
    print(f"🚀 Uploaded To YouTube: {script_data.get('youtube_title')}")

if __name__ == "__main__":
    render_final_video()