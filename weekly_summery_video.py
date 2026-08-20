import datetime
import logging
import os
import sys
import matplotlib.pyplot as plt
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    VideoFileClip,
    afx,
    concatenate_videoclips,
)
from outro_generator import generate_outro_clip
from thumbnail import generate_weekly_thumbnail
from uploader import upload_video

# ייבוא הפונקציות מהמודולים שיצרת
from fetch_upcoming_week_context import generate_upcoming_week_clip
from index_section_generator import (
    fetch_market_data,
    generate_market_recap_ai_content,
    generate_market_video,
    generate_voiceover_audio,
    get_macro_news_events,
)
from stock_section_generator import (
    generate_stocks_section_video,
    select_top_stocks_of_the_week,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FullVideoPipeline")
import PIL.Image
if not hasattr(PIL.Image, 'ANTIALIAS'):
  PIL.Image.ANTIALIAS = PIL.Image.LANCZOS


def get_formatted_today(ref_date=None):
  if ref_date is None:
    ref_date = datetime.datetime.now()

  # חישוב יום שישי האחרון (אם מריצים בסופ"ש/שני, מביא את יום שישי שהיה)
  # ב-Python: Monday=0, ..., Friday=4, Saturday=5, Sunday=6
  days_since_friday = (ref_date.weekday() - 4) % 7
  last_friday = ref_date - datetime.timedelta(days=days_since_friday)
  last_monday = last_friday - datetime.timedelta(days=4)

  # 1. מקרה רגיל: אותם חודש ושנה (למשל: Aug 10-14, 2026)
  if (
      last_monday.month == last_friday.month
      and last_monday.year == last_friday.year
  ):
    month_str = last_monday.strftime("%b")
    return f"{month_str} {last_monday.day:02d}-{last_friday.day:02d}, {last_friday.year}"

  # 2. מעבר חודש באותה שנה (למשל: Jul 28 - Aug 01, 2026)
  elif last_monday.year == last_friday.year:
    return f"{last_monday.strftime('%b %d')} - {last_friday.strftime('%b %d, %Y')}"

  # 3. מעבר שנה (למשל: Dec 28, 2025 - Jan 02, 2026)
  else:
    return f"{last_monday.strftime('%b %d, %Y')} - {last_friday.strftime('%b %d, %Y')}"


def format_time_mm_ss(seconds):
  """ממירה שניות לפורמט MM:SS שהרשת והאלגוריתם של YouTube מבינים."""
  minutes = int(seconds) // 60
  secs = int(seconds) % 60
  return f"{minutes:02d}:{secs:02d}"


def inject_timestamps_to_description(
    ai_description,
    top_tickers,
    intro_duration,
    upcoming_duration,
    stocks_duration,
    outro_duration,
):
  """מקבלת את התיאור שנוצר ב-AI ומזריקה לתוכו סקציית Timestamps מדויקת."""
  current_time = 0.0
  timestamps = []

  # 1. חובה ביוטיוב: הפרק הראשון חייב להתחיל ב-00:00
  timestamps.append(
      f"{format_time_mm_ss(current_time)} - Market Overview & S&P 500"
  )
  current_time += intro_duration

  # 2. סקציית תחזית שבועית
  timestamps.append(
      f"{format_time_mm_ss(current_time)} - Upcoming Week Outlook"
  )
  current_time += upcoming_duration

  # 3. ניתוח מניות (חישוב זמן ממוצע למנייה)
  stock_avg_duration = (
      stocks_duration / len(top_tickers) if top_tickers else 20.0
  )
  for ticker in top_tickers:
    timestamps.append(
        f"{format_time_mm_ss(current_time)} - {ticker} Stock Breakdown"
    )
    current_time += stock_avg_duration

  # 4. פרק סיכום/Outro
  timestamps.append(
      f"{format_time_mm_ss(current_time)} - Final Thoughts & Outro"
  )

  timestamps_formatted = "\n".join(timestamps)

  hashtags = " ".join([f"#{ticker}" for ticker in top_tickers[:5]])

  full_description = f"""{ai_description.strip()}

📌 Chapters / Timestamps:
{timestamps_formatted}

⚠️ Disclaimer:
This video is for educational and informational purposes only and does not constitute financial advice.

{hashtags} #StockMarket #Investing #SP500
"""
  return full_description


def build_full_weekly_video(
    bg_music_path="assets/weekly_recup_music.mp3",
    output_filename="Weekly_Market_Summary.mp4",
    num_stocks=6,
):
    print("==================================================")
    print("🎬 מתחיל תהליך הפקת סרטון הסיכום השבועי המלא...")
    print("==================================================\n")

    cleanups = []
    figs_to_close = []
    clips_to_close = []

    try:
        # --- חלק 1: סיכום מדדים ---
        print("[1/4] 📈 מפיק את סקציית המדדים...")
        market_data = fetch_market_data(target_points=1000)
        news = get_macro_news_events()
        ai_content = generate_market_recap_ai_content(market_data, news)

        index_script = ai_content["narration_script"]
        youtube_title = ai_content.get("youtube_title", "Weekly_Market_Recap")

        # חילוץ שינוי שבועי אמיתי עבור ה-Thumbnail
        sp500_change = market_data.get("sp500_pct_change", 0.0)

        index_audio_file = generate_voiceover_audio(
            index_script, output_path="temp_index_narration.mp3"
        )
        cleanups.append(index_audio_file)

        index_clip = generate_market_video(
            market_data, news, audio_path=index_audio_file
        )
        clips_to_close.append(index_clip)

        # --- חלק 2: מה יהיה השבוע ---
        print("\n[2/4] 📅 מפיק את סקציית התחזית השבועית...")
        upcoming_clip, _ = generate_upcoming_week_clip()
        clips_to_close.append(upcoming_clip)
        cleanups.extend([
            "temp_upcoming_narration.mp3",
            "temp_macro_narration.mp3",
            "temp_earnings_narration.mp3",
            "temp_fng_narration.mp3",
        ])

        # --- חלק 3: פירוט מניות ---
        print("\n[3/4] 📊 מפיק את סקציית ניתוח המניות...")
        top_stocks = select_top_stocks_of_the_week(count=num_stocks)

        # חילוץ טיקרים למקרה ש-top_stocks מכיל אובייקטים/דיקשנריז
        top_tickers = [
            s.get("ticker", s) if isinstance(s, dict) else str(s)
            for s in top_stocks
        ]

        stocks_clip, figs, stocks_thumbnail_data = generate_stocks_section_video(
            top_stocks, duration_per_stock=20.0, fps=30
        )
        clips_to_close.append(stocks_clip)
        figs_to_close.extend(figs)

        for ticker in top_tickers:
            cleanups.append(f"narration_{ticker}.mp3")

        # --- חלק 4: מסך סיום (Outro & Call to Action) ---
        print("\n[4/4] 🔔 מוסיף מסך סיום להנעה לפעולה (Outro)...", flush=True)
        outro_clip = generate_outro_clip(duration=5.0)
        clips_to_close.append(outro_clip)

        # --- 5. שרשור כל 4 החלקים ברצף ב-1080p ---
        print("\n🔗 משרשר את כל סקציות הווידאו...")
        index_clip_res = index_clip.resize((1920, 1080))
        upcoming_clip_res = upcoming_clip.resize((1920, 1080))
        stocks_clip_res = stocks_clip.resize((1920, 1080))
        outro_clip_res = outro_clip.resize((1920, 1080))

        final_video_clip = concatenate_videoclips([
            index_clip_res,
            upcoming_clip_res,
            stocks_clip_res,
            outro_clip_res,
        ])
        clips_to_close.append(final_video_clip)
        total_duration = final_video_clip.duration

        # --- 6. בילד לתיאור מפורט עם Timestamps ---
        formatted_description = inject_timestamps_to_description(
            ai_description=ai_content.get("description", ""),
            top_tickers=top_tickers,
            intro_duration=index_clip.duration,
            upcoming_duration=upcoming_clip.duration,
            stocks_duration=stocks_clip.duration,
            outro_duration=outro_clip.duration,
        )

        # --- 7. המוזיקה + עמעום בסיום (Fade Out) ---
        if os.path.exists(bg_music_path):
            print(
                f"\n🎵 מעבד מוזיקת רקע מ: {bg_music_path} עם Fade Out בסיום...",
                flush=True,
            )
            bg_music = AudioFileClip(bg_music_path)

            if bg_music.duration < total_duration:
                bg_music = afx.audio_loop(bg_music, duration=total_duration)
            else:
                bg_music = bg_music.subclip(0, total_duration)

            # תיקון קריאות אפקטים ב-MoviePy
            bg_music = afx.volumex(bg_music, 0.12)
            bg_music = afx.audio_fadeout(bg_music, 2.5)

            combined_audio = CompositeAudioClip([final_video_clip.audio, bg_music])
            final_video_clip = final_video_clip.set_audio(combined_audio)

        # --- 8. שמירת הקובץ הסופי ---
        print(f"\n💾 מקרן ושומר את הסרטון המלא: {youtube_title}...", flush=True)
        #final_video_clip.write_videofile(
        #    output_filename,
        #    fps=30,
        #    codec="libx264",
        #    audio_codec="aac",
        #    bitrate="8000k",
        #    logger=None,
        #    threads=1,
        #    preset="ultrafast",
        #)

        print(f"\n🎉 הסרטון המלא והמושלם נשמר ב: {output_filename}")

        date_range_str = get_formatted_today()

        return (
            output_filename,
            youtube_title,
            formatted_description,
            ai_content.get("tags", []),
            stocks_thumbnail_data,
            sp500_change,
            date_range_str,
        )

    finally:
        print("\n🧹 מנקה קבצים זמניים ומשאבים...")
        for fig in figs_to_close:
            try:
                plt.close(fig)
            except Exception:
                pass

        for clip in clips_to_close:
            try:
                clip.close()
            except Exception:
                pass

        for file_path in set(cleanups):
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass


def generate_and_upload_video(upload=True):
    (
        filename,
        title,
        v_description,
        tags,
        stocks_thumbnail_data,
        sp500_weekly_change,
        date_range_str,
    ) = build_full_weekly_video(
        bg_music_path="assets/weekly_recup_music.mp3",
        output_filename="Weekly_Market_Summary.mp4",
        num_stocks=6,
    )

    # יצירת ה-Thumbnail השבועי עם הפרמטרים המעודכנים
    img_path = generate_weekly_thumbnail(
        stocks_list=stocks_thumbnail_data,
        date_range_str=date_range_str,
        template_path="assets/Thumbnail_Weekly.jpg",
        output_path="thumbnail.png",
    )

    if upload:
        upload_video(
            filename,
            title,
            v_description,
            tags,
            thumbnail_path=img_path,
        )

    return filename

if __name__ == "__main__":
    generate_and_upload_video(upload=False)
