import streamlit as st
from main import render_final_video

st.set_page_config(page_title="AI Stock Video Generator", page_icon="🚀")

st.title("🚀 מחולל סרטוני מניות - מעקף ידני")
st.write("האתר אינו מריץ סרטונים אוטומטית בכניסה. לחץ על הכפתור כדי להפיק ולהעלות סרטון עכשיו.")

# הקוד ירוץ אך ורק בעת לחיצה על הכפתור
if st.button("🎬 צור והעלה סרטון עכשיו", type="primary"):
    with st.spinner("מייצר גרף, קריינות, כתוביות ומעלה ליוטיוב..."):
        try:
            render_final_video()
            st.success("✅ הסרטון נוצר והועלה בהצלחה ליוטיוב!")
        except Exception as e:
            st.error(f"🚨 שגיאה במהלך ההרצה: {e}")