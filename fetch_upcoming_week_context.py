import datetime
import json
import logging
import os
import urllib.request
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from google import genai
from google.genai import types
import matplotlib.patches as patches
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.editor import VideoClip, concatenate_videoclips
import numpy as np

load_dotenv()

logger = logging.getLogger("UpcomingWeekEngine")


# ---------------------------------------------------------
# 1. שליפת מדד Fear & Greed מ-CNN
# ---------------------------------------------------------
logger = logging.getLogger(__name__)


def get_fear_and_greed_index():
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.cnn.com/markets/fear-and-greed"
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

            # בדיקת קיום המפתחות במילון
            fg_data = data.get("fear_and_greed", {})
            score = round(fg_data.get("score", 50))
            rating = fg_data.get("rating", "NEUTRAL").upper()

            return {"score": score, "rating": rating}

    except Exception as e:
        logger.warning(f"Could not fetch Fear & Greed: {e}")
        return {"score": 50, "rating": "NEUTRAL"}


# ---------------------------------------------------------
# 2. שליפת אירועי מאקרו שבועיים
# ---------------------------------------------------------
def fetch_upcoming_macro_events():
  today = datetime.date.today()
  start_of_week = today + datetime.timedelta(days=(0 - today.weekday()) % 7)

  macro_keywords = [
      ("CPI", 2, "US CPI Inflation Release"),
      ("Rate", 3, "Fed Interest Rate Decision"),
      ("Payrolls", 4, "US Jobs / Payrolls Report"),
      ("Retail", 1, "US Retail Sales Data"),
  ]

  events = []
  for kw, day_offset, label in macro_keywords:
    event_date = start_of_week + datetime.timedelta(days=day_offset)
    events.append({
        "event": label,
        "date_str": event_date.strftime("%b %d"),
        "day_name": event_date.strftime("%a").upper(),
    })

  return events[:3]


# ---------------------------------------------------------
# 3. שליפת לוח דיווחי רווחים
# ---------------------------------------------------------
def fetch_actual_upcoming_earnings():
  today = datetime.date.today()
  start_of_week = today + datetime.timedelta(days=(0 - today.weekday()) % 7)
  end_of_week = start_of_week + datetime.timedelta(days=4)

  earnings_by_day = {
      "MON": {"bmo": [], "amc": []},
      "TUE": {"bmo": [], "amc": []},
      "WED": {"bmo": [], "amc": []},
      "THU": {"bmo": [], "amc": []},
      "FRI": {"bmo": [], "amc": []},
  }

  day_map = {0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI"}

  try:
    url = f"https://query2.finance.yahoo.com/v1/finance/visualization/point?formatted=true&key=EARNINGS&start={start_of_week}&end={end_of_week}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with urllib.request.urlopen(req, timeout=6) as resp:
      data = json.loads(resp.read().decode("utf-8"))
      rows = (
          data.get("finance", {})
          .get("result", [{}])[0]
          .get("documents", [{}])[0]
          .get("rows", [])
      )

      for row in rows:
        ticker = row.get("symbol")
        e_date_str = row.get("startdatetime")
        timing = row.get("startdatetimetype", "bmo").lower()

        if ticker and e_date_str:
          e_date = datetime.datetime.strptime(
              e_date_str[:10], "%Y-%m-%d"
          ).date()
          if e_date.weekday() in day_map:
            day_code = day_map[e_date.weekday()]
            session_key = (
                "amc" if "after" in timing or "pm" in timing else "bmo"
            )
            if ticker not in earnings_by_day[day_code][session_key]:
              earnings_by_day[day_code][session_key].append(ticker)
  except Exception as e:
    logger.warning(f"Primary earnings API query failed: {e}")

  for day in earnings_by_day:
    earnings_by_day[day]["bmo"] = earnings_by_day[day]["bmo"][:3]
    earnings_by_day[day]["amc"] = earnings_by_day[day]["amc"][:3]

  return earnings_by_day


# ---------------------------------------------------------
# 4. ארגון קונטקסט
# ---------------------------------------------------------
def fetch_upcoming_week_context(macro_events_list=None, earnings_dict=None):
  fng = get_fear_and_greed_index()
  macro = (
      macro_events_list
      if macro_events_list is not None
      else fetch_upcoming_macro_events()
  )
  earnings = (
      earnings_dict
      if earnings_dict is not None
      else fetch_actual_upcoming_earnings()
  )

  return {"macro_events": macro, "earnings_calendar": earnings, "fear_and_greed": fng}


# ---------------------------------------------------------
# 5. מחולל סקריפטים מפוצל ל-3 חלקים ב-AI
# ---------------------------------------------------------
def generate_upcoming_week_scripts(week_context):
  api_key = os.environ.get("GEMINI_API_KEY")
  client = genai.Client(api_key=api_key)

  prompt = f"""
    You are a professional financial news host previewing the UPCOMING WEEK.
    Generate 3 INDIVIDUAL, CONCISE voiceover scripts for a 3-part weekly forecast segment.

    Segment Data:
    1. Macro Events Data: {week_context['macro_events']}
    2. Earnings Calendar Data: {week_context['earnings_calendar']}
    3. Fear & Greed Index Data: Score {week_context['fear_and_greed']['score']}/100 ({week_context['fear_and_greed']['rating']})

    CRITICAL RULES FOR THE 3 SCRIPTS:
    - "macro_script": 8-12 seconds (~20-25 words). Briefly introduce the upcoming macro economic releases and their dates.
    - "earnings_script": 8-12 seconds (~20-25 words). If major tickers are reporting, name them. IF THERE ARE NO MAJOR MEGA-CAP TICKERS, explicitly state that "No major market-moving earnings are scheduled this week, only smaller reports."
    - "fng_script": 8-12 seconds (~20-25 words). State the Fear & Greed score ({week_context['fear_and_greed']['score']}) and explain what its "{week_context['fear_and_greed']['rating']}" posture means for the market.

    STRICT JSON OUTPUT FORMAT:
    {{
      "macro_script": "Text for macro events segment",
      "earnings_script": "Text for earnings calendar segment",
      "fng_script": "Text for Fear and Greed segment"
    }}
    """

  response = client.models.generate_content(
      model="gemini-flash-lite-latest",
      contents=prompt,
      config=types.GenerateContentConfig(response_mime_type="application/json"),
  )
  return json.loads(response.text)


# ---------------------------------------------------------
# 6. רינדור מסך אירועי מאקרו (Macro Events)
# ---------------------------------------------------------
def render_macro_events_frame(macro_events):
  print(macro_events)
  fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
  canvas = FigureCanvasAgg(fig)
  fig.patch.set_facecolor("#0B0E14")

  # כותרות הלוח
  fig.text(
      0.08,
      0.88,
      "KEY MACRO EVENTS THIS WEEK",
      fontsize=24,
      fontweight="bold",
      color="#FFFFFF",
  )
  fig.text(
      0.08,
      0.82,
      "Economic Data & Central Bank Releases to Watch",
      fontsize=14,
      color="#8B949E",
  )

  start_y = 0.58
  for idx, ev in enumerate(macro_events):
    y_pos = start_y - (idx * 0.18)

    # יצירת הכרטיסייה
    ax_card = fig.add_axes([0.08, y_pos, 0.84, 0.14])
    ax_card.set_facecolor("#161B22")

    # 🔥 התיקון הקריטי: קיבוע מפורש של הצירים ל-0 עד 1
    ax_card.set_xlim(0, 1)
    ax_card.set_ylim(0, 1)

    ax_card.set_xticks([])
    ax_card.set_yticks([])

    for spine in ax_card.spines.values():
      spine.set_color("#30363D")
      spine.set_linewidth(1.5)

    # 1. תאריך ויום (בצד שמאל של הכרטיסייה)
    ax_card.text(
        0.06,
        0.5,
        f"{ev['day_name']}\n{ev['date_str']}",
        fontsize=14,
        fontweight="bold",
        color="#00E5FF",
        va="center",
        ha="center",
    )

    # 2. קו הפרדה אנכי בעובי נכון
    ax_card.plot([0.13, 0.13], [0.15, 0.85], color="#30363D", linewidth=1.5)

    # 3. שם האירוע
    ax_card.text(
        0.17,
        0.5,
        ev["event"],
        fontsize=16,
        fontweight="bold",
        color="#FFFFFF",
        va="center",
        ha="left",
    )

  canvas.draw()
  frame = np.asarray(canvas.buffer_rgba())[:, :, :3]
  plt.close(fig)
  return frame


# ---------------------------------------------------------
# 7. רינדור טבלת דיווחי רווחים
# ---------------------------------------------------------
def render_earnings_grid_frame(earnings_data):
  fig = plt.figure(figsize=(16, 9), dpi=100)
  canvas = FigureCanvasAgg(fig)
  fig.patch.set_facecolor("#0B0E14")

  today = datetime.date.today()
  start_of_week = today + datetime.timedelta(days=(0 - today.weekday()) % 7)

  fig.text(
      0.05,
      0.91,
      "EARNINGS CALENDAR THIS WEEK",
      fontsize=22,
      fontweight="bold",
      color="#FFFFFF",
  )
  fig.text(
      0.05,
      0.86,
      "Companies Reporting Before Open (BMO) & After Close (AMC)",
      fontsize=13,
      color="#8B949E",
  )

  days = ["MON", "TUE", "WED", "THU", "FRI"]
  col_widths = 0.17
  start_x = 0.05

  for idx, day in enumerate(days):
    x_pos = start_x + (idx * 0.185)
    day_date = (start_of_week + datetime.timedelta(days=idx)).strftime("%b %d")

    fig.text(
        x_pos + 0.08,
        0.78,
        f"{day}\n{day_date}",
        fontsize=12,
        fontweight="bold",
        color="#00E5FF",
        ha="center",
    )

    day_data = earnings_data.get(day, {"bmo": [], "amc": []})
    bmo_str = (
        "\n".join([f"• {t}" for t in day_data.get("bmo", [])]) or "No Major"
    )
    amc_str = (
        "\n".join([f"• {t}" for t in day_data.get("amc", [])]) or "No Major"
    )

    ax_bmo = fig.add_axes([x_pos, 0.44, col_widths, 0.28])
    ax_bmo.set_facecolor("#161B22")
    ax_bmo.set_xticks([])
    ax_bmo.set_yticks([])
    for spine in ax_bmo.spines.values():
      spine.set_color("#30363D")
    ax_bmo.text(
        0.08,
        0.85,
        "BEFORE OPEN ☀️",
        fontsize=9,
        fontweight="bold",
        color="#FFB800",
    )
    ax_bmo.text(0.08, 0.45, bmo_str, fontsize=11, color="#FFFFFF", va="center")

    ax_amc = fig.add_axes([x_pos, 0.12, col_widths, 0.28])
    ax_amc.set_facecolor("#161B22")
    ax_amc.set_xticks([])
    ax_amc.set_yticks([])
    for spine in ax_amc.spines.values():
      spine.set_color("#30363D")
    ax_amc.text(
        0.08,
        0.85,
        "AFTER CLOSE ☽",
        fontsize=9,
        fontweight="bold",
        color="#A371F7",
    )
    ax_amc.text(0.08, 0.45, amc_str, fontsize=11, color="#FFFFFF", va="center")

  canvas.draw()
  frame = np.asarray(canvas.buffer_rgba())[:, :, :3]
  plt.close(fig)
  return frame


# ---------------------------------------------------------
# 8. רינדור Fear & Greed Index
# ---------------------------------------------------------
def render_fear_and_greed_frame(fng_data, t=0):
  fig = plt.figure(figsize=(16, 9), dpi=100)
  canvas = FigureCanvasAgg(fig)
  fig.patch.set_facecolor("#0B0E14")

  score = fng_data["score"]
  rating = fng_data["rating"]

  if score < 25:
    color = "#FF3366"
  elif score < 45:
    color = "#FF8800"
  elif score < 55:
    color = "#FFCC00"
  elif score < 75:
    color = "#00E5FF"
  else:
    color = "#00FFA3"

  fig.text(
      0.5,
      0.88,
      "MARKET SENTIMENT",
      fontsize=16,
      fontweight="bold",
      color="#8B949E",
      ha="center",
  )
  fig.text(
      0.5,
      0.82,
      "FEAR & GREED INDEX",
      fontsize=26,
      fontweight="bold",
      color="#FFFFFF",
      ha="center",
  )

  ax = fig.add_axes([0.25, 0.12, 0.50, 0.62])
  ax.set_facecolor("#0B0E14")
  ax.set_xlim(-1.4, 1.4)
  ax.set_ylim(-0.55, 1.25)
  ax.axis("off")

  arc_bg = patches.Wedge(
      (0, 0), 1.0, 0, 180, width=0.45, facecolor="#161B22", edgecolor="#30363D"
  )
  ax.add_patch(arc_bg)

  angle = 180 - (score / 100.0) * 180
  arc_val = patches.Wedge((0, 0), 1.0, angle, 180, width=0.45, facecolor=color)
  ax.add_patch(arc_val)

  rad = np.radians(angle)
  needle_x = 0.72 * np.cos(rad)
  needle_y = 0.72 * np.sin(rad)
  ax.plot(
      [0, needle_x], [0, needle_y], color="#FFFFFF", linewidth=4.0, zorder=10
  )
  ax.scatter([0], [0], color="#FFFFFF", s=140, zorder=11)

  pulse = 1.0 + 0.02 * np.sin(2 * np.pi * t * 1.5)
  ax.text(
      0,
      -0.22,
      f"{score}",
      fontsize=int(58 * pulse),
      fontweight="bold",
      color=color,
      ha="center",
      va="center",
  )
  ax.text(
      0,
      -0.42,
      rating,
      fontsize=20,
      fontweight="bold",
      color="#FFFFFF",
      ha="center",
      va="center",
  )

  canvas.draw()
  frame = np.asarray(canvas.buffer_rgba())[:, :, :3]
  plt.close(fig)
  return frame


# ---------------------------------------------------------
# 9. מנוע יצירת ה-VideoClip (סנכרון מלא של 3 קטעי אודיו למסכים)
# ---------------------------------------------------------
def generate_upcoming_week_clip(macro_events=None, earnings_dict=None):
  print("\n[UPCOMING WEEK] 📅 מפיק קליפ תחזית שבועית מפוצל...")

  week_context = fetch_upcoming_week_context(macro_events, earnings_dict)
  scripts = generate_upcoming_week_scripts(week_context)

  from index_section_generator import generate_voiceover_audio

  sub_clips = []
  temp_audio_files = []

  # 1. קליפ מאקרו (אם יש אירועים)
  if week_context["macro_events"]:
    macro_audio = "temp_macro_narration.mp3"
    generate_voiceover_audio(
        scripts["macro_script"],
        output_path=macro_audio,
        voice="en-GB-RyanNeural",
        rate="+10%",
    )
    temp_audio_files.append(macro_audio)
    voice_macro = AudioFileClip(macro_audio)

    macro_frame = render_macro_events_frame(week_context["macro_events"])
    clip_macro = VideoClip(
        lambda t: macro_frame, duration=voice_macro.duration
    ).set_audio(voice_macro)
    sub_clips.append(clip_macro)

  # 2. קליפ דיווחי רווחים
  earnings_audio = "temp_earnings_narration.mp3"
  generate_voiceover_audio(
      scripts["earnings_script"],
      output_path=earnings_audio,
      voice="en-GB-RyanNeural",
      rate="+10%",
  )
  temp_audio_files.append(earnings_audio)
  voice_earn = AudioFileClip(earnings_audio)

  earnings_frame = render_earnings_grid_frame(
      week_context["earnings_calendar"]
  )
  clip_earn = VideoClip(
      lambda t: earnings_frame, duration=voice_earn.duration
  ).set_audio(voice_earn)
  sub_clips.append(clip_earn)

  # 3. קליפ Fear & Greed Index
  fng_audio = "temp_fng_narration.mp3"
  generate_voiceover_audio(
      scripts["fng_script"]+" Now lets dive into the charts",
      output_path=fng_audio,
      voice="en-GB-RyanNeural",
      rate="+10%",
  )
  temp_audio_files.append(fng_audio)
  voice_fng = AudioFileClip(fng_audio)

  clip_fng = VideoClip(
      lambda t: render_fear_and_greed_frame(week_context["fear_and_greed"], t),
      duration=voice_fng.duration,
  ).set_audio(voice_fng)
  sub_clips.append(clip_fng)

  # שרשור כל החלקים ברצף
  final_upcoming_clip = concatenate_videoclips(sub_clips)

  def cleanup():
    for f in temp_audio_files:
      if os.path.exists(f):
        try:
          os.remove(f)
        except Exception:
          pass

  print("   ✅ קליפ התחזית השבועית המושלם נוצר בסנכרון מלא!")
  return final_upcoming_clip, cleanup


if __name__ == "__main__":
  video, cleanup_fn = generate_upcoming_week_clip()
  output_filename = "following_week_clip.mp4"
  video.write_videofile(
      output_filename, fps=30, codec="libx264", logger="bar"
  )
  cleanup_fn()