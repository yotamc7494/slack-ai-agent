import streamlit as st
import os
from comparison_video_engine import run_generator
from main import render_final_video, view_final_video

st.set_page_config(page_title="AI Stock Video Generator", page_icon="🚀")

st.title("🚀 מחולל סרטוני מניות - מעקף ידני")
st.write("סרטוני מנייה")
col1, col2 = st.columns(2)

with col1:
    run_full = st.button("🚀 הרץ והעלה ליוטיוב")

with col2:
    run_test = st.button("🧪 הרצת ניסיון (תצוגה מקדימה)")
st.write("סרטוני השוואה")
with col1:
    run_full_c = st.button("🚀 הרץ והעלה ליוטיוב")

with col2:
    run_test_c = st.button("🧪 הרצת ניסיון (תצוגה מקדימה)")

if run_full or run_test:
    is_test_mode = run_test

    if is_test_mode:
        st.warning("🧪 מריץ במצב ניסיון: הסרטון לא יועלה ליוטיוב והמניה לא תישמר ב-used stocks.")
        filename = view_final_video()
        st.success("✅ הסרטון נוצר בהצלחה!")

        # קריאת הקובץ ויצירת כפתור הורדה דפדפני
        with open(filename, "rb") as file:
            st.download_button(
                label="📥 הורד את הסרטון למחשב",
                data=file,
                file_name=os.path.basename(filename),
                mime="video/mp4"
            )
    else:
        st.info("🚀 מריץ תהליך מלא כולל העלאה ליוטיוב...")
        render_final_video()

if run_test_c or run_full_c:
    is_test_mode = run_test_c
    run_generator(is_test_mode)
