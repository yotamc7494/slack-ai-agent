import os
import sys
import logging
from uploader import upload_video
from outro_generator import generate_outro_clip
from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    CompositeAudioClip,
    concatenate_videoclips,
    afx
)
import matplotlib.pyplot as plt
# ייבוא הפונקציות מהמודולים שיצרת
from index_section_generator import (
    fetch_market_data,
    get_macro_news_events,
    generate_market_recap_ai_content,
    generate_voiceover_audio,
    generate_market_video  # פונקציה שמחזירה VideoClip במקום לכתוב לקובץ
)
from fetch_upcoming_week_context import generate_upcoming_week_clip
from stock_section_generator import (
    select_top_stocks_of_the_week,
    generate_stocks_section_video
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("FullVideoPipeline")


def build_full_weekly_video(
        bg_music_path="assets/weekly_recup_music.mp3",
        output_filename="Weekly_Market_Summary.mp4",
        num_stocks=6
):
    print("==================================================")
    print("🎬 מתחיל תהליך הפקת סרטון הסיכום השבועי המלא...")
    print("==================================================\n")

    cleanups = []
    figs_to_close = []

    try:
        # --- חלק 1: סיכום מדדים ---
        print("[1/4] 📈 מפיק את סקציית המדדים...")
        market_data = fetch_market_data(target_points=1000)
        news = get_macro_news_events()
        ai_content = generate_market_recap_ai_content(market_data, news)

        index_script = ai_content["narration_script"]
        youtube_title = ai_content.get("youtube_title", "Weekly_Market_Recap")

        index_audio_file = generate_voiceover_audio(index_script, output_path="temp_index_narration.mp3")
        cleanups.append(index_audio_file)

        index_clip = generate_market_video(
            market_data,
            news,
            audio_path=index_audio_file,
            aspect_ratio="16:9"
        )

        # --- חלק 2: מה יהיה השבוע ---
        print("\n[2/4] 📅 מפיק את סקציית התחזית השבועית...")
        upcoming_clip, _ = generate_upcoming_week_clip()
        cleanups.extend([
            "temp_upcoming_narration.mp3",
            "temp_macro_narration.mp3",
            "temp_earnings_narration.mp3",
            "temp_fng_narration.mp3"
        ])

        # --- חלק 3: פירוט מניות ---
        print("\n[3/4] 📊 מפיק את סקציית ניתוח המניות...")
        top_stocks = select_top_stocks_of_the_week(count=num_stocks)
        stocks_clip, figs = generate_stocks_section_video(top_stocks, duration_per_stock=20.0, fps=30)
        figs_to_close.extend(figs)

        for ticker in top_stocks:
            cleanups.append(f"narration_{ticker}.mp3")

        # --- חלק 4: מסך סיום (Outro & Call to Action) ---
        print("\n[4/4] 🔔 מוסיף מסך סיום להנעה לפעולה (Outro)...")
        outro_clip = generate_outro_clip(duration=5.0)

        # --- 5. שרשור כל 4 החלקים ברצף ---
        print("\n🔗 משרשר את כל סקציות הווידאו...")
        final_video_clip = concatenate_videoclips([index_clip, upcoming_clip, stocks_clip, outro_clip])
        total_duration = final_video_clip.duration

        # --- 6. המוזיקה + עמעום בסיום (Fade Out) ---
        if os.path.exists(bg_music_path):
            print(f"\n🎵 מעבד מוזיקת רקע מ: {bg_music_path} עם Fade Out בסיום...")
            bg_music = AudioFileClip(bg_music_path)

            # התאמת אורך המוזיקה
            if bg_music.duration < total_duration:
                bg_music = afx.audio_loop(bg_music, duration=total_duration)
            else:
                bg_music = bg_music.subclip(0, total_duration)

            # 1. הנמכת ווליום הרקע ל-12%
            bg_music = bg_music.volumex(0.12)

            # 2. 🔥 אפקט Fade Out ב-2.5 השניות האחרונות של הסרטון
            bg_music = bg_music.audio_fadeout(2.5)

            # מיזוג האודיו הקים (קריינות) עם מוזיקת הרקע
            combined_audio = CompositeAudioClip([final_video_clip.audio, bg_music])
            final_video_clip = final_video_clip.set_audio(combined_audio)

        # --- 7. שמירת הקובץ הסופי ---

        print(f"\n💾 מקרן ושומר את הסרטון המלא: {output_filename}...")
        final_video_clip.write_videofile(
            output_filename,
            fps=30,
            codec="libx264",
            audio_codec="aac",
            logger=False
        )

        print(f"\n🎉 הסרטון המלא והמושלם נשמר ב: {output_filename}")

    finally:
        print("\n🧹 מנקה קבצים זמניים ומשאבים...")
        for fig in figs_to_close:
            try:
                plt.close(fig)
            except Exception:
                pass

        for file_path in set(cleanups):
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
    return output_filename, youtube_title, ai_content["description"], ai_content["tags"]


def generate_and_upload_video(upload=True):
    filename, title, v_description, tags = build_full_weekly_video(
        bg_music_path="assets/weekly_recup_music.mp3",
        output_filename="Weekly_Market_Summary.mp4",
        num_stocks=6
    )
    if upload:
        upload_video(filename, title, v_description, tags)
    else:
        return filename
