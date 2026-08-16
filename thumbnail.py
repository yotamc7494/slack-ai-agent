from PIL import Image, ImageDraw, ImageFont
import os


def generate_simple_thumbnail(
        sp500_weekly_change,
        date_str,
        top_tickers,
        output_path='youtube_thumbnail.png',
):
  """
  מייצר תמונה ממוזערת מורכבת מבוססת תבנית עם טקסט מעודכן.
  מתאים את מיקומי הטקסט והפונטים לתבנית הניאון המורכבת.
  """
  # 1. בחירת הטמפלייט המורכב לפי סנטימנט השוק
  # הנחה: קבצי התבנית המורכבים קיימים ב-assets/
  if sp500_weekly_change >= 0:
    # תבנית עם גרף ניאון ירוק עולה
    template_path = 'assets/template_bullish.jpeg'
    change_text = f'+{sp500_weekly_change:.2f}%'
  else:
    # תבנית עם גרף ניאון אדום יורד (כמו בתמונה)
    template_path = 'assets/template_bearish.jpeg'
    change_text = f'{sp500_weekly_change:.2f}%'

  if not os.path.exists(template_path):
    raise FileNotFoundError(f"⚠️ קובץ התבנית {template_path} לא נמצא. וודא שהוא קיים.")

  img = Image.open(template_path).convert('RGB')
  draw = ImageDraw.Draw(img)

  # 2. טעינת פונטים - השתמש ב-Bold (מודגש) למראה הניאון העבה
  # הגדל גדלים כדי להתאים לתבנית הגדולה
  try:
    # נסה לטעון Arial Bold. אם לא, נסה Roboto Bold.
    # אם אף אחד מהם לא נמצא, השתמש ב-Arial הרגיל ודלג על Bold.
    font_large = ImageFont.truetype('arialbd.ttf', 65)
    font_medium = ImageFont.truetype('arialbd.ttf', 50)
  except IOError:
    try:
      font_large = ImageFont.truetype('Roboto-Bold.ttf', 80)
      font_medium = ImageFont.truetype('Roboto-Bold.ttf', 50)
    except IOError:
      print("⚠️ הפונטים המודגשים arialbd.ttf או Roboto-Bold.ttf לא נמצאו. משתמש ב-Arial הרגיל.")
      font_large = ImageFont.truetype('arial.ttf', 80)
      font_medium = ImageFont.truetype('arial.ttf', 50)

  # 3. הכנת הטקסט
  # שורה 1: תאריך | אחוז שינוי
  line1_text = f'{date_str}'
  # שורה 2: FOCUS: הטיקרים המובילים
  msg = ' • '.join(top_tickers[:3])
  line2_text = f'FOCUS: {msg}'

  # 4. חישוב מיקומים בתוך המסגרת השחורה השמאלית
  # הנחה: התבנית היא 1920x1080. המסגרת תופסת בערך את השליש השמאלי.

  # קואורדינטות Y למיקום מרכזי יותר בתוך המסגרת
  line1_y = 100
  line2_y = 330

  # כדי ליישר למרכז אופקית בתוך המסגרת, נשתמש בנקודת X קבועה
  # נקודה X של 150 נראית כמו נקודת התחלה טובה בתוך המסגרת
  start_x = 100

  # 5. ציור הטקסטים
  # שורה ראשונה (גדול, לבן)
  draw.text((start_x, line1_y), line1_text, font=font_large, fill=(255, 255, 255))
  draw.text((start_x+100, line1_y+100), change_text, font=font_large, fill=(0, 255, 163) if sp500_weekly_change>0 else (255, 51, 102))
  # שורה שנייה (בינוני, אפור בהיר)
  for i in range(3):
    draw.text((start_x+140, line2_y+i*120), top_tickers[i], font=font_medium, fill=(255, 255, 255))

  # 6. שמירה
  img.save(output_path)
  print(f'📸 Thumbnail נוצר בהצלחה מ-Template המורכב: {template_path}')
  return output_path

