"""Generate Modish Enterprises brand logo assets for the HRMS app.

Produces:
- ekkaa-mark.png & modish-mark.png: Centered square brand mark (512x512)
- favicon.png & favicon.ico: Crisp browser favicons (64x64 PNG and multi-res ICO)
- ekkaa-logo-full.png & modish-logo-full.png: Full brand lockup with mark + MODISH ENTERPRISES

Saves to both:
- static/img/
- deploy-ready/static/img/
"""
import os
import shutil
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_IMG = os.path.join(ROOT, "static", "img")
DEPLOY_IMG = os.path.join(ROOT, "deploy-ready", "static", "img")

# Look for source mark
source_candidates = [
    os.path.join(STATIC_IMG, "modish_source_logo.png"),
    os.path.join(ROOT, "..", "modish_preview.png"),
    os.path.join(STATIC_IMG, "ekkaa-mark.png"),
    os.path.join(STATIC_IMG, "modish-mark.png"),
]

src_path = None
for cand in source_candidates:
    p = os.path.abspath(cand)
    if os.path.exists(p):
        src_path = p
        break

if not src_path:
    raise FileNotFoundError("Could not find Modish Enterprises logo source image.")

print(f"Using source mark: {src_path}")
im_mark = Image.open(src_path).convert("RGBA")

# Crop to visible non-transparent content
bbox = im_mark.getbbox()
mark_cropped = im_mark.crop(bbox)
mw, mh = mark_cropped.size
print(f"Cropped mark bounds: {mw}x{mh}")

# 1. Square Brand Mark (512x512)
SIDE = 512
canvas_mark = Image.new("RGBA", (SIDE, SIDE), (0, 0, 0, 0))
scale = 460.0 / max(mw, mh)
tw = int(round(mw * scale))
th = int(round(mh * scale))
mark_scaled = mark_cropped.resize((tw, th), Image.LANCZOS)
canvas_mark.paste(mark_scaled, ((SIDE - tw) // 2, ((SIDE - th) // 2)), mark_scaled)

# 2. Favicons
favicon_64 = canvas_mark.resize((64, 64), Image.LANCZOS)
favicon_32 = canvas_mark.resize((32, 32), Image.LANCZOS)
favicon_16 = canvas_mark.resize((16, 16), Image.LANCZOS)

# 3. Full Brand Logo Lockup (Mark + MODISH ENTERPRISES)
LW, LH = 800, 240
logo_full = Image.new("RGBA", (LW, LH), (0, 0, 0, 0))

# Mark scaled to height 180
m_scale = 180.0 / th
fm_w = int(round(tw * m_scale))
fm_h = 180
fm_scaled = mark_cropped.resize((fm_w, fm_h), Image.LANCZOS)
logo_full.paste(fm_scaled, (30, (LH - fm_h) // 2), fm_scaled)

draw = ImageDraw.Draw(logo_full)
font_bold_candidates = ["segoeuib.ttf", "arialbd.ttf", "calibrib.ttf"]
font_candidates = ["segoeui.ttf", "arial.ttf", "calibri.ttf"]

main_font = None
sub_font = None
for fb in font_bold_candidates:
    try:
        main_font = ImageFont.truetype(fb, 76)
        break
    except Exception:
        pass

for f in font_candidates:
    try:
        sub_font = ImageFont.truetype(f, 30)
        break
    except Exception:
        pass

if main_font is None:
    main_font = ImageFont.load_default()
if sub_font is None:
    sub_font = ImageFont.load_default()

text_x = 30 + fm_w + 35
# "MODISH" in deep forest green/slate
draw.text((text_x, 42), "MODISH", fill=(5, 46, 22, 255), font=main_font)

# "ENTERPRISES" with elegant tracking
sub_text = "ENTERPRISES"
spacing = 6
cur_x = text_x + 4
sub_y = 138
for ch in sub_text:
    draw.text((cur_x, sub_y), ch, fill=(21, 128, 61, 230), font=sub_font)
    ch_box = sub_font.getbbox(ch)
    ch_w = ch_box[2] - ch_box[0]
    cur_x += ch_w + spacing

# Crop full logo to actual content bbox with 20px padding
f_box = logo_full.getbbox()
pad = 20
crop_box = (
    max(0, f_box[0] - pad),
    max(0, f_box[1] - pad),
    min(LW, f_box[2] + pad),
    min(LH, f_box[3] + pad),
)
logo_full_cropped = logo_full.crop(crop_box)

# Target directories
dirs = [STATIC_IMG, DEPLOY_IMG]
for d in dirs:
    os.makedirs(d, exist_ok=True)
    # Save mark
    canvas_mark.save(os.path.join(d, "ekkaa-mark.png"))
    canvas_mark.save(os.path.join(d, "modish-mark.png"))
    # Save full logo
    logo_full_cropped.save(os.path.join(d, "ekkaa-logo-full.png"))
    logo_full_cropped.save(os.path.join(d, "modish-logo-full.png"))
    # Save favicon png
    favicon_64.save(os.path.join(d, "favicon.png"))
    # Save favicon ico
    favicon_64.save(
        os.path.join(d, "favicon.ico"),
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64)],
    )
    print(f"Saved all brand assets -> {d}")

# Also root favicon.ico in static/
root_ico = os.path.join(ROOT, "static", "favicon.ico")
favicon_64.save(
    root_ico,
    format="ICO",
    sizes=[(16, 16), (32, 32), (48, 48), (64, 64)],
)

print("\n--- Summary of Generated Assets ---")
for f in ["ekkaa-mark.png", "ekkaa-logo-full.png", "favicon.png", "favicon.ico", "modish-mark.png", "modish-logo-full.png"]:
    p = os.path.join(STATIC_IMG, f)
    if os.path.exists(p):
        print(f"  {f}: {os.path.getsize(p)} bytes")

print("ALL BRAND ASSETS SUCCESSFULLY GENERATED!")
