import os
import sys
import logging
import urllib.request
import xml.etree.ElementTree as ET
import json
from google import genai
from google.genai import types
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.editor import VideoClip, concatenate_videoclips
from numpy import random

from index_section_generator import generate_voiceover_audio


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("StockEngine")

# ---------------------------------------------------------
# POOL של כ-50 מניות מובילות
# ---------------------------------------------------------
MEGA_CAP_POOL = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA"]

STOCK_POOL = [
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA",
    "AMD", "PLTR", "INTC", "NFLX", "DIS", "COIN", "MSTR", "ARM",
    "SMCI", "LLY", "NKE", "PYPL", "SHOP", "BABA", "BA", "AVGO",
    "ORCL", "CRM", "AMD", "QCOM", "JPM", "V", "MA", "UNH",
    "XOM", "CVX", "BAC", "WMT", "COST", "HD", "PG", "JNJ",
    "PFE", "ABBV", "MRK", "NOW", "UBER", "ABNB", "HOOD"
]


# ---------------------------------------------------------
# 1. פונקציית עזר להמרת מספרים גדולים (Market Cap)
# ---------------------------------------------------------
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


# ---------------------------------------------------------
# 2. סינון ובחירת 5-10 המניות המעניינות של השבוע
# ---------------------------------------------------------
def select_top_stocks_of_the_week(count=6):
    print(f"\n[1/3] 🔍 סורק את Pool המניות ({len(STOCK_POOL)} מניות)...")
    logger.info("Scanning stock pool for weekly highlights...")

    results = []

    for ticker in list(set(STOCK_POOL)):
        try:
            # 1. שליפת חדשות דרך Google News RSS
            top_news = get_stock_news(ticker)
            if not top_news:
                continue  # דילוג על מנייה ללא חדשות

            t = yf.Ticker(ticker)
            hist = t.history(period="5d", interval="1d")
            if len(hist) >= 2:
                start_price = hist['Close'].iloc[0]
                end_price = hist['Close'].iloc[-1]
                pct_change = abs(((end_price - start_price) / start_price) * 100)
                results.append({
                    'ticker': ticker,
                    'pct_change': pct_change,
                    'is_mega': ticker in MEGA_CAP_POOL,
                    'top_news': top_news
                })
        except Exception:
            continue

    df_res = pd.DataFrame(results)

    # 2. סינון לפי כמות מניות מבוקשת (count)
    mega_df = df_res[df_res['is_mega']].sort_values(by='pct_change', ascending=False)
    selected_megas = mega_df.head(min(3, count))['ticker'].tolist()

    other_df = df_res[~df_res['ticker'].isin(selected_megas)].sort_values(by='pct_change', ascending=False)
    needed_others = max(0, min(count - len(selected_megas), 7))
    if needed_others > 0:
        selected_others = other_df.head(needed_others)['ticker'].tolist()
    else:
        selected_others = []

    final_selection = selected_megas + selected_others
    print(f"   ⭐ מניות Mega-Cap שנבחרו ({len(selected_megas)}): {selected_megas}")
    print(f"   🔥 מניות נוספות שנבחרו ({len(selected_others)}): {selected_others}")

    return final_selection

# ---------------------------------------------------------
# 3. שליפת נתוני נרות, מדדים וחדשות עבור מנייה יחידה
# ---------------------------------------------------------


def fetch_stock_full_context(ticker):
  """שולפת נתוני נרות, מדדים פונדמנטליים, ציפיות אנליסטים וחדשות עבור ה-AI."""
  t = yf.Ticker(ticker)

  # 1. נתוני נרות שעתיים (5 ימי מסחר)
  df_ohlc = t.history(period="5d", interval="1h")

  # 2. נתונים פונדמנטליים ודירוגי אנליסטים
  info = t.info or {}
  company_name = info.get("shortName") or info.get("longName") or ticker

  open_price = df_ohlc["Open"].iloc[0]
  current_price = df_ohlc["Close"].iloc[-1]
  pct_change = ((current_price - open_price) / open_price) * 100

  # נתוני אנליסטים וציפיות שוק
  target_price = info.get("targetMeanPrice")
  target_price_str = f"${target_price:.2f}" if target_price else "N/A"
  recommendation = (info.get("recommendationKey") or "N/A").upper()
  num_analysts = info.get("numberOfAnalystRecommendations", "N/A")

  # 3. איסוף חדשות מ-Google News RSS עבור הקשר ה-AI
  news_headlines = []
  try:
    url = f"https://news.google.com/rss/search?q={ticker}+stock+when:7d&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=5) as resp:
      root = ET.fromstring(resp.read())
      for item in root.findall(".//item")[:4]:
        title = item.findtext("title") or ""
        if " - " in title:
          title = title.rsplit(" - ", 1)[0]
        news_headlines.append(title)
  except Exception as e:
    logger.warning(f"Failed pulling RSS news for {ticker}: {e}")

  return {
      "ticker": ticker,
      "company_name": company_name,
      "df_ohlc": df_ohlc,
      "current_price": current_price,
      "pct_change": pct_change,
      "market_cap": format_large_number(info.get("marketCap")),
      "pe": f"{info.get('trailingPE'):.1f}" if info.get("trailingPE") else "N/A",
      "eps": (
          f"${info.get('trailingEps'):.2f}"
          if info.get("trailingEps")
          else "N/A"
      ),
      "target_price": target_price_str,
      "recommendation": recommendation,
      "num_analysts": num_analysts,
      "news_context": "\n".join(
          [f"- {h}" for h in news_headlines]
          or ["No specific headline found."]
      ),
  }


def get_stock_news(ticker):
    """
    שולפת את הכותרת החדשותית הכי חמה ורלוונטית מהשבוע האחרון מ-Google News RSS.
    """
    try:
        # שאילתת חיפוש ממוקדת מנייה מ-7 הימים האחרונים
        url = f"https://news.google.com/rss/search?q={ticker}+stock+when:7d&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})

        with urllib.request.urlopen(req, timeout=5) as response:
            xml_data = response.read()

        root = ET.fromstring(xml_data)
        items = root.findall('.//item')

        if items:
            title = items[0].find('title').text
            if " - " in title:
                title = title.rsplit(" - ", 1)[0]
            return title
    except Exception as e:
        logger.warning(f"Failed fetching RSS news for {ticker}: {e}")

    return None


def generate_stock_ai_script(stock_data):
  """מייצרת סקריפט ממוקד ואינפורמטיבי (15-25 שניות) על המנייה, סיבת התנועה וציפיות האנליסטים."""
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
    You are a senior equity analyst delivering an informative, 15 to 25 second stock breakdown for a short-form video.
    NO CLICKBAIT. Be objective, analytical, and directly explain the movement and market perspective.

    Stock Details:
    - Company: {stock_data['company_name']} ({stock_data['ticker']})
    - Current Price: ${stock_data['current_price']:.2f} ({stock_data['pct_change']:+.2f}% this week)
    - Wall St Consensus Target Price: {stock_data['target_price']} (Consensus: {stock_data['recommendation']} from {stock_data['num_analysts']} analysts)
    - Key News Context from past week:
    {stock_data['news_context']}

    CRITICAL SCRIPT RULES:
    1. Duration: EXACTLY 15 to 25 seconds of speech (~35 to 50 words maximum).
    2. Structure: 
       - Line 1: State what happened to {stock_data['ticker']} this week and why (based on the news context).
       - Line 2: Mention consensus price targets and what analysts expect.
       - Line 3: Provide an objective takeaway (e.g. "Is this a temporary dip-buying opportunity or is caution warranted?").
    3. Tone: Financial news anchor tone (like Bloomberg or CNBC). Sharp, informative, data-driven.

    STRICT OUTPUT FORMAT:
    Return ONLY a valid JSON object:
    {{
      "script": "The 15-25 second voiceover script text here"
    }}
    """

  print(f"🤖 מייצר סקריפט AI מידעני עבור {stock_data['ticker']}...")

  response = client.models.generate_content(
      model="gemini-flash-lite-latest",
      contents=prompt,
      config=types.GenerateContentConfig(response_mime_type="application/json"),
  )

  result = json.loads(response.text)
  print(f"   📜 סקריפט נוצר ({len(result['script'].split())} מילים):")
  print(f"      \"{result['script']}\"")

  return result["script"]


# ---------------------------------------------------------
# 4. מנוע רינדור עבור קליפ מנייה יחידה (~20 שניות)
# ---------------------------------------------------------
def render_single_stock_clip(stock_data, duration=20.0, fps=30):
    ticker = stock_data['ticker']
    df_ohlc = stock_data['df_ohlc']
    num_candles = len(df_ohlc)

    fig = plt.figure(figsize=(16, 9), dpi=100)
    canvas = FigureCanvasAgg(fig)
    fig.patch.set_facecolor('#0B0E14')

    ax = fig.add_axes([0.05, 0.08, 0.90, 0.76])
    ax.set_facecolor('#0B0E14')

    pct_color = '#00FFA3' if stock_data['pct_change'] >= 0 else '#FF3366'

    # --- BANNER עליון ---
    fig.text(0.05, 0.93, f"{stock_data['company_name']} ({ticker})", fontsize=18, fontweight='bold', color='#FFFFFF')
    fig.text(0.05, 0.89, f"${stock_data['current_price']:.2f}  ({stock_data['pct_change']:+.2f}%)", fontsize=15, fontweight='bold', color=pct_color)

    fig.text(0.38, 0.93, "MARKET CAP", fontsize=9, color='#8B949E')
    fig.text(0.38, 0.89, stock_data.get('market_cap', 'N/A'), fontsize=12, fontweight='bold', color='#FFFFFF')

    fig.text(0.50, 0.93, "P/E RATIO", fontsize=9, color='#8B949E')
    fig.text(0.50, 0.89, stock_data.get('pe', 'N/A'), fontsize=12, fontweight='bold', color='#FFFFFF')

    fig.text(0.61, 0.93, "EPS (TTM)", fontsize=9, color='#8B949E')
    fig.text(0.61, 0.89, stock_data.get('eps', 'N/A'), fontsize=12, fontweight='bold', color='#FFFFFF')

    target_val = stock_data.get('target_price', stock_data.get('range_52', 'N/A'))
    target_label = "ANALYST TARGET" if 'target_price' in stock_data else "52W RANGE"
    fig.text(0.72, 0.93, target_label, fontsize=9, color='#8B949E')
    fig.text(0.72, 0.89, target_val, fontsize=12, fontweight='bold', color='#00E5FF' if 'target_price' in stock_data else '#FFFFFF')

    if 'recommendation' in stock_data:
        fig.text(0.85, 0.93, "RATING", fontsize=9, color='#8B949E')
        fig.text(0.85, 0.89, stock_data['recommendation'], fontsize=12, fontweight='bold', color='#FFB800')

    # נתוני נרות קבועים
    opens = df_ohlc['Open'].values
    closes = df_ohlc['Close'].values
    highs = df_ohlc['High'].values
    lows = df_ohlc['Low'].values
    x_idxs = np.arange(num_candles)
    colors = np.where(closes >= opens, '#00FFA3', '#FF3366')

    y_min_base = df_ohlc['Low'].min() * 0.995
    y_max_base = df_ohlc['High'].max() * 1.005
    current_price = stock_data['current_price']

    # --- פונקציית make_frame דינמית ---
    def make_frame(t):
        progress = min(t / duration, 1.0)

        ax.clear()
        ax.set_facecolor('#0B0E14')

        # 1. תנועת מצלמה מעודנת (Slow Zoom/Pan): התקרבות עדינה של 8% לעבר הנרות האחרונים
        x_start = -1 + (num_candles * 0.08 * progress)
        x_end = num_candles - (num_candles * 0.02 * progress)
        ax.set_xlim(x_start, x_end)
        ax.set_ylim(y_min_base, y_max_base)

        # 2. עיצוב צירים וגריד
        ax.set_ylabel("Price ($)", fontsize=10, fontweight='bold', color='#FFFFFF')
        ax.tick_params(axis='y', colors='#FFFFFF', labelsize=10)
        ax.tick_params(axis='x', colors='#8B949E', labelsize=9)
        ax.grid(True, linestyle='--', alpha=0.15, color='#8B949E')

        for spine in ['top', 'right']:
            ax.spines[spine].set_visible(False)
        for spine in ['left', 'bottom']:
            ax.spines[spine].set_color('#30363D')

        # 3. ציור נרות
        ax.vlines(x_idxs, lows, highs, color=colors, linewidth=1.4, alpha=0.9)
        ax.bar(x_idxs, closes - opens, bottom=opens, color=colors, width=0.6, alpha=0.9)

        # 4. קו מחיר נוכחי פועם (Live Pulsing Price Line)
        pulse_alpha = 0.30 + 0.25 * np.sin(2 * np.pi * t * 1.2)  # פעימה חלקה מ-0.30 ל-0.55
        ax.axhline(y=current_price, color=pct_color, linestyle='--', linewidth=1.2, alpha=pulse_alpha)

        # נקודת לייב זוהרת בנר האחרון
        ax.scatter([x_idxs[-1]], [current_price], color=pct_color, s=80, zorder=10, edgecolors='white', linewidth=1.2)

        canvas.draw()
        return np.asarray(canvas.buffer_rgba())[:, :, :3]

    clip = VideoClip(make_frame, duration=duration)
    return clip, fig


# ---------------------------------------------------------
# 5. יצירת סקציית המניות המלאה
# ---------------------------------------------------------
def generate_stocks_section_video(stock_tickers, duration_per_stock=20.0, fps=30):
    print(f"\n[2/3] 🎬 מפיק קליפים עבור {len(stock_tickers)} מניות ({duration_per_stock}s למנייה)...")
    logger.info("Generating stock breakdown clips...")

    clips = []
    figs_to_close = []
    first = True
    for idx, ticker in enumerate(stock_tickers, 1):
        print(f"   [{idx}/{len(stock_tickers)}] מעבד נתונים וגרף נרות עבור {ticker}...")
        stock_data = fetch_stock_full_context(ticker)
        script = generate_stock_ai_script(stock_data)
        if first:
            first = False
        else:
            script = random.choice(["Next ", "For the Next Stock ", "To Our Next Topic "])+script
        audio_file = generate_voiceover_audio(
            script,
            output_path=f"narration_{stock_data['ticker']}.mp3",
            voice="en-GB-RyanNeural",
            rate="+10%",
        )
        voice_clip = AudioFileClip(audio_file)
        clip, fig = render_single_stock_clip(
            stock_data, duration=voice_clip.duration, fps=30
        )
        clip = clip.set_audio(voice_clip)
        clips.append(clip)
        figs_to_close.append(fig)

    # שרשור כל קליפי המניות לרצף אחד רציף
    final_stocks_clip = concatenate_videoclips(clips)

    print("   ✅ ייצור סקציית המניות הושלם בהצלחה ב-RAM!")
    return final_stocks_clip, figs_to_close


# ---------------------------------------------------------
# הרצה ראשית לבדיקת סקציית המניות
# ---------------------------------------------------------
if __name__ == "__main__":
    top_stocks = select_top_stocks_of_the_week(count=6)
    stocks_clip, figs = generate_stocks_section_video(top_stocks, duration_per_stock=20.0, fps=30)
    output_filename = "stocks_breakdown_section.mp4"
    stocks_clip.write_videofile(
        output_filename,
        fps=30,
        codec='libx264',
        logger='bar'
    )
    for ticker in top_stocks:
        temp_audio = f"narration_{ticker}.mp3"
        if os.path.exists(temp_audio):
            try:
                os.remove(temp_audio)
            except Exception as e:
                print(f"   ⚠️ שגיאה במחיקת {temp_audio}: {e}")
    # ניקוי משאבים
    for fig in figs:
        plt.close(fig)
    stocks_clip.close()

    print(f"\n🚀 סקציית המניות נשמרה ב: {output_filename}")