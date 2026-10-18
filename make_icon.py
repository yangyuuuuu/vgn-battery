import sys, os
sys.path.insert(0, ".")
import win_icon

sizes = (16, 24, 32, 48, 64, 128, 256)
green = (93, 220, 138)
imgs = [(s, win_icon.render_rgba("88", s, green, True)) for s in sizes]
os.makedirs("docs", exist_ok=True)
with open(os.path.join("docs", "icon.ico"), "wb") as f:
    f.write(win_icon.build_ico(imgs))
print("icon bytes:", os.path.getsize(os.path.join("docs", "icon.ico")))
