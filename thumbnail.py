import os
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timedelta


def load_system_font(size):
  """טוענת פונט בצורה עמידה שמתאימה גם ל-Windows, גם ל-Linux בשרת ענן, וגם

  לפונט ברירת מחדל.
  """
  # 1. עדיפות ראשונה: פונט מקומי בתיקיית הפרויקט
  local_fonts = ["Roboto-Bold.ttf", "Montserrat-Bold.ttf", "arial.ttf"]
  for font_file in local_fonts:
    if os.path.exists(font_file):
      try:
        return ImageFont.truetype(font_file, size)
      except Exception:
        pass

  # 2. עדיפות שנייה: נתיבים של Linux/Ubuntu בשרתי ענן (Streamlit Cloud)
  linux_fonts = [
      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
      "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
      "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
  ]
  for font_path in linux_fonts:
    try:
      return ImageFont.truetype(font_path, size)
    except Exception:
      continue

  # 3. עדיפות שלישית: שמות פונטים של Windows
  windows_fonts = ["impact.ttf", "ariblk.ttf", "arialbd.ttf", "trebucbd.ttf"]
  for font_name in windows_fonts:
    try:
      return ImageFont.truetype(font_name, size)
    except Exception:
      continue

  # 4. Fallback אחרון במידה ולא נמצא אף פונט במערכת
  try:
    return ImageFont.load_default(size=size)
  except Exception:
    return ImageFont.load_default()


def generate_daily_thumbnail(
        sp500_val, sp500_pct,
        qqq_val, qqq_pct,
        btc_val, btc_pct,
        date_str=None,  # תאריך אופציונלי. אם לא מועבר - מחושב אוטומטית
        template_path="assets/Thumbnail_Daily.jpg",
        output_path="youtube_thumbnail_daily.png"
):
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"⚠️ קובץ התבנית {template_path} לא נמצא.")

    img = Image.open(template_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    # 1. חישוב תאריך יומי במידה ולא הועבר
    if not date_str:
        date_str = datetime.now().strftime("%B %d, %Y")  # למשל: August 20, 2026

    # 2. הוספת התאריך מתחת לכותרת DAILY RECAP (בצבע תכלת ניאון)
    font_date = load_system_font(int(h * 0.038))
    draw.text((w * 0.5, h * 0.29), date_str.upper(), font=font_date, fill=(255, 255, 255), anchor="mm")

    # 3. הוספת הנתונים בטבלה
    font_val = load_system_font(int(h * 0.055))

    rows = [
        (f"${sp500_val:,.2f}", sp500_pct, 0.508),  # S&P500
        (f"${qqq_val:,.2f}", qqq_pct, 0.683),  # Nasdaq
        (f"${btc_val:,.0f}", btc_pct, 0.858)  # BitCoin
    ]

    x_val_center = w * 0.523  # מרכז תא הערך (אמצע)
    x_pct_center = w * 0.785  # מרכז תא האחוזים (ימין)

    for val_str, pct_val, y_rel in rows:
        y_pos = h * y_rel

        # כתיבת המחיר/ערך (לבן)
        draw.text((x_val_center, y_pos), val_str, font=font_val, fill=(255, 255, 255), anchor="mm")

        # כתיבת אחוז השינוי (ירוק/אדום)
        pct_str = f"{pct_val:+.2f}%"
        color = (0, 255, 163) if pct_val >= 0 else (255, 51, 102)
        draw.text((x_pct_center, y_pos), pct_str, font=font_val, fill=color, anchor="mm")

    img.save(output_path)
    print(f"📸 Daily Thumbnail נוצר בהצלחה: {output_path}")
    return output_path


# ---------------------------------------------------------
# 2. תמונה ממוזערת לסיכום שבועי (Weekly Thumbnail)
# ---------------------------------------------------------
def generate_weekly_thumbnail(
        stocks_list,  # רשימה של עד 6 דיקשנריז: [{'ticker': 'NVDA', 'pct_change': 4.5}, ...]
        date_range_str=None,  # טווח תאריכים אופציונלי. אם לא מועבר - מחושב אוטומטית (שני עד שישי)
        template_path="assets/Thumbnail_Weekly.jpg",
        output_path="youtube_thumbnail_weekly.png"
):
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"⚠️ קובץ התבנית {template_path} לא נמצא.")

    img = Image.open(template_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    # 1. חישוב טווח ימי המסחר לשבוע (שני עד שישי) במידה ולא הועבר
    if not date_range_str:
        today = datetime.now()
        monday = today - timedelta(days=today.weekday())
        friday = monday + timedelta(days=4)
        date_range_str = f"{monday.strftime('%b %d')} - {friday.strftime('%b %d, %Y')}"  # למשל: AUG 17 - AUG 21, 2026

    # 2. הוספת טווח התאריכים השבועי מתחת לכותרת WEEKLY RECAP
    font_date = load_system_font(int(h * 0.038))
    draw.text((w * 0.5, h * 0.29), date_range_str.upper(), font=font_date, fill=(255, 255, 255), anchor="mm")

    # 3. הוספת נתוני המניות בטבלה
    font_stock = load_system_font(int(h * 0.052))

    y_positions = [h * 0.508, h * 0.683, h * 0.858]
    col_coords = [
        {"ticker_x": w * 0.165, "pct_x": w * 0.380},  # עמודה שמאלית
        {"ticker_x": w * 0.620, "pct_x": w * 0.835}  # עמודה ימנית
    ]

    for i in range(min(6, len(stocks_list))):
        stock = stocks_list[i]
        row_idx = i % 3
        col_idx = i // 3

        y_pos = y_positions[row_idx]
        coords = col_coords[col_idx]

        ticker_str = str(stock.get("ticker", "")).upper()
        pct_val = float(stock.get("pct_change", 0.0))
        pct_str = f"{pct_val:+.2f}%"

        # שם הטיקר (לבן)
        draw.text((coords["ticker_x"], y_pos), ticker_str, font=font_stock, fill=(255, 255, 255), anchor="mm")

        # אחוז השינוי השבועי (ירוק/אדום)
        color = (0, 255, 163) if pct_val >= 0 else (255, 51, 102)
        draw.text((coords["pct_x"], y_pos), pct_str, font=font_stock, fill=color, anchor="mm")

    img.save(output_path)
    print(f"📸 Weekly Thumbnail נוצר בהצלחה: {output_path}")
    return output_path
