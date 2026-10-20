"""Contact sheet of stills for review: python3 video/sheet.py OUT.png t1 t2 ... (renders them first)."""
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
out, ts = sys.argv[1], [float(x) for x in sys.argv[2:]]
subprocess.run(["node", str(HERE / "web" / "render.mjs"), "--stills", ",".join(str(t) for t in ts)], check=True,
               capture_output=True)
W, H, cols = 960, 540, 2
rows = (len(ts) + cols - 1) // cols
sheet = Image.new("RGB", (W * cols, H * rows), "white")
d = ImageDraw.Draw(sheet)
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
for i, t in enumerate(ts):
    im = Image.open(HERE / "build" / "stills" / f"t{t:07.2f}.png").convert("RGB").resize((W, H), Image.LANCZOS)
    x, y = (i % cols) * W, (i // cols) * H
    sheet.paste(im, (x, y))
    d.rectangle([x, y, x + 120, y + 36], fill="black")
    d.text((x + 8, y + 4), f"{t:.1f}", fill="yellow", font=font)
sheet.save(out)
print(out)
