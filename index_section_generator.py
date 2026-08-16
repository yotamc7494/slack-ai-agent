import sys
import logging
import textwrap
import asyncio
import edge_tts
import numpy as np
import os
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    VideoClip,
    afx,
)
import json
from google import genai
from google.genai import types
import yfinance as yf
from scipy.interpolate import make_interp_spline
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.lines import Line2D
from moviepy.editor import VideoClip, AudioFileClip
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from dotenv import load_dotenv
load_dotenv()

# הגדרת Logger מובנה למעקב אחר תהליכי הרינדור והמערכת
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("VideoEngine")


# ---------------------------------------------------------
# 1. שליפת נתוני מדדים וביטקוין + אינטרפולציה + תאריכים
# ---------------------------------------------------------
def fetch_market_data(target_points=1000):
    """
    שולפת נתוני 5 ימי מסחר עבור SPY, QQQ ו-BTC-USD,
    מחשבת טווח תאריכים דינמי ומבצעת אינטרפולציית Spline.
    """
    print("\n[1/4] 📊 שולף נתוני מסחר מ-yfinance עבור SPY, QQQ ו-BTC-USD...")
    logger.info("Fetching market data...")

    spy = yf.Ticker("SPY")
    qqq = yf.Ticker("QQQ")
    btc = yf.Ticker("BTC-USD")

    df_spy = spy.history(period="5d", interval="1h")
    df_qqq = qqq.history(period="5d", interval="1h")
    df_btc = btc.history(period="5d", interval="1h")

    min_len = min(len(df_spy), len(df_qqq), len(df_btc))
    df_spy = df_spy.iloc[-min_len:]
    df_qqq = df_qqq.iloc[-min_len:]
    df_btc = df_btc.iloc[-min_len:]

    start_date_str = df_spy.index[0].strftime("%b %d, %Y").upper()
    end_date_str = df_spy.index[-1].strftime("%b %d, %Y").upper()
    date_range = f"{start_date_str} - {end_date_str}"
    print(f"   📅 טווח תאריכים שנמצא: {date_range} ({min_len} נקודות דגימה)")

    spy_raw = df_spy['Close'].values
    qqq_raw = df_qqq['Close'].values
    btc_raw = df_btc['Close'].values

    spy_pct_raw = ((spy_raw - spy_raw[0]) / spy_raw[0]) * 100
    qqq_pct_raw = ((qqq_raw - qqq_raw[0]) / qqq_raw[0]) * 100
    btc_pct_raw = ((btc_raw - btc_raw[0]) / btc_raw[0]) * 100

    x_raw = np.linspace(0, 1, min_len)
    x_smooth = np.linspace(0, 1, target_points)

    print(f"   🌀 מבצע אינטרפולציית Spline ל-{target_points} נקודות להחלקה מלאה...")
    spl_spy = make_interp_spline(x_raw, spy_pct_raw, k=3)(x_smooth)
    spl_qqq = make_interp_spline(x_raw, qqq_pct_raw, k=3)(x_smooth)
    spl_btc = make_interp_spline(x_raw, btc_pct_raw, k=3)(x_smooth)

    spl_spy_p = make_interp_spline(x_raw, spy_raw, k=3)(x_smooth)
    spl_qqq_p = make_interp_spline(x_raw, qqq_raw, k=3)(x_smooth)
    spl_btc_p = make_interp_spline(x_raw, btc_raw, k=3)(x_smooth)

    print("   ✅ שליפת הנתונים והאינטרפולציה הושלמו בהצלחה.")
    return {
        'x_smooth': x_smooth,
        'spy_pct': spl_spy,
        'qqq_pct': spl_qqq,
        'btc_pct': spl_btc,
        'spy_prices': spl_spy_p,
        'qqq_prices': spl_qqq_p,
        'btc_prices': spl_btc_p,
        'date_range': date_range,
        'total_steps': target_points
    }


# ---------------------------------------------------------
# 2. שליפת חדשות מאקרו ואירועים בזמן אמת
# ---------------------------------------------------------
def get_macro_news_events():
    """
    שולפת חדשות מאקרו כלליות של השוק מהשבוע האחרון (אינפלציה, ריבית, הפד, כלכלה)
    בשימוש ב-Standard Library ללא התקנת ספריות נוספות.
    """
    print("\n[2/4] 📰 שולף חדשות מאקרו שבועיות כלליות מה-7 ימים האחרונים...")
    logger.info("Fetching weekly macro market news via Google News RSS...")

    # שאילתת חיפוש לחדשות מאקרו וכלכלה
    query = "US+economy+Fed+inflation+stock+market"
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)
    events = []

    try:
        req = urllib.request.Request(rss_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            xml_data = response.read()

        root = ET.fromstring(xml_data)
        for item in root.findall('.//item'):
            pub_date_str = item.findtext('pubDate')
            title = item.findtext('title') or ''

            # סינון: רק ידיעות מ-7 הימים האחרונים
            if pub_date_str:
                pub_date = parsedate_to_datetime(pub_date_str)
                if pub_date < cutoff_date:
                    continue

            # הפרדת שם הגוף המפרסם מהכותרת ("Headline - Publisher")
            publisher = "MACRO NEWS"
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
        print(f"   ⚠️ שגיאה בשליפת ה-RSS ({e}), עובר לברירת מחדל.")

    triggers = [0.25, 0.55, 0.80]
    for idx, ev in enumerate(events):
        ev['progress_trigger'] = triggers[idx]
        print(f"   📌 אירוע מאקרו {idx + 1}: [{ev['tag']}] - {ev['headline'][:35]}...")

    print("   ✅ הכנת אירועי המאקרו הושלמה.")
    return events


def generate_market_recap_ai_content(market_data_summary, news_events):
    """
    מייצרת באמצעות Gemini סקריפט קריינות ל-30 שניות ומטא-דאטה מותאמת
    על בסיס נתוני השוק וידיעות החדשות ששלפנו.
    """
    # 1. שליפת API Key מ-env או Streamlit Secrets
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

    # 2. פירסור 3 הידיעות עבור הפרומפט
    news_text_formatted = ""
    for idx, ev in enumerate(news_events, 1):
        news_text_formatted += f"Event {idx} [{ev['tag']}]: {ev['headline']} - {ev['detail']}\n"

    # 3. הגדרת הפרומפט ל-Gemini
    prompt = f"""
    You are a professional financial news host for viral short-form videos (TikTok, Shorts, Reels).
    Generate a 30-second high-energy voiceover script and social media metadata for a weekly market recap video.

    Weekly Market Context:
    - Tracked Assets: SPY, QQQ, Bitcoin (BTC)
    - Date Range: {market_data_summary.get('date_range', 'This Week')}

    Top 3 Macro News Events of the Week:
    {news_text_formatted}

    CRITICAL RULES:
    1. "narration_script": A punchy, fast-paced voiceover script EXACTLY designed for 30 SECONDS of speech (~65 to 75 words maximum). It MUST seamlessly cover the 3 news events in chronological order while mentioning the market momentum (SPY, QQQ, BTC). 
       - CRITICAL ENDING: The script MUST end with a smooth, high-energy transition line teasing the individual stock chart breakdowns coming up next in the video (e.g., "Now, let's take a look at how top individual stocks performed!", "Stay tuned, because next we're diving into this week's biggest stock movers!").
    2. "youtube_title": Clickbait-y, high-CTR YouTube Shorts / Reels title with emojis But clear that says its a weekly summery.
    3. "description": Engaging summary ending with a question about top stocks/market trends to boost comments.
    4. "tags": 6-8 comma-separated tags without spaces after commas (e.g., Stocks,SPY,QQQ,Bitcoin,Crypto,Finance,Investing,Fed).

    STRICT OUTPUT FORMAT:
    Return ONLY a valid JSON object with the following fields:
    {{
      "narration_script": "30-second voiceover script ending with a transition to upcoming stocks (65-75 words)",
      "youtube_title": "High-CTR title with emojis starting with the exact phrase [Weekly Market Recap]",
      "description": "Short summary ending with a question",
      "tags": "tag1,tag2,tag3,tag4"
    }}
    """

    print("🤖 מייצר סקריפט קריינות ל-30 שניות ומטא-דאטה בעזרת Gemini AI...")

    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    result = json.loads(response.text)

    print(f"   📜 סקריפט נוצר ({len(result['narration_script'].split())} מילים):")
    print(f"      \"{result['narration_script']}\"")

    return result


# ---------------------------------------------------------
# 3. מנוע הרינדור On-The-Fly ב-RAM
# ---------------------------------------------------------
def generate_market_video(
    data,
    news_events,
    audio_path="index_narration.mp3",
    default_duration=45.0,
):
    print("\n[3/4] 🎨 מכין את אלמנטים הויזואליים בזיכרון RAM...")
    logger.info("Initializing RAM Canvas and rendering elements...")

    x_smooth = data['x_smooth']
    spy_pct, qqq_pct, btc_pct = data['spy_pct'], data['qqq_pct'], data['btc_pct']
    spy_p, qqq_p, btc_p = data['spy_prices'], data['qqq_prices'], data['btc_prices']
    num_points = data['total_steps']

    # הגדרת אורך הסרטון מול קובץ האודיו

    voice_clip = AudioFileClip(audio_path)
    duration = voice_clip.duration

    if os.path.exists(audio_path):
        final_audio = voice_clip
    else:
        duration = default_duration
        print(f"   ⚠️ לא נמצא קובץ קריינות, אורך ברירת מחדל: {duration:.1f}s")

    fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
    canvas = FigureCanvasAgg(fig)
    fig.patch.set_facecolor('#0B0E14')

    # מערכת הצירים תופסת כ-67% מימין (פינוי 28% משמאל עבור פאנל החדשות)
    ax = fig.add_axes([0.28, 0.12, 0.67, 0.72])
    ax.set_facecolor('#0B0E14')

    # --- כותרות וטווח תאריכים ---
    fig.text(0.03, 0.93, "WEEKLY MARKET RECAP", fontsize=20, fontweight='bold', color='#FFFFFF')
    fig.text(0.03, 0.90, data['date_range'], fontsize=11, fontweight='semibold', color='#8B949E')

    # כרטיסיות מדדים עליונות
    fig.text(0.48, 0.93, "SPY", fontsize=11, fontweight='bold', color='#00FFA3')
    spy_val_text = fig.text(0.48, 0.90, "", fontsize=13, fontweight='bold', color='#00FFA3')

    fig.text(0.65, 0.93, "QQQ", fontsize=11, fontweight='bold', color='#00E5FF')
    qqq_val_text = fig.text(0.65, 0.90, "", fontsize=13, fontweight='bold', color='#00E5FF')

    fig.text(0.82, 0.93, "BTC", fontsize=11, fontweight='bold', color='#FFB800')
    btc_val_text = fig.text(0.82, 0.90, "", fontsize=13, fontweight='bold', color='#FFB800')

    # --- פאנל חדשות שמאלי (מידות קבועות ב-RAM לכל כרטיסייה) ---
    news_box_y_positions = [0.72, 0.48, 0.24]
    card_elements = []

    # מידות קבועות באחוזים מכלל המסך (Figure Coordinates)
    CARD_LEFT = 0.03
    CARD_WIDTH = 0.20  # רוחב קבוע (22% מרוחב המסך, מסתיים ב-0.25)
    CARD_HEIGHT = 0.16  # גובה קבוע לבלוק

    for i, ev in enumerate(news_events):
        y_pos = news_box_y_positions[i]

        # 1. יצירת ציר (Axes) בגודל ומיקום קבועים מראש
        card_ax = fig.add_axes([
            CARD_LEFT,
            y_pos - (CARD_HEIGHT / 2),
            CARD_WIDTH,
            CARD_HEIGHT
        ], zorder=25)

        card_ax.set_facecolor('#161B22')

        # 2. עיצוב המסגרת של הכרטיסייה
        for spine in card_ax.spines.values():
            spine.set_color('#FF3366')
            spine.set_linewidth(1.8)

        card_ax.set_xticks([])
        card_ax.set_yticks([])

        # 3. פורמט הטקסט והכנסתו בתוך ה-Axes הקבוע
        wrapped_headline = textwrap.fill(ev['headline'], width=38)
        wrapped_detail = textwrap.fill(ev['detail'], width=40)
        divider_line = "─" * 24

        formatted_text = (
            f"[{ev['tag']}]\n"
            f"{wrapped_headline}\n"
            f"{divider_line}\n"
            f"• {wrapped_detail}"
        )

        card_ax.text(
            0.05, 0.5,
            formatted_text,
            transform=card_ax.transAxes,
            fontsize=8.5, fontweight='bold', color='#FFFFFF',
            va='center', ha='left'
        )

        # הסתרה התחלתית עד סיום הנפשת הקו
        card_ax.set_visible(False)

        card_elements.append({
            'trigger': ev['progress_trigger'],
            'bbox': card_ax,
            'event': ev,
            'target_y_fig': y_pos
        })

    # אתחול קווי הגרף
    line_spy, = ax.plot([], [], color='#00FFA3', linewidth=3.0, label='SPY')
    line_qqq, = ax.plot([], [], color='#00E5FF', linewidth=2.2, linestyle='--', label='QQQ')
    line_btc, = ax.plot([], [], color='#FFB800', linewidth=2.0, linestyle=':', label='BTC')

    head_spy = ax.scatter([], [], color='#00FFA3', s=100, zorder=10, edgecolors='white', linewidth=1.5)

    # אתחול קווי חיבור מעודנים (שקופים, מתחת לכרטיסייה)
    connector_lines = []
    for card in card_elements:
        line_conn = Line2D([], [], color='#FF3366', linewidth=2.0, alpha=0.55, zorder=15)
        fig.add_artist(line_conn)

        sc = ax.scatter([], [], color='#FF3366', s=120, zorder=12, edgecolors='white', linewidth=1.5)
        sc.set_visible(False)

        connector_lines.append({
            'trigger': card['trigger'],
            'line': line_conn,
            'scatter': sc,
            'target_y_fig': card['target_y_fig'],
            'card_bbox': card['bbox']
        })

    # --- הגדרת צירים ותוויות RETURN בלבן ---
    ax.set_xlim(-0.02, 1.02)
    y_min = min(np.min(spy_pct), np.min(qqq_pct), np.min(btc_pct)) - 2.0
    y_max = max(np.max(spy_pct), np.max(qqq_pct), np.max(btc_pct)) + 3.0
    ax.set_ylim(y_min, y_max)

    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(['Mon', 'Tue', 'Wed', 'Thu', 'Fri Close'], fontsize=10, color='#8B949E')

    # תוויות ה-Return בציר ה-Y בלבן בולט (#FFFFFF)
    ax.set_ylabel("Return (%)", fontsize=10, fontweight='bold', color='#FFFFFF')
    ax.tick_params(axis='y', colors='#FFFFFF', labelsize=10)
    ax.tick_params(axis='x', colors='#8B949E', labelsize=10)

    ax.grid(True, linestyle='--', alpha=0.15, color='#8B949E')

    for spine in ['top', 'right']:
        ax.spines[spine].set_visible(False)
    for spine in ['left', 'bottom']:
        ax.spines[spine].set_color('#30363D')

    print("\n[4/4] 🎬 מתחיל רינדור וידאו ישיר ב-RAM (מזרים ל-FFmpeg)...")
    logger.info("Starting MoviePy rendering loop...")

    # --- פונקציית make_frame On-The-Fly ---
    def make_frame(t):
        progress = min(t / duration, 1.0)
        curr_idx = int(progress * (num_points - 1))
        curr_idx = max(0, min(curr_idx, num_points - 1))

        # 1. עדכון נתוני הקווים בזיכרון
        line_spy.set_data(x_smooth[:curr_idx + 1], spy_pct[:curr_idx + 1])
        line_qqq.set_data(x_smooth[:curr_idx + 1], qqq_pct[:curr_idx + 1])
        line_btc.set_data(x_smooth[:curr_idx + 1], btc_pct[:curr_idx + 1])

        # 2. עדכון ראש הקו
        head_spy.set_offsets([[x_smooth[curr_idx], spy_pct[curr_idx]]])

        # 3. עדכון כרטיסיות נתונים עליונות
        spy_val_text.set_text(f"${spy_p[curr_idx]:.2f} ({spy_pct[curr_idx]:+.2f}%)")
        spy_val_text.set_color('#00FFA3' if spy_pct[curr_idx] >= 0 else '#FF3366')

        qqq_val_text.set_text(f"${qqq_p[curr_idx]:.2f} ({qqq_pct[curr_idx]:+.2f}%)")
        qqq_val_text.set_color('#00E5FF' if qqq_pct[curr_idx] >= 0 else '#FF3366')

        btc_val_text.set_text(f"${btc_p[curr_idx]:,.0f} ({btc_pct[curr_idx]:+.2f}%)")
        btc_val_text.set_color('#FFB800' if btc_pct[curr_idx] >= 0 else '#FF3366')

        # 4. הנפשת הקו (Vertical-First) ועצירה בדופן הימנית של הכרטיסייה הקבועה
        for conn in connector_lines:
            trig = conn['trigger']
            if progress >= trig:
                idx = int(trig * (num_points - 1))
                ev_x_data = x_smooth[idx]
                ev_y_data = spy_pct[idx]

                conn['scatter'].set_offsets([[ev_x_data, ev_y_data]])
                conn['scatter'].set_visible(True)

                # המרת קואורדינטות Data (ax) ל-Figure (fig)
                display_pt = ax.transData.transform((ev_x_data, ev_y_data))
                fig_pt = fig.transFigure.inverted().transform(display_pt)
                start_x_fig, start_y_fig = fig_pt[0], fig_pt[1]

                # נקודת סיום מדויקת בחיבור לדופן הימנית הקבועה של הכרטיסייה (0.25)
                target_x_fig = CARD_LEFT + CARD_WIDTH
                target_y_fig = conn['target_y_fig']

                anim_duration = 0.05
                line_anim_progress = min((progress - trig) / anim_duration, 1.0)

                len_v = abs(target_y_fig - start_y_fig)
                len_h = abs(target_x_fig - start_x_fig)
                total_len = len_v + len_h

                frac_v = len_v / total_len if total_len > 0 else 0.5

                if line_anim_progress <= frac_v:
                    sub_p = line_anim_progress / frac_v if frac_v > 0 else 1.0
                    curr_y = start_y_fig + (target_y_fig - start_y_fig) * sub_p
                    curr_path_x = [start_x_fig, start_x_fig]
                    curr_path_y = [start_y_fig, curr_y]
                else:
                    sub_p = (line_anim_progress - frac_v) / (1.0 - frac_v) if frac_v < 1.0 else 1.0
                    curr_x = start_x_fig + (target_x_fig - start_x_fig) * sub_p
                    curr_path_x = [start_x_fig, start_x_fig, curr_x]
                    curr_path_y = [start_y_fig, target_y_fig, target_y_fig]

                conn['line'].set_data(curr_path_x, curr_path_y)

                # הכרטיסייה מופיעה רק בסיום ההנפשה של הקו
                if line_anim_progress >= 1.0:
                    conn['card_bbox'].set_visible(True)
                else:
                    conn['card_bbox'].set_visible(False)

        canvas.draw()
        return np.asarray(canvas.buffer_rgba())[:, :, :3]

    clip = VideoClip(make_frame, duration=duration)
    # הזרמה ישירה ל-MoviePy
    if final_audio:
        clip = clip.set_audio(final_audio)

        # כתיבה ל-MP4
    return clip


def generate_voiceover_audio(
    script_text,
    output_path="index_narration.mp3",
    voice="en-GB-RyanNeural",
    rate="+15%",
):
  """מייצרת קובץ קריינות (.mp3) באמצעות edge-tts עם קול ותדר דיבור מותאמים."""
  print(
      f"\n[3.5/4] 🎙️ מייצר קריינות קולית ב-edge-tts ({voice}, קצב:"
      f" {rate})..."
  )
  logger.info("Generating edge-tts voiceover...")

  async def _save_audio():
    communicate = edge_tts.Communicate(script_text, voice, rate=rate)
    await communicate.save(output_path)

  # הרצת המשימה האסינכרונית
  asyncio.run(_save_audio())

  print(f"   ✅ קובץ הקריינות נשמר בהצלחה ב: {output_path}")
  return output_path


# ---------------------------------------------------------
# הרצה ראשית
# ---------------------------------------------------------
if __name__ == "__main__":
    market_data = fetch_market_data(target_points=1000)
    news = get_macro_news_events()
    ai_content = generate_market_recap_ai_content(market_data, news)
    narration_script = ai_content["narration_script"]
    youtube_title = ai_content["youtube_title"]

    # 4. יצירת קובץ ה-Voiceover באודיו (.mp3)
    audio_file = generate_voiceover_audio(narration_script, output_path="index_narration.mp3")
    generate_market_video(
        market_data,
        news,
        audio_path=audio_file,  # הקריינות שיצרנו עם edge-tts
        bg_music_path="assets/weekly_recup_music.mp3",  # הקובץ של מוזיקת הרקע שלך
        output_video=f"{youtube_title}.mp4",
        aspect_ratio="16:9",
    )