import streamlit as st
import os
from main import render_final_video, view_final_video

st.set_page_config(page_title="AI Stock Video Generator", page_icon="🚀")

st.title("🚀 מחולל סרטוני מניות - מעקף ידני")
st.write("האתר אינו מריץ סרטונים אוטומטית בכניסה. לחץ על הכפתור כדי להפיק ולהעלות סרטון עכשיו.")
col1, col2 = st.columns(2)

with col1:
    run_full = st.button("🚀 הרץ והעלה ליוטיוב")

with col2:
    run_test = st.button("🧪 הרצת ניסיון (תצוגה מקדימה)")

if run_full or run_test:
    is_test_mode = run_test

    if is_test_mode:
        st.warning("🧪 מריץ במצב ניסיון: הסרטון לא יועלה ליוטיוב והמניה לא תישמר ב-used stocks.")
        filename = view_final_video()
        if filename and os.path.exists(filename):
            st.subheader("🎥 תצוגה מקדימה של הסרטון:")
            st.video(filename)
    else:
        st.info("🚀 מריץ תהליך מלא כולל העלאה ליוטיוב...")
        render_final_video()