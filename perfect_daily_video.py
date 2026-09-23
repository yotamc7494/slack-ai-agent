import os
import sys
import logging
import asyncio
import json
import re
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.interpolate import make_interp_spline
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
import edge_tts
from google import genai
from google.genai import types
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
import requests
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    VideoClip,
    TextClip,
    CompositeVideoClip,
    concatenate_videoclips,
    afx,
)
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("PerfectDailyVideo")

# ---------------------------------------------------------
# Pydantic Schemas for Structured LLM Output
# ---------------------------------------------------------
class StockAnalysis(BaseModel):
    ticker: str = Field(description="Stock ticker symbol, e.g. NVDA")
    company_spoken_name: str = Field(description="Full spoken company name for TTS, e.g. Nvidia")
    script: str = Field(description="Spoken narrative for TTS (15-20s, ~40 words). Numbers spelled out.")
    timeframe: str = Field(description="Chart timeframe: '1d', '1mo', '3mo', '6mo', or '1y'")
    interval: str = Field(description="Chart interval: '5m' for 1d, '1d' for others")
    key_levels: List[float] = Field(default=[], description="Important price levels to highlight on chart")
    highlight_type: str = Field(default="none", description="Type of overlay: 'breakout', 'support', 'resistance', or 'none'")

class FullVideoScriptSchema(BaseModel):
    intro_script: str = Field(description="STRICTLY 65 to 75 words English intro script for 30 seconds audio.")
    analyzed_stocks: List[StockAnalysis]
    youtube_title: str
    description: str
    tags: str

# ---------------------------------------------------------
# Helper Functions & TTS Normalization
# ---------------------------------------------------------
def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("🚨 GEMINI_API_KEY is missing!")
    return genai.Client(api_key=api_key)

def format_seconds_to_timestamp(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins:02d}:{secs:02d}"

def clean_script_for_tts(text: str) -> str:
    """Narrows ticker symbols & characters into phonetic words."""
    text = text.replace("$", "").replace("%", " percent")
    replacements = {
        r'\bNVDA\b': 'Nvidia', r'\bTSLA\b': 'Tesla', r'\bAAPL\b': 'Apple',
        r'\bAMZN\b': 'Amazon', r'\bMSFT\b': 'Microsoft', r'\bGOOGL\b': 'Google',
        r'\bMETA\b': 'Meta', r'\bBTC\b': 'Bitcoin', r'\bSPY\b': 'S and P 500', r'\bQQQ\b': 'Nasdaq'
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)
    return text

def generate_voiceover_audio(script_text: str, output_path: str = "temp_speech.mp3") -> float:
    clean_text = clean_script_for_tts(script_text)
    logger.info(f"🎙️ Generating TTS audio: {output_path}")

    async def _save():
        comm = edge_tts.Communicate(clean_text, "en-US-ChristopherNeural", rate="+5%")
        await comm.save(output_path)

    asyncio.run(_save())
    audio_clip = AudioFileClip(output_path)
    duration = audio_clip.duration
    audio_clip.close()
    return duration

# ---------------------------------------------------------
# 1. RSS & Robust Multi-Method Transcript Extraction
# ---------------------------------------------------------
MICHA_STOCKS_RSS = "https://www.youtube.com/feeds/videos.xml?channel_id=UCSxjNbPriyBh9RNl_QNSAtw"

def get_latest_micha_video_url() -> Optional[str]:
    logger.info("📡 Fetching latest video URL from YouTube RSS...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        response = requests.get(MICHA_STOCKS_RSS, headers=headers, timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            entry = root.find("{http://www.w3.org/2005/Atom}entry")
            if entry is not None:
                video_url = entry.find("{http://www.w3.org/2005/Atom}link").attrib.get("href")
                title = entry.find("{http://www.w3.org/2005/Atom}title").text
                logger.info(f"🎥 Found Latest Video: '{title}' ({video_url})")
                return video_url
        else:
            logger.error(f"❌ Failed to fetch RSS: HTTP Status {response.status_code}")
    except Exception as e:
        logger.error(f"❌ Exception fetching RSS: {e}")
    return None


def extract_video_id(url: str) -> Optional[str]:
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", url)
    return match.group(1) if match else None


def fetch_youtube_transcript_robust(video_id: str) -> Optional[str]:
    """
    תומך בכל הגרסאות של youtube-transcript-api (ישנות וחדשות).
    אם התמליל נכשל, מבצע חילוץ כתוביות דרך yt-dlp ללא הורדת אודיו/וידאו.
    """
    logger.info(f"📜 Attempting to fetch transcript for video ID: {video_id}...")

    # דרך 1: בדיקת מתודה סטטית (גרסאות ישנות)
    if hasattr(YouTubeTranscriptApi, 'get_transcript'):
        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['he', 'iw', 'en'])
            text = " ".join([item['text'] if isinstance(item, dict) else getattr(item, 'text', '') for item in transcript])
            if text.strip():
                logger.info("✅ Retrieved transcript via static YouTubeTranscriptApi.get_transcript")
                return text
        except Exception as e:
            logger.warning(f"⚠️ Static get_transcript failed: {e}")

    # דרך 2: יצירת אובייקט (גרסאות חדשות)
    try:
        api_instance = YouTubeTranscriptApi()
        fetch_method = getattr(api_instance, 'fetch', getattr(api_instance, 'get_transcript', None))
        if fetch_method:
            transcript = fetch_method(video_id)
            text = " ".join([item.text if hasattr(item, 'text') else item.get('text', '') for item in transcript])
            if text.strip():
                logger.info("✅ Retrieved transcript via YouTubeTranscriptApi instance call")
                return text
    except Exception as e:
        logger.warning(f"⚠️ Instance transcript fetch failed: {e}")

    # דרך 3: חילוץ כתוביות טקסט ישירות מ-yt-dlp ללא הורדת קובץ המדיה (עוקף חסימות Bot)
    try:
        logger.info("📜 Falling back to yt-dlp subtitle metadata extraction...")
        ydl_opts = {
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['he', 'iw', 'en'],
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            subtitles = info.get('subtitles') or info.get('automatic_captions')
            if subtitles:
                for lang in ['he', 'iw', 'en']:
                    if lang in subtitles:
                        json_sub = next((s['url'] for s in subtitles[lang] if s.get('ext') == 'json3'), None)
                        if json_sub:
                            resp = requests.get(json_sub, timeout=10)
                            if resp.status_code == 200:
                                events = resp.json().get('events', [])
                                text_parts = [
                                    seg.get('utf8', '').strip()
                                    for ev in events for seg in ev.get('segs', [])
                                    if seg.get('utf8', '').strip()
                                ]
                                full_text = " ".join(text_parts)
                                if full_text.strip():
                                    logger.info("✅ Retrieved transcript via yt-dlp subtitle JSON stream")
                                    return full_text
    except Exception as e:
        logger.warning(f"⚠️ Subtitle metadata extraction failed: {e}")

    return None


def download_youtube_audio_fallback(video_url: str, output_mp3="micha_input.mp3") -> str:
    """מופעל רק כגיבוי אחרון אם לא נמצאו כתוביות כלל"""
    logger.info(f"📥 Downloading audio fallback from {video_url}...")
    
    ydl_opts = {
        'format': 'ba/b',
        'outtmpl': 'micha_input.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android'],
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
        }
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])
    return output_mp3


def transcribe_audio_with_gemini(audio_path: str) -> str:
    logger.info("🧠 Transcribing audio with Financial Glossary Prompt...")
    client = get_gemini_client()
    audio_file = client.files.upload(file=audio_path)

    glossary_prompt = """
    תמלל את סרטון הסקירה הפיננסית במיקוד גבוה.
    
    מילון מונחים ודגשי תעתיק (השתמש במונחים אלה לדיוק מירבי):
    - מדדים ומניות: S&P 500, נאסד"ק (Nasdaq), ביטקוין (Bitcoin), QQQ, SPY, NVDA, TSLA, AAPL, AMZN, MSFT, GOOGL, META, AMD, INTEL.
    - מושגי מסחר: אופציות, פוטים (Puts), קולים (Calls), שורט (Short), לונג (Long), תמיכה (Support), התנגדות (Resistance), פריצה (Breakout), נר פטיש (Hammer Candle), נר היפוך, מחזור מסחר (Volume), גאפ (Gap).

    חלץ תמלול מדויק של כל המדדים, המניות והרמות הטכניות המוזכרות בסרטון.
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[audio_file, glossary_prompt]
    )
    client.files.delete(name=audio_file.name)
    return response.text

# ---------------------------------------------------------
# 2. Market Data Verification
# ---------------------------------------------------------
def extract_and_verify_ticker_data(raw_transcript: str) -> dict:
    logger.info("🔍 Extracting mentioned tickers and fetching ground-truth data...")
    client = get_gemini_client()
    
    prompt = f"Extract all stock tickers mentioned in this text as a JSON array of strings (e.g. ['NVDA', 'TSLA']): {raw_transcript}"
    res = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    
    tickers = []
    try:
        tickers = json.loads(re.search(r'\[.*\]', res.text, re.DOTALL).group(0))
    except Exception:
        tickers = ["NVDA", "TSLA", "AAPL"]

    verified_data = {}
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="5d")
            if not hist.empty:
                last_close = float(hist['Close'].iloc[-1])
                prev_close = float(hist['Close'].iloc[-2]) if len(hist) > 1 else last_close
                pct_change = ((last_close - prev_close) / prev_close) * 100
                verified_data[ticker] = {
                    "price": round(last_close, 2),
                    "pct_change": round(pct_change, 2)
                }
        except Exception as e:
            logger.warning(f"Failed to fetch market data for {ticker}: {e}")

    return verified_data

# ---------------------------------------------------------
# 3. AI Script Generation with Structured Schema
# ---------------------------------------------------------
def generate_verified_script(transcript: str, verified_market_data: dict) -> FullVideoScriptSchema:
    logger.info("📝 Generating structured video script...")
    client = get_gemini_client()

    prompt = f"""
    You are a Wall Street video producer. Synthesize this transcript and VERIFIED market data into an English script for YouTube.

    Raw Transcript:
    {transcript}

    Verified Market Data (MUST USE THESE EXACT NUMBERS):
    {json.dumps(verified_market_data, indent=2)}

    RULES:
    1. "intro_script": EXACTLY 65 TO 75 WORDS (~70 words). Covers market summary for 30s audio speed. Spell out numbers!
    2. "analyzed_stocks": Max 4 key stocks. Provide exact technical key levels (e.g. [120.0, 125.0]) and highlight_type ('breakout', 'support', 'resistance', 'none').
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=FullVideoScriptSchema
        )
    )
    return FullVideoScriptSchema.model_validate_json(response.text)

# ---------------------------------------------------------
# 4. Dynamic 30-Sec Intro Rendering
# ---------------------------------------------------------
def fetch_intro_index_data():
    logger.info("📊 Fetching intraday index data...")
    spy = yf.Ticker("SPY").history(period="1d", interval="5m", prepost=True)
    qqq = yf.Ticker("QQQ").history(period="1d", interval="5m", prepost=True)
    btc = yf.Ticker("BTC-USD").history(period="1d", interval="5m", prepost=True)

    min_len = min(len(spy), len(qqq), len(btc))
    if min_len == 0:
        spy = yf.Ticker("SPY").history(period="2d", interval="5m", prepost=True).tail(78)
        qqq = yf.Ticker("QQQ").history(period="2d", interval="5m", prepost=True).tail(78)
        btc = yf.Ticker("BTC-USD").history(period="2d", interval="5m", prepost=True).tail(78)
        min_len = min(len(spy), len(qqq), len(btc))

    spy_v = spy["Close"].values
    qqq_v = qqq["Close"].values
    btc_v = btc["Close"].values

    spy_pct_0 = spy_v[0]
    spy_pct = ((spy_v - spy_pct_0) / spy_pct_0) * 100

    qqq_pct_0 = qqq_v[0]
    qqq_pct = ((qqq_v - qqq_pct_0) / qqq_pct_0) * 100

    btc_pct_0 = btc_v[0]
    btc_pct = ((btc_v - btc_pct_0) / btc_pct_0) * 100

    x_raw = np.linspace(0, 1, min_len)
    x_smooth = np.linspace(0, 1, 300)

    return {
        "x": x_smooth,
        "QQQ": (make_interp_spline(x_raw, qqq_pct, k=3)(x_smooth), qqq_v[-1]),
        "SPY": (make_interp_spline(x_raw, spy_pct, k=3)(x_smooth), spy_v[-1]),
        "BTC": (make_interp_spline(x_raw, btc_pct, k=3)(x_smooth), btc_v[-1]),
        "date_str": spy.index[-1].strftime("%b %d, %Y").upper()
    }


def render_dynamic_intro_clip(market_data: dict, audio_path: str, duration: float) -> VideoClip:
    logger.info(f"🎨 Rendering 30-Sec Retention Intro (Duration: {duration:.2f}s)...")
    voice_clip = AudioFileClip(audio_path)

    fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
    canvas = FigureCanvasAgg(fig)
    fig.patch.set_facecolor('#0B0E14')

    ax = fig.add_axes([0.08, 0.12, 0.88, 0.73])
    ax.set_facecolor('#0B0E14')

    x_smooth = market_data["x"]
    assets = ["QQQ", "SPY", "BTC"]
    colors = {"QQQ": "#00E5FF", "SPY": "#00FFA3", "BTC": "#FFB800"}

    def make_frame(t):
        ax.clear()
        ax.set_facecolor('#0B0E14')

        segment_duration = duration / 3.0
        asset_idx = min(int(t // segment_duration), 2)
        active_asset = assets[asset_idx]

        local_t = t % segment_duration
        progress = min(local_t / segment_duration, 1.0)
        curr_step = max(1, int(progress * len(x_smooth)))

        y_vals, current_price = market_data[active_asset]
        c_color = colors[active_asset]

        fig.text(0.08, 0.93, f"MARKET OVERVIEW: {active_asset}", fontsize=24, fontweight='bold', color=c_color)
        fig.text(0.08, 0.89, f"{market_data['date_str']} | Current: ${current_price:,.2f}", fontsize=14, color='#8B949E')

        ax.plot(x_smooth[:curr_step], y_vals[:curr_step], color=c_color, linewidth=4.0)
        ax.scatter(x_smooth[curr_step-1], y_vals[curr_step-1], color=c_color, s=150, zorder=10)

        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(min(y_vals) - 0.5, max(y_vals) + 0.5)
        ax.grid(True, linestyle='--', alpha=0.15, color='#8B949E')

        for spine in ['top', 'right']: ax.spines[spine].set_visible(False)
        for spine in ['left', 'bottom']: ax.spines[spine].set_color('#30363D')

        canvas.draw()
        return np.asarray(canvas.buffer_rgba())[:, :, :3]

    clip = VideoClip(make_frame, duration=duration).set_audio(voice_clip)
    return clip

# ---------------------------------------------------------
# 5. Dynamic Stock Chart with Annotations
# ---------------------------------------------------------
def render_annotated_stock_clip(stock_info: StockAnalysis, verified_price: float, audio_path: str, duration: float) -> VideoClip:
    ticker = stock_info.ticker
    logger.info(f"📈 Rendering annotated chart for {ticker} with key levels {stock_info.key_levels}...")
    voice_clip = AudioFileClip(audio_path)

    df = yf.Ticker(ticker).history(period=stock_info.timeframe, interval=stock_info.interval, prepost=True)
    if df.empty:
        df = yf.Ticker(ticker).history(period="1mo", interval="1d")

    fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
    canvas = FigureCanvasAgg(fig)
    fig.patch.set_facecolor('#0B0E14')

    ax = fig.add_axes([0.08, 0.10, 0.88, 0.70])
    ax.set_facecolor('#0B0E14')

    opens, closes = df['Open'].values, df['Close'].values
    highs, lows = df['High'].values, df['Low'].values
    x_idxs = np.arange(len(df))
    candle_colors = np.where(closes >= opens, '#00FFA3', '#FF3366')

    # Draw Candlesticks
    ax.vlines(x_idxs, lows, highs, color=candle_colors, linewidth=1.2)
    ax.bar(x_idxs, closes - opens, bottom=opens, color=candle_colors, width=0.6)

    # Draw Annotations / Key Levels
    for level in stock_info.key_levels:
        ax.axhline(y=level, color='#FFD700', linestyle='--', linewidth=2.0, alpha=0.8)
        ax.text(x_idxs[-1], level, f" Key Level: ${level:.2f}", color='#FFD700', fontsize=12, fontweight='bold', va='center')

    # Highlight Callouts
    if stock_info.highlight_type.lower() == "breakout":
        ax.annotate('🔥 BREAKOUT ZONE', xy=(x_idxs[-1], closes[-1]), xytext=(x_idxs[-1] - 10, closes[-1] * 1.03),
                    arrowprops=dict(facecolor='#00FFA3', shrink=0.05), fontsize=14, fontweight='bold', color='#00FFA3')
    elif stock_info.highlight_type.lower() == "support":
        ax.annotate('🛡️ SUPPORT LEVEL', xy=(x_idxs[-1], lows.min()), xytext=(x_idxs[-1] - 10, lows.min() * 0.97),
                    arrowprops=dict(facecolor='#00E5FF', shrink=0.05), fontsize=14, fontweight='bold', color='#00E5FF')

    fig.text(0.08, 0.90, f"{ticker} - {stock_info.company_spoken_name}", fontsize=26, fontweight='bold', color='#FFFFFF')
    fig.text(0.08, 0.85, f"Verified Price: ${verified_price:.2f} | Timeframe: {stock_info.timeframe}", fontsize=14, color='#8B949E')

    ax.set_xlim(-1, len(df))
    ax.grid(True, linestyle='--', alpha=0.15, color='#8B949E')
    for spine in ['top', 'right']: ax.spines[spine].set_visible(False)

    def make_frame(t):
        canvas.draw()
        return np.asarray(canvas.buffer_rgba())[:, :, :3]

    clip = VideoClip(make_frame, duration=duration).set_audio(voice_clip)
    return clip

# ---------------------------------------------------------
# Subtitles & Final Pipeline Assembly
# ---------------------------------------------------------
def add_subtitles(video_clip: VideoClip, text: str) -> CompositeVideoClip:
    txt = TextClip(text, fontsize=36, color='yellow', font='Arial-Bold', method='caption', size=(video_clip.w * 0.8, None))
    txt = txt.set_duration(video_clip.duration).set_position(('center', 0.85), relative=True)
    return CompositeVideoClip([video_clip, txt])

def run_perfect_pipeline(output_filename="perfect_daily_recap.mp4"):
    logger.info("🚀 Launching Perfect Daily Video Pipeline...")
    temp_files = []
    timestamps = []
    current_time = 0.0

    try:
        video_url = get_latest_micha_video_url()
        if not video_url:
            raise ValueError("❌ Could not retrieve YouTube video URL from RSS.")

        video_id = extract_video_id(video_url)
        transcript = fetch_youtube_transcript_robust(video_id) if video_id else None

        if not transcript:
            logger.warning("⚠️ Direct transcript unavailable for video. Attempting audio fallback...")
            audio_mp3 = download_youtube_audio_fallback(video_url)
            temp_files.append(audio_mp3)
            transcript = transcribe_audio_with_gemini(audio_mp3)

        # Step 2: Extract & Verify Market Data
        verified_data = extract_and_verify_ticker_data(transcript)

        # Step 3: Structured Script Generation
        script_schema = generate_verified_script(transcript, verified_data)

        # Step 4: Render Intro Clip
        intro_audio_file = "temp_intro.mp3"
        intro_duration = generate_voiceover_audio(script_schema.intro_script, intro_audio_file)
        temp_files.append(intro_audio_file)

        market_data = fetch_intro_index_data()
        intro_clip = render_dynamic_intro_clip(market_data, intro_audio_file, intro_duration)
        intro_clip = add_subtitles(intro_clip, script_schema.intro_script)

        timestamps.append(f"{format_seconds_to_timestamp(current_time)} Market Overview")
        current_time += intro_duration

        # Step 5: Render Stock Clips with Annotations
        stock_clips = []
        for stock_info in script_schema.analyzed_stocks:
            stock_audio_file = f"temp_{stock_info.ticker}.mp3"
            stock_duration = generate_voiceover_audio(stock_info.script, stock_audio_file)
            temp_files.append(stock_audio_file)

            verified_price = verified_data.get(stock_info.ticker, {}).get("price", 0.0)
            s_clip = render_annotated_stock_clip(stock_info, verified_price, stock_audio_file, stock_duration)
            s_clip = add_subtitles(s_clip, stock_info.script)
            stock_clips.append(s_clip)

            timestamps.append(f"{format_seconds_to_timestamp(current_time)} {stock_info.ticker}")
            current_time += stock_duration

        # Step 6: Concatenate & Export
        final_video = concatenate_videoclips([intro_clip] + stock_clips)
        final_video.write_videofile(output_filename, fps=30, codec="libx264", audio_codec="aac")

        logger.info("✅ Perfect Video Created Successfully!")
        logger.info("Chapters:\n" + "\n".join(timestamps))

    finally:
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)

if __name__ == "__main__":
    run_perfect_pipeline()
