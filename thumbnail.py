import os
from PIL import Image, ImageDraw, ImageFont


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


def generate_simple_thumbnail(
    sp500_weekly_change,
    date_str,
    top_tickers,
    output_path="youtube_thumbnail.png",
):
  """מייצר תמונה ממוזערת מורכבת מבוססת תבנית עם טקסט מעודכן."""
  # 1. בחירת הטמפלייט המורכב לפי סנטימנט השוק
  if sp500_weekly_change >= 0:
    template_path = "assets/template_bullish.jpeg"
    change_text = f"+{sp500_weekly_change:.2f}%"
  else:
    template_path = "assets/template_bearish.jpeg"
    change_text = f"{sp500_weekly_change:.2f}%"

  if not os.path.exists(template_path):
    raise FileNotFoundError(
        f"⚠️ קובץ התבנית {template_path} לא נמצא. וודא שהוא קיים."
    )

  img = Image.open(template_path).convert("RGB")
  draw = ImageDraw.Draw(img)

  # 2. טעינת פונטים בצורה עמידה לכל סביבת הרצה
  font_large = load_system_font(65)
  font_medium = load_system_font(50)

  # 3. הכנת הטקסט
  line1_text = f"{date_str}"

  # 4. חישוב מיקומים בתוך המסגרת השחורה
  line1_y = 100
  line2_y = 330
  start_x = 100

  # 5. ציור הטקסטים
  draw.text(
      (start_x, line1_y), line1_text, font=font_large, fill=(255, 255, 255)
  )

  change_color = (
      (0, 255, 163) if sp500_weekly_change > 0 else (255, 51, 102)
  )
  draw.text(
      (start_x + 100, line1_y + 100),
      change_text,
      font=font_large,
      fill=change_color,
  )

  for i in range(min(3, len(top_tickers))):
    draw.text(
        (start_x + 150, line2_y + i * 120),
        top_tickers[i],
        font=font_medium,
        fill=(255, 255, 255),
    )

  # 6. שמירה
  img.save(output_path)
  print(f"📸 Thumbnail נוצר בהצלחה מ-Template המורכב: {template_path}")
  return output_path