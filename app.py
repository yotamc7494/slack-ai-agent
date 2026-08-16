import streamlit as st
import os
import sys
# ייבוא הפונקציות המקוריות שלך - הנוסחאות עובדות!
from comparison_video_engine import run_generator
from main import render_final_video, view_final_video
from weekly_summery_video import generate_and_upload_video

st.set_page_config(page_title="AI Stock Video Generator", page_icon="🚀")

st.title("🚀 מחולל סרטוני מניות - מעקף ידני")

# --- סקשן סרטוני מנייה ---
st.header("סרטוני מנייה")
# יצירת עמודות נפרדות עבור סקשן זה
col1, col2 = st.columns(2)

if "WEBHOOK_TOKEN" in st.query_params:
  if st.query_params["WEBHOOK_TOKEN"] == st.secrets.get("WEBHOOK_TOKEN"):
    video_type = st.query_params["video_type"]
    print(f"⚡ Webhook triggered from GitHub Actions! - {video_type}", flush=True)
    if video_type == "update_video":
        sys.stdout.reconfigure(line_buffering=True)
        filename = render_final_video()
        st.success(f"✅ הסרטון נוצר בהצלחה: {filename}")
        print(f"✅ הסרטון נוצר בהצלחה: {filename}", flush=True)

    elif video_type == "vs_video":
        sys.stdout.reconfigure(line_buffering=True)
        filename = run_generator()
        st.success(f"✅ הסרטון נוצר בהצלחה: {filename}")
        print(f"✅ הסרטון נוצר בהצלחה: {filename}", flush=True)
    elif video_type == "weekly_summery":
        sys.stdout.reconfigure(line_buffering=True)
        filename = generate_and_upload_video()
        st.success(f"✅ הסרטון נוצר בהצלחה: {filename}")
        print(f"✅ הסרטון נוצר בהצלחה: {filename}", flush=True)
  else:
      st.info("Wrong Token!")

with col1:
    # שינוי התווית לייחודית: הוספת המילה "מנייה"
    run_full = st.button("🚀 הרץ והעלה מנייה ליוטיוב")

with col2:
    # שינוי התווית לייחודית: הוספת המילה "מנייה"
    run_test = st.button("🧪 הרצת ניסיון מנייה (תצוגה מקדימה)")

# לוגיקת הפעלה עבור סרטוני מנייה
if run_full or run_test:
    is_test_mode = run_test

    if is_test_mode:
        st.warning("🧪 מריץ במצב ניסיון: הסרטון לא יועלה ליוטיוב והמניה לא תישמר ב-used stocks.")
        # קריאה לפונקציה המקורית שלך
        filename = view_final_video()
        st.success("✅ הסרטון נוצר בהצלחה!")

        # יצירת כפתור הורדה
        if filename and os.path.exists(filename):
            with open(filename, "rb") as file:
                st.download_button(
                    label="📥 הורד את הסרטון למחשב",
                    data=file,
                    file_name=os.path.basename(filename),
                    mime="video/mp4"
                )
        else:
            st.error("שגיאה: קובץ הוידאו לא נמצא.")
    else:
        st.info("🚀 מריץ תהליך מלא כולל העלאה ליוטיוב...")
        # קריאה לפונקציה המקורית שלך
        render_final_video()
        st.success("התהליך הסתייים.")

st.write("---") # קו מפריד ויזואלי

# --- סקשן סרטוני השוואה ---
st.header("סרטוני השוואה")
# יצירת עמודות נפרדות וחדשות (col3, col4) עבור סקשן זה כדי למנוע בלבול
col3, col4 = st.columns(2)

with col3:
    # שינוי התווית לייחודית: הוספת המילה "השוואה"
    run_full_c = st.button("🚀 הרץ והעלה השוואה ליוטיוב")

with col4:
    # שינוי התווית לייחודית: הוספת המילה "השוואה"
    run_test_c = st.button("🧪 הרצת ניסיון השוואה (תצוגה מקדימה)")

# לוגיקת הפעלה עבור סרטוני השוואה
if run_test_c or run_full_c:
    is_test_mode_c = run_test_c
    st.info(f"מריץ סרטון השוואה (מצב טסט: {is_test_mode_c})...")
    # קריאה לפונקציה המקורית שלך מהקובץ השני
    video_path = run_generator(is_test_mode_c)
    st.success("תהליך יצירת סרטון השוואה הסתיים.")
    if video_path and os.path.exists(video_path):
        with open(video_path, "rb") as file:
            st.download_button(
                label="📥 הורד את ההשוואה למחשב",
                data=file,
                file_name=os.path.basename(video_path),
                mime="video/mp4"
            )

st.write("---") # קו מפריד ויזואלי

# --- סקשן סרטוני השוואה ---
st.header("סרטוני סיכום שבועי")
# יצירת עמודות נפרדות וחדשות (col3, col4) עבור סקשן זה כדי למנוע בלבול
col5, col6 = st.columns(2)

with col5:
    # שינוי התווית לייחודית: הוספת המילה "השוואה"
    run_full_c = st.button("🚀 הרץ והעלה סיכום שבועי ליוטיוב")

with col6:
    # שינוי התווית לייחודית: הוספת המילה "השוואה"
    run_test_c = st.button("🧪 הרצת ניסיון סיכום שבועי (תצוגה מקדימה)")

# לוגיקת הפעלה עבור סרטוני השוואה
if run_test_c or run_full_c:
    is_test_mode_c = run_test_c
    st.info(f"מריץ סרטון סיכום שבועי (מצב טסט: {is_test_mode_c})...")
    # קריאה לפונקציה המקורית שלך מהקובץ השני
    video_path = generate_and_upload_video(upload=not is_test_mode_c)
    st.success("תהליך יצירת סרטון סיכום שבועי הסתיים.")
    if video_path and os.path.exists(video_path):
        with open(video_path, "rb") as file:
            st.download_button(
                label="📥 הורד את הסיכום השבועי למחשב",
                data=file,
                file_name=os.path.basename(video_path),
                mime="video/mp4"
            )