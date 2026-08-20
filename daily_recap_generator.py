import os
import sys
import logging
import textwrap
import asyncio
import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.interpolate import make_interp_spline
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.lines import Line2D
from uploader import upload_video
import edge_tts
from google import genai
from google.genai import types
from thumbnail import generate_daily_thumbnail
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    VideoClip,
    concatenate_videoclips,
    afx,
)
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------
# הגדרות Logging ומערכת
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("VideoEngine")

MEGA_CAP_POOL = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA"]

STOCK_POOL = [
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA",
    "AMD", "PLTR", "INTC", "NFLX", "DIS", "COIN", "MSTR", "ARM",
    "SMCI", "LLY", "NKE", "PYPL", "SHOP", "BABA", "BA", "AVGO",
    "ORCL", "CRM", "QCOM", "JPM", "V", "MA", "UNH",
    "XOM", "CVX", "BAC", "WMT", "COST", "HD", "PG", "JNJ",
    "PFE", "ABBV", "MRK", "NOW", "UBER", "ABNB", "HOOD"
]


# ---------------------------------------------------------
# 0. פונקציות עזר כלליות
# ---------------------------------------------------------
def generate_voiceover_audio(
        script_text,
        output_path="temp_narration.mp3",
        voice="en-GB-RyanNeural",
        rate="+12%",
):
    """מייצרת קובץ קריינות (.mp3) באמצעות edge-tts."""
    logger.info(f"🎙️ מייצר קריינות קולית עבור {output_path}...")

    async def _save_audio():
        communicate = edge_tts.Communicate(script_text, voice, rate=rate)
        await communicate.save(output_path)

    asyncio.run(_save_audio())
    return output_path


def format_large_number(num):
    if num is None or np.isnan(num):
        return "N/A"
    if num >= 1e12:
        return f"${num / 1e12:.2f}T"
    if num >= 1e9:
        return f"${num / 1e9:.2f}B"
    if num >= 1e6:
        return f"${num / 1e6:.2f}M"
    return f"${num:,.0f}"


def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            pass
    if not api_key:
        raise ValueError("🚨 GEMINI_API_KEY is missing!")
    return genai.Client(api_key=api_key)


# ---------------------------------------------------------
# 1. סקציית מאקרו ומדדים יומיים (Daily Index & Market Recap)
# ---------------------------------------------------------
def fetch_daily_market_data(target_points=1000):
    logger.info("📊 שולף נתוני מסחר תוך-יומיים עבור SPY, QQQ ו-BTC-USD...")

    spy = yf.Ticker("SPY")
    qqq = yf.Ticker("QQQ")
    btc = yf.Ticker("BTC-USD")

    # שליפת נתונים תוך-יומיים במרווח של 5 דקות
    df_spy = spy.history(period="1d", interval="5m")
    df_qqq = qqq.history(period="1d", interval="5m")
    df_btc = btc.history(period="1d", interval="5m")

    min_len = min(len(df_spy), len(df_qqq), len(df_btc))
    if min_len == 0:
        # Fallback אם השוק סגור או אין נתוני 1d
        df_spy = spy.history(period="2d", interval="5m").tail(78)
        df_qqq = qqq.history(period="2d", interval="5m").tail(78)
        df_btc = btc.history(period="2d", interval="5m").tail(78)
        min_len = min(len(df_spy), len(df_qqq), len(df_btc))

    df_spy = df_spy.iloc[-min_len:]
    df_qqq = df_qqq.iloc[-min_len:]
    df_btc = df_btc.iloc[-min_len:]

    date_str = df_spy.index[-1].strftime("%b %d, %Y").upper()

    spy_raw = df_spy["Close"].values
    qqq_raw = df_qqq["Close"].values
    btc_raw = df_btc["Close"].values

    spy_pct_raw = ((spy_raw - spy_raw[0]) / spy_raw[0]) * 100
    qqq_pct_raw = ((qqq_raw - qqq_raw[0]) / qqq_raw[0]) * 100
    btc_pct_raw = ((btc_raw - btc_raw[0]) / btc_raw[0]) * 100

    x_raw = np.linspace(0, 1, min_len)
    x_smooth = np.linspace(0, 1, target_points)

    spl_spy = make_interp_spline(x_raw, spy_pct_raw, k=3)(x_smooth)
    spl_qqq = make_interp_spline(x_raw, qqq_pct_raw, k=3)(x_smooth)
    spl_btc = make_interp_spline(x_raw, btc_pct_raw, k=3)(x_smooth)

    spl_spy_p = make_interp_spline(x_raw, spy_raw, k=3)(x_smooth)
    spl_qqq_p = make_interp_spline(x_raw, qqq_raw, k=3)(x_smooth)
    spl_btc_p = make_interp_spline(x_raw, btc_raw, k=3)(x_smooth)

    return {
        "x_smooth": x_smooth,
        "spy_pct": spl_spy,
        "qqq_pct": spl_qqq,
        "btc_pct": spl_btc,
        "spy_prices": spl_spy_p,
        "qqq_prices": spl_qqq_p,
        "btc_prices": spl_btc_p,
        "date_str": date_str,
        "total_steps": target_points,
        "sp500_pct_change": float(spy_pct_raw[-1]),
        "qqq_pct_change": float(qqq_pct_raw[-1]),
        "btc_pct_change": float(btc_pct_raw[-1]),
    }


def get_daily_macro_news_events():
    logger.info("📰 שולף חדשות מאקרו יומיומיות מ-Google News RSS...")
    query = "US+economy+Fed+inflation+stock+market+when:1d"
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=1)
    events = []

    try:
        req = urllib.request.Request(rss_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            root = ET.fromstring(response.read())
        for item in root.findall('.//item'):
            pub_date_str = item.findtext('pubDate')
            title = item.findtext('title') or ''

            if pub_date_str:
                pub_date = parsedate_to_datetime(pub_date_str)
                if pub_date < cutoff_date:
                    continue

            publisher = "DAILY NEWS"
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                headline = parts[0]
                publisher = parts[1].upper()
            else:
                headline = title

            events.append({
                'tag': publisher[:18],
                'headline': headline,
                'detail': headline
            })
            if len(events) >= 3:
                break
    except Exception as e:
        logger.warning(f"⚠️ שגיאה בשליפת RSS מאקרו יומי: {e}")

    triggers = [0.25, 0.55, 0.80]
    for idx, ev in enumerate(events):
        ev['progress_trigger'] = triggers[idx]

    return events


def generate_daily_market_recap_ai_content(market_data_summary):
    client = get_gemini_client()

    prompt = f"""
    You are a fast-paced financial video host.
    Generate a 10-15 second ULTRA-FAST market opening for a short-form daily video.

    Daily Returns:
    - S&P 500 (SPY): {market_data_summary['sp500_pct_change']:+.2f}%
    - Nasdaq (QQQ): {market_data_summary['qqq_pct_change']:+.2f}%
    - Bitcoin (BTC): {market_data_summary['btc_pct_change']:+.2f}%

    CRITICAL RULES:
    1. "narration_script": Exactly 10-15 seconds (~25-35 words max). Pure speed! Focus ONLY on index numbers and overall daily market momentum. NO news context.
       - End directly with a high-energy hook: "Let's dive straight into today's top stock movers!"
    2. "youtube_title": High-CTR title | Daily Recap.
    3. "description": Short video description.
    4. "tags": 6-8 tags separated by commas.

    STRICT OUTPUT FORMAT: JSON ONLY
    {{
      "narration_script": "script text",
      "youtube_title": "title",
      "description": "desc",
      "tags": "tags"
    }}
    """

    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return json.loads(response.text)


def render_daily_market_recap_clip(data, audio_path="temp_daily_index_narration.mp3"):
    logger.info("🎨 מנהל את רינדור קליפ המאקרו היומי (מסך מלא)...")
    x_smooth = data['x_smooth']
    spy_pct, qqq_pct, btc_pct = data['spy_pct'], data['qqq_pct'], data['btc_pct']
    spy_p, qqq_p, btc_p = data['spy_prices'], data['qqq_prices'], data['btc_prices']
    num_points = data['total_steps']

    voice_clip = AudioFileClip(audio_path)
    duration = voice_clip.duration

    fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
    canvas = FigureCanvasAgg(fig)
    fig.patch.set_facecolor('#0B0E14')

    # גרף בפריסה רחבה על כל המסך (ללא כרטיסיות חדשות)
    ax = fig.add_axes([0.08, 0.12, 0.88, 0.73])
    ax.set_facecolor('#0B0E14')

    fig.text(0.08, 0.93, "DAILY MARKET RECAP", fontsize=22, fontweight='bold', color='#FFFFFF')
    fig.text(0.08, 0.89, data['date_str'], fontsize=12, fontweight='semibold', color='#8B949E')

    fig.text(0.55, 0.93, "SPY", fontsize=11, fontweight='bold', color='#00FFA3')
    spy_val_text = fig.text(0.55, 0.89, "", fontsize=13, fontweight='bold', color='#00FFA3')

    fig.text(0.70, 0.93, "QQQ", fontsize=11, fontweight='bold', color='#00E5FF')
    qqq_val_text = fig.text(0.70, 0.89, "", fontsize=13, fontweight='bold', color='#00E5FF')

    fig.text(0.85, 0.93, "BTC", fontsize=11, fontweight='bold', color='#FFB800')
    btc_val_text = fig.text(0.85, 0.89, "", fontsize=13, fontweight='bold', color='#FFB800')

    line_spy, = ax.plot([], [], color='#00FFA3', linewidth=3.5, label='SPY')
    line_qqq, = ax.plot([], [], color='#00E5FF', linewidth=2.8, linestyle='--', label='QQQ')
    line_btc, = ax.plot([], [], color='#FFB800', linewidth=2.5, linestyle=':', label='BTC')
    head_spy = ax.scatter([], [], color='#00FFA3', s=120, zorder=10, edgecolors='white', linewidth=1.5)

    ax.set_xlim(-0.02, 1.02)
    y_min = min(np.min(spy_pct), np.min(qqq_pct), np.min(btc_pct)) - 1.0
    y_max = max(np.max(spy_pct), np.max(qqq_pct), np.max(btc_pct)) + 1.5
    ax.set_ylim(y_min, y_max)

    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(['9:30 AM', '11:00 AM', '1:00 PM', '2:30 PM', '4:00 PM Close'], fontsize=11, color='#8B949E')
    ax.set_ylabel("Return (%)", fontsize=11, fontweight='bold', color='#FFFFFF')
    ax.tick_params(axis='both', colors='#8B949E', labelsize=11)
    ax.grid(True, linestyle='--', alpha=0.15, color='#8B949E')

    for spine in ['top', 'right']:
        ax.spines[spine].set_visible(False)
    for spine in ['left', 'bottom']:
        ax.spines[spine].set_color('#30363D')

    def make_frame(t):
        progress = min(t / duration, 1.0)
        curr_idx = max(0, min(int(progress * (num_points - 1)), num_points - 1))

        line_spy.set_data(x_smooth[:curr_idx + 1], spy_pct[:curr_idx + 1])
        line_qqq.set_data(x_smooth[:curr_idx + 1], qqq_pct[:curr_idx + 1])
        line_btc.set_data(x_smooth[:curr_idx + 1], btc_pct[:curr_idx + 1])
        head_spy.set_offsets([[x_smooth[curr_idx], spy_pct[curr_idx]]])

        spy_val_text.set_text(f"${spy_p[curr_idx]:.2f} ({spy_pct[curr_idx]:+.2f}%)")
        spy_val_text.set_color('#00FFA3' if spy_pct[curr_idx] >= 0 else '#FF3366')

        qqq_val_text.set_text(f"${qqq_p[curr_idx]:.2f} ({qqq_pct[curr_idx]:+.2f}%)")
        qqq_val_text.set_color('#00E5FF' if qqq_pct[curr_idx] >= 0 else '#FF3366')

        btc_val_text.set_text(f"${btc_p[curr_idx]:,.0f} ({btc_pct[curr_idx]:+.2f}%)")
        btc_val_text.set_color('#FFB800' if btc_pct[curr_idx] >= 0 else '#FF3366')

        canvas.draw()
        return np.asarray(canvas.buffer_rgba())[:, :, :3]

    clip = VideoClip(make_frame, duration=duration).set_audio(voice_clip)
    return clip, fig


# ---------------------------------------------------------
# 2. סקציית המניות הבודדות - ניתוח יומי (Daily Stocks Breakdown)
# ---------------------------------------------------------
def get_daily_stock_news(ticker):
    try:
        url = f"https://news.google.com/rss/search?q={ticker}+stock+when:1d&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            root = ET.fromstring(response.read())
        items = root.findall('.//item')
        if items:
            title = items[0].find('title').text
            return title.rsplit(" - ", 1)[0] if " - " in title else title
    except Exception as e:
        logger.warning(f"Failed daily RSS news for {ticker}: {e}")
    return None


def select_top_stocks_of_the_day(count=6):
    logger.info(f"🔍 סורק מניות בולטות של היום ({len(STOCK_POOL)} מניות)...")
    results = []

    for ticker in list(set(STOCK_POOL)):
        try:
            top_news = get_daily_stock_news(ticker)
            t = yf.Ticker(ticker)
            hist = t.history(period="1d", interval="5m")
            if len(hist) >= 2:
                start_p, end_p = hist['Close'].iloc[0], hist['Close'].iloc[-1]
                pct_change = abs(((end_p - start_p) / start_p) * 100)
                results.append({
                    'ticker': ticker,
                    'pct_change': pct_change,
                    'is_mega': ticker in MEGA_CAP_POOL,
                    'top_news': top_news or f"{ticker} daily market action"
                })
        except Exception:
            continue

    df_res = pd.DataFrame(results)
    mega_df = df_res[df_res['is_mega']].sort_values(by='pct_change', ascending=False)
    selected_megas = mega_df.head(min(3, count))['ticker'].tolist()

    other_df = df_res[~df_res['ticker'].isin(selected_megas)].sort_values(by='pct_change', ascending=False)
    needed_others = max(0, min(count - len(selected_megas), 7))
    selected_others = other_df.head(needed_others)['ticker'].tolist() if needed_others > 0 else []

    final_selection = selected_megas + selected_others
    logger.info(f"⭐ מניות מובחרות ליום זה: {final_selection}")
    return final_selection


def fetch_daily_stock_full_context(ticker, preloaded_df=None):
    t = yf.Ticker(ticker)
    df_ohlc = preloaded_df if (preloaded_df is not None and not preloaded_df.empty) else t.history(period="1d", interval="5m")

    info, fast_info = {}, {}
    try:
        info = t.info or {}
    except Exception:
        pass
    try:
        fast_info = t.fast_info or {}
    except Exception:
        pass

    company_name = info.get("shortName") or info.get("longName") or ticker

    if not df_ohlc.empty:
        open_price = df_ohlc["Open"].iloc[0]
        current_price = df_ohlc["Close"].iloc[-1]
    else:
        current_price = fast_info.get("lastPrice", 0)
        open_price = fast_info.get("previousClose", current_price)

    pct_change = ((current_price - open_price) / open_price) * 100 if open_price != 0 else 0
    market_cap_str = format_large_number(fast_info.get("market_cap") or info.get("marketCap"))

    target_price = info.get("targetMeanPrice")
    target_price_str = f"${target_price:.2f}" if target_price else "N/A"

    news_headlines = []
    try:
        url = f"https://news.google.com/rss/search?q={ticker}+stock+when:1d&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            root = ET.fromstring(resp.read())
            for item in root.findall(".//item")[:4]:
                title = item.findtext("title") or ""
                news_headlines.append(title.rsplit(" - ", 1)[0] if " - " in title else title)
    except Exception:
        pass

    return {
        "ticker": ticker,
        "company_name": company_name,
        "df_ohlc": df_ohlc,
        "current_price": current_price,
        "pct_change": pct_change,
        "market_cap": market_cap_str,
        "pe": f"{info.get('trailingPE'):.1f}" if info.get("trailingPE") else "N/A",
        "eps": f"${info.get('trailingEps'):.2f}" if info.get("trailingEps") else "N/A",
        "target_price": target_price_str,
        "recommendation": (info.get("recommendationKey") or "N/A").upper(),
        "num_analysts": info.get("numberOfAnalystRecommendations", "N/A"),
        "news_context": "\n".join([f"- {h}" for h in news_headlines] or ["No headline today."]),
    }


def generate_daily_stock_ai_script(stock_data):
    client = get_gemini_client()
    prompt = f"""
    You are a sharp financial commentator creating viral, high-engagement content.
    Stock: {stock_data['company_name']} ({stock_data['ticker']})
    Price: ${stock_data['current_price']:.2f} ({stock_data['pct_change']:+.2f}% today)
    P/E: {stock_data.get('pe', 'N/A')} | Target: {stock_data['target_price']}
    Context:
    {stock_data['news_context']}

    CRITICAL INSTRUCTIONS:
    1. Duration: 15 to 20 seconds (~35-45 words max).
    2. TAKE A BOLD, PROVOCATIVE ANALYTICAL STANCE! Challenge current market sentiment (e.g. "Valuation is completely overblown", "Bulls are ignoring the macro risks", or "Sellers are wildly overreacting here").
    3. STRICT COMPLIANCE: Do NOT give financial advice or explicit buy/sell recommendations (Do NOT say "You should buy/sell", "My advice is to trade"). Keep it strictly analytical/opinionated to spark debate in the comment section!

    STRICT OUTPUT FORMAT: JSON ONLY
    {{
      "script": "Voiceover script text"
    }}
    """

    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return json.loads(response.text)["script"]


def render_single_stock_clip(stock_data, queued_stocks=[], duration=20.0, fps=30):
    ticker = stock_data['ticker']
    df_ohlc = stock_data['df_ohlc']
    num_candles = len(df_ohlc)

    fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
    canvas = FigureCanvasAgg(fig)
    fig.patch.set_facecolor('#0B0E14')

    # --- 1. תצוגת 3 המניות הבאות למעלה (Queue Panel) ---
    queue_box_positions = [[0.05, 0.81, 0.27, 0.15], [0.36, 0.81, 0.27, 0.15], [0.67, 0.81, 0.27, 0.15]]

    for i in range(3):
        box_ax = fig.add_axes(queue_box_positions[i])
        box_ax.set_facecolor('#161B22')
        for spine in box_ax.spines.values():
            spine.set_color('#30363D')
            spine.set_linewidth(1.2)
        box_ax.set_xticks([])
        box_ax.set_yticks([])

        if i < len(queued_stocks):
            q_stock = queued_stocks[i]
            q_df = q_stock['df_ohlc']
            box_ax.text(0.05, 0.78, f"{q_stock['ticker']}", transform=box_ax.transAxes, fontsize=12, fontweight='bold', color='#FFFFFF')

            # ציור מיני-גרף נרות יפניים בתוך התיבה
            if not q_df.empty:
                q_opens, q_closes = q_df['Open'].values, q_df['Close'].values
                q_highs, q_lows = q_df['High'].values, q_df['Low'].values
                q_x = np.arange(len(q_df))
                q_cols = np.where(q_closes >= q_opens, '#00FFA3', '#FF3366')

                mini_chart_ax = fig.add_axes([queue_box_positions[i][0] + 0.10, queue_box_positions[i][1] + 0.02, 0.16, 0.11])
                mini_chart_ax.set_facecolor('#161B22')
                mini_chart_ax.vlines(q_x, q_lows, q_highs, color=q_cols, linewidth=1.0)
                mini_chart_ax.bar(q_x, q_closes - q_opens, bottom=q_opens, color=q_cols, width=0.6)
                mini_chart_ax.axis('off')
        else:
            box_ax.text(0.5, 0.5, " ", transform=box_ax.transAxes, fontsize=10, color='#8B949E', ha='center', va='center')

    # --- 2. פס המדדים והמידע המרכזי (Middle Metric Bar) ---
    pct_color = '#00FFA3' if stock_data['pct_change'] >= 0 else '#FF3366'

    fig.text(0.05, 0.74, stock_data['ticker'], fontsize=22, fontweight='bold', color='#FFFFFF')
    fig.text(0.16, 0.74, f"${stock_data['current_price']:.2f} ({stock_data['pct_change']:+.2f}%)", fontsize=16, fontweight='bold', color=pct_color)

    fig.text(0.42, 0.74, f"EPS: {stock_data.get('eps', 'N/A')}", fontsize=13, fontweight='bold', color='#8B949E')
    fig.text(0.58, 0.74, f"MKT CAP: {stock_data.get('market_cap', 'N/A')}", fontsize=13, fontweight='bold', color='#8B949E')
    fig.text(0.78, 0.74, f"TARGET: {stock_data.get('target_price', 'N/A')}", fontsize=13, fontweight='bold', color='#00E5FF')

    # קו הפרדה עיצובי
    fig.add_artist(Line2D([0.05, 0.95], [0.71, 0.71], color='#30363D', linewidth=1.5))

    # --- 3. גרף נרות יפניים ראשי (Main Candle Chart) ---
    ax = fig.add_axes([0.05, 0.08, 0.90, 0.60])
    ax.set_facecolor('#0B0E14')

    opens = df_ohlc['Open'].values
    closes = df_ohlc['Close'].values
    highs = df_ohlc['High'].values
    lows = df_ohlc['Low'].values
    x_idxs = np.arange(num_candles)
    colors = np.where(closes >= opens, '#00FFA3', '#FF3366')

    y_min_base = df_ohlc['Low'].min() * 0.995
    y_max_base = df_ohlc['High'].max() * 1.005
    current_price = stock_data['current_price']

    def make_frame(t):
        progress = min(t / duration, 1.0)

        ax.clear()
        ax.set_facecolor('#0B0E14')

        x_start = -1 + (num_candles * 0.08 * progress)
        x_end = num_candles - (num_candles * 0.02 * progress)
        ax.set_xlim(x_start, x_end)
        ax.set_ylim(y_min_base, y_max_base)

        ax.set_ylabel("Price ($)", fontsize=10, fontweight='bold', color='#FFFFFF')
        ax.tick_params(axis='y', colors='#FFFFFF', labelsize=10)
        ax.tick_params(axis='x', colors='#8B949E', labelsize=9)
        ax.grid(True, linestyle='--', alpha=0.15, color='#8B949E')

        for spine in ['top', 'right']:
            ax.spines[spine].set_visible(False)
        for spine in ['left', 'bottom']:
            ax.spines[spine].set_color('#30363D')

        ax.vlines(x_idxs, lows, highs, color=colors, linewidth=1.4, alpha=0.9)
        ax.bar(x_idxs, closes - opens, bottom=opens, color=colors, width=0.6, alpha=0.9)

        pulse_alpha = 0.30 + 0.25 * np.sin(2 * np.pi * t * 1.2)
        ax.axhline(y=current_price, color=pct_color, linestyle='--', linewidth=1.2, alpha=pulse_alpha)
        ax.scatter([x_idxs[-1]], [current_price], color=pct_color, s=80, zorder=10, edgecolors='white', linewidth=1.2)

        canvas.draw()
        return np.asarray(canvas.buffer_rgba())[:, :, :3]

    clip = VideoClip(make_frame, duration=duration)
    return clip, fig


def generate_daily_stocks_section_video(stock_tickers, fps=30):
  logger.info(f"🎬 מפיק קליפים יומיים עבור {len(stock_tickers)} מניות...")

  batch_ohlc = None
  try:
    batch_ohlc = yf.download(
        tickers=stock_tickers,
        period="1d",
        interval="5m",
        group_by="ticker",
        progress=False,
        threads=True,
    )
  except Exception as e:
    logger.error(f"Failed daily batch download: {e}")

  all_stocks_data = []
  for ticker in stock_tickers:
    ticker_df = None
    if batch_ohlc is not None:
      if len(stock_tickers) > 1 and ticker in batch_ohlc.columns.levels[0]:
        ticker_df = batch_ohlc[ticker].dropna()
      else:
        ticker_df = batch_ohlc.dropna()

    all_stocks_data.append(
        fetch_daily_stock_full_context(ticker, preloaded_df=ticker_df)
    )

  clips = []
  figs_to_close = []
  temp_files = []

  for idx, stock_data in enumerate(all_stocks_data):
    script = generate_daily_stock_ai_script(stock_data)

    audio_file = f"temp_daily_narration_{stock_data['ticker']}.mp3"
    generate_voiceover_audio(script, output_path=audio_file)
    temp_files.append(audio_file)

    queued_stocks = all_stocks_data[idx + 1 : idx + 4]

    voice_clip = AudioFileClip(audio_file)
    clip, fig = render_single_stock_clip(
        stock_data,
        queued_stocks=queued_stocks,
        duration=voice_clip.duration,
        fps=fps,
    )
    clip = clip.set_audio(voice_clip)

    clips.append(clip)
    figs_to_close.append(fig)

  stocks_clip = concatenate_videoclips(clips)
  return stocks_clip, figs_to_close, temp_files


def render_outro_clip(audio_path="temp_outro_narration.mp3"):
    logger.info("🎬 מפיק מסך סיום (Outro)...")
    outro_script = "Which stock are you watching tomorrow? Let us know in the comments below, and don't forget to like and subscribe for daily market updates!"
    generate_voiceover_audio(outro_script, output_path=audio_path)

    voice_clip = AudioFileClip(audio_path)
    duration = voice_clip.duration

    fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
    canvas = FigureCanvasAgg(fig)
    fig.patch.set_facecolor('#0B0E14')

    fig.text(0.5, 0.60, "WHAT'S YOUR MOVE TOMORROW?", fontsize=28, fontweight='bold', color='#FFFFFF', ha='center')
    fig.text(0.5, 0.48, "Drop your thoughts in the comments below!", fontsize=18, fontweight='bold', color='#00E5FF', ha='center')
    fig.text(0.5, 0.32, "LIKE & SUBSCRIBE FOR DAILY MARKET RECAPS", fontsize=14, fontweight='bold', color='#8B949E', ha='center')

    def make_frame(t):
        canvas.draw()
        return np.asarray(canvas.buffer_rgba())[:, :, :3]

    clip = VideoClip(make_frame, duration=duration).set_audio(voice_clip)
    return clip, fig, audio_path


# ---------------------------------------------------------
# 3. צינור העיבוד היומי המאוחד (Master Daily Execution Pipeline)
# ---------------------------------------------------------
def build_full_daily_video(
    stock_count=6,
    output_filename="daily_market_recap.mp4",
    bg_music_path=None,
    upload=False,
):
  logger.info("🚀 מתחיל ייצור סרטון סיכום יומי מלא...")
  temp_files_to_clean = []
  all_figs_to_close = []

  try:
    # === חלק 1: מאקרו ומדדים יומיים ===
    market_data = fetch_daily_market_data(target_points=1000)
    ai_content = generate_daily_market_recap_ai_content(market_data)

    macro_audio_file = generate_voiceover_audio(
        ai_content["narration_script"],
        output_path="temp_daily_macro_narration.mp3",
    )
    temp_files_to_clean.append(macro_audio_file)

    macro_clip, macro_fig = render_daily_market_recap_clip(
        market_data, audio_path=macro_audio_file
    )
    all_figs_to_close.append(macro_fig)

    # === חלק 2: סקציית המניות ===
    top_stocks = select_top_stocks_of_the_day(count=stock_count)
    stocks_clip, stock_figs, stock_audio_files = (
        generate_daily_stocks_section_video(top_stocks)
    )

    all_figs_to_close.extend(stock_figs)
    temp_files_to_clean.extend(stock_audio_files)

    # === חלק 3: מסך Outro ===
    outro_clip, outro_fig, outro_audio_file = render_outro_clip()
    all_figs_to_close.append(outro_fig)
    temp_files_to_clean.append(outro_audio_file)

    # === חלק 4: איחוד כל הסרטון ===
    logger.info("🔗 משרשר את המאקרו, המניות וה-Outro...")
    final_video_clip = concatenate_videoclips(
        [macro_clip, stocks_clip, outro_clip]
    )

    if bg_music_path and os.path.exists(bg_music_path):
      logger.info("🎵 מוסיף מוזיקת רקע לפרויקט...")
      bg_music = AudioFileClip(bg_music_path)
      bg_music = afx.volumex(bg_music, 0.12)

      if bg_music.duration < final_video_clip.duration:
        bg_music = afx.audio_loop(
            bg_music, duration=final_video_clip.duration
        )
      else:
        bg_music = bg_music.subclip(0, final_video_clip.duration)

      combined_audio = CompositeAudioClip([final_video_clip.audio, bg_music])
      final_video_clip = final_video_clip.set_audio(combined_audio)

    # === חלק 5: רינדור סופי לקובץ ===
    logger.info(f"💾 כותב קובץ וידאו סופי: {output_filename}...")
    final_video_clip.write_videofile(
        output_filename, fps=30, codec="libx264", audio_codec="aac", logger="bar"
    )

    # === חלק 6: יצירת Thumbnail יומי והעלאה ===
    img_path = generate_daily_thumbnail(
        sp500_val=market_data["spy_prices"][-1],
        sp500_pct=market_data["sp500_pct_change"],
        qqq_val=market_data["qqq_prices"][-1],
        qqq_pct=market_data["qqq_pct_change"],
        btc_val=market_data["btc_prices"][-1],
        btc_pct=market_data["btc_pct_change"],
        date_str=market_data.get("date_str"),
        template_path="assets/Thumbnail_Daily.jpg",
        output_path="d_thumbnail.png",
    )
    if upload:
      upload_video(
          output_filename,
          ai_content.get("youtube_title"),
          ai_content.get("description"),
          ai_content.get("tags"),
          thumbnail_path=img_path,
      )

    logger.info("✅ יצירת הסרטון היומי הושלמה בהצלחה!")

  finally:
    logger.info("🧹 מנקה משאבים וקובצי טיוטה...")
    for fig in all_figs_to_close:
      plt.close(fig)

    for temp_file in temp_files_to_clean:
      if os.path.exists(temp_file):
        try:
          os.remove(temp_file)
        except Exception as e:
          logger.warning(f"⚠️ לא ניתן למחוק קובץ זמני {temp_file}: {e}")

  return output_filename

