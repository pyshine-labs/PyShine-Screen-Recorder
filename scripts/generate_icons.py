#!/usr/bin/env python3
"""Generate app icons and MSIX assets for Screen Recorder."""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

# Colors
BG_COLOR = (30, 30, 40)
SCREEN_COLOR = (50, 120, 200)
SCREEN_BG = (20, 20, 30)
RECORD_RED = (230, 40, 50)
TEXT_COLOR = (255, 255, 255)
TILE_BG = (30, 60, 120)

def create_icon(size: int) -> Image.Image:
    """Create a screen recorder icon at the given size."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size / 300.0

    # Rounded rectangle background
    margin = int(15 * s)
    radius = int(40 * s)
    draw.rounded_rectangle([margin, margin, size - margin, size - margin], radius=radius, fill=BG_COLOR)

    # Monitor shape
    sx, sy = int(45*s), int(55*s)
    sw, sh = int(210*s), int(140*s)
    sr = int(10*s)
    draw.rounded_rectangle([sx, sy, sx+sw, sy+sh], radius=sr, fill=SCREEN_COLOR)
    ib = int(8*s)
    draw.rounded_rectangle([sx+ib, sy+ib, sx+sw-ib, sy+sh-ib], radius=int(6*s), fill=SCREEN_BG)

    # Stand
    stand_w, stand_h = int(80*s), int(20*s)
    stand_x, stand_y = int(150*s) - stand_w//2, sy+sh
    draw.rectangle([stand_x, stand_y, stand_x+stand_w, stand_y+stand_h], fill=SCREEN_COLOR)
    base_w, base_h = int(120*s), int(8*s)
    base_x, base_y = int(150*s) - base_w//2, stand_y+stand_h
    draw.rounded_rectangle([base_x, base_y, base_x+base_w, base_y+base_h], radius=int(4*s), fill=SCREEN_COLOR)

    # Record dot with glow
    dot_r = int(18*s)
    dot_x, dot_y = int(150*s), int(110*s)
    glow_r = int(28*s)
    for g in range(glow_r, dot_r, -1):
        alpha = int(80 * (1 - (g - dot_r)/(glow_r - dot_r)))
        draw.ellipse([dot_x-g, dot_y-g, dot_x+g, dot_y+g], fill=(RECORD_RED[0], RECORD_RED[1], RECORD_RED[2], alpha))
    draw.ellipse([dot_x-dot_r, dot_y-dot_r, dot_x+dot_r, dot_y+dot_r], fill=RECORD_RED)
    hl_r = int(6*s)
    draw.ellipse([dot_x-dot_r+int(4*s), dot_y-dot_r+int(4*s),
                  dot_x-dot_r+int(4*s)+hl_r*2, dot_y-dot_r+int(4*s)+hl_r*2],
                 fill=(255, 255, 255, 100))
    return img

def create_tile(w: int, h: int) -> Image.Image:
    """Create a tile with icon on blue background."""
    img = Image.new('RGBA', (w, h), TILE_BG + (255,))
    icon_size = int(min(w, h) * 0.6)
    icon = create_icon(icon_size)
    ix, iy = (w - icon_size)//2, (h - icon_size)//2
    img.paste(icon, (ix, iy), icon)
    return img

def create_splash(w: int, h: int) -> Image.Image:
    """Create a splash screen."""
    img = Image.new('RGBA', (w, h), (20, 25, 40, 255))
    draw = ImageDraw.Draw(img)
    s = min(w, h) / 600.0
    icon_size = int(200*s)
    icon = create_icon(icon_size)
    ix, iy = (w-icon_size)//2, int(120*s)
    img.paste(icon, (ix, iy), icon)
    try:
        font = ImageFont.truetype("segoeui.ttf", int(36*s))
    except (IOError, OSError):
        font = ImageFont.load_default()
    text = "Screen Recorder"
    bbox = draw.textbbox((0,0), text, font=font)
    tw = bbox[2]-bbox[0]
    draw.text(((w-tw)//2, iy+icon_size+int(20*s)), text, fill=TEXT_COLOR, font=font)
    return img

def save_scaled(base_name: str, base_img: Image.Image, scales: dict, out_dir: Path, is_splash: bool = False, is_tile: bool = False):
    """Save base image and scaled variants with MSIX naming convention."""
    # scale-100 (base)
    base_img.save(out_dir / base_name, "PNG")

    for qualifier, factor in scales.items():
        w, h = int(base_img.width * factor), int(base_img.height * factor)
        if is_splash:
            scaled = create_splash(w, h)
        else:
            scaled = base_img.resize((w, h), Image.LANCZOS)
        # Insert scale qualifier before .png: name.scale-xxx.png
        name_parts = base_name.rsplit(".", 1)
        scaled_name = f"{name_parts[0]}.{qualifier}.{name_parts[1]}"
        scaled.save(out_dir / scaled_name, "PNG")

def main():
    project_root = Path(__file__).parent.parent
    msix_dir = project_root / "installer" / "msix"
    icons_dir = project_root / "resources" / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)

    # Windows ICO
    icon_sizes = [(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]
    ico_imgs = [create_icon(sz[0]) for sz in icon_sizes]
    ico_imgs[0].save(icons_dir/"app.ico", format="ICO", sizes=icon_sizes, append_images=ico_imgs[1:])
    create_icon(512).save(icons_dir/"app_512.png", "PNG")
    print(f"Created app.ico and app_512.png in {icons_dir}")

    # MSIX Assets (flat directory with scale qualifiers in filenames)
    assets_dir = msix_dir / "Assets"
    if assets_dir.exists():
        import shutil
        shutil.rmtree(assets_dir)
    assets_dir.mkdir(parents=True)

    scales = {"scale-125": 1.25, "scale-150": 1.50, "scale-200": 2.00, "scale-400": 4.00}

    # Define assets: (filename, creator_function, base_width, base_height, flags)
    assets = [
        ("Square44x44Logo.png",      create_icon, 44,  44,  {}),
        ("Square150x150Logo.png",    create_icon, 150, 150, {}),
        ("Square310x310Logo.png",    create_icon, 310, 310, {}),
        ("Wide310x150Logo.png",      create_tile, 310, 150, {"tile": True}),
        ("StoreLogo.png",            create_icon, 50,  50,  {}),
        ("BadgeLogo.png",            create_icon, 24,  24,  {}),
        ("SplashScreen.png",         create_splash, 620, 300, {"splash": True}),
        # Target-size variants for unplated icons (taskbar, etc.)
        ("Square44x44Logo.targetsize-16.png",  create_icon, 16, 16, {}),
        ("Square44x44Logo.targetsize-24.png",  create_icon, 24, 24, {}),
        ("Square44x44Logo.targetsize-32.png",  create_icon, 32, 32, {}),
        ("Square44x44Logo.targetsize-48.png",  create_icon, 48, 48, {}),
        ("Square44x44Logo.targetsize-256.png", create_icon, 256, 256, {}),
    ]

    for name, creator, w, h, flags in assets:
        if flags.get("splash"):
            img = creator(w, h)
        elif flags.get("tile"):
            img = creator(w, h)
        else:
            img = creator(w)
        # target-size assets don't need scale variants
        if "targetsize" in name:
            img.save(assets_dir / name, "PNG")
        else:
            save_scaled(name, img, scales, assets_dir,
                        is_splash=flags.get("splash", False),
                        is_tile=flags.get("tile", False))
        print(f"  Created {name}")

    count = sum(1 for f in assets_dir.iterdir() if f.is_file())
    print(f"\nMSIX assets: {count} files in {assets_dir}")

if __name__ == "__main__":
    main()
