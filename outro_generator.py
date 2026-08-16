import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from moviepy.editor import VideoClip


def render_outro_frame(t=0):
  """מייצרת פריים Outro מודרני ונקי להנעה לפעולה (Call to Action)."""
  fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
  canvas = FigureCanvasAgg(fig)
  fig.patch.set_facecolor('#0B0E14')

  # פעימה קלה ללוגו/אייקון המרכזי
  pulse = 1.0 + 0.02 * np.sin(2 * np.pi * t * 1.2)

  # כותרת ראשית
  fig.text(
      0.5,
      0.78,
      'STAY AHEAD OF THE MARKET',
      fontsize=20,
      fontweight='bold',
      color='#8B949E',
      ha='center',
  )
  fig.text(
      0.5,
      0.68,
      'LIKE & SUBSCRIBE',
      fontsize=int(38 * pulse),
      fontweight='bold',
      color='#FFFFFF',
      ha='center',
  )

  # קופסה מרכזית להנעה לפעולה
  ax_box = fig.add_axes([0.22, 0.22, 0.56, 0.35])
  ax_box.set_facecolor('#161B22')
  ax_box.set_xticks([])
  ax_box.set_yticks([])
  ax_box.set_xlim(0, 1)
  ax_box.set_ylim(0, 1)

  for spine in ax_box.spines.values():
    spine.set_color('#30363D')
    spine.set_linewidth(1.5)

  # נקודות הנעה לפעולה בתוך הקופסה
  ax_box.text(
      0.5,
      0.72,
      'Ring the Bell for Daily & Weekly Market Updates',
      fontsize=15,
      fontweight='bold',
      color='#00E5FF',
      ha='center',
  )
  ax_box.text(
      0.5,
      0.45,
      'Like & Share to Support the Channel',
      fontsize=15,
      fontweight='bold',
      color='#FFB800',
      ha='center',
  )
  ax_box.text(
      0.5,
      0.20,
      'Comment Your Stock Requests Below!',
      fontsize=13,
      color='#FFFFFF',
      ha='center',
  )

  canvas.draw()
  frame = np.asarray(canvas.buffer_rgba())[:, :, :3]
  plt.close(fig)
  return frame


def generate_outro_clip(duration=5.0):
  """מחזירה VideoClip של מסך הסיום באורך המבוקש."""
  return VideoClip(lambda t: render_outro_frame(t), duration=duration)