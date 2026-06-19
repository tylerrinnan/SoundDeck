"""make_icon.py — generates sounddeck.ico for the build (and provides make_icon() for tray.py)."""
from PIL import Image, ImageDraw


def make_icon(size: int = 64) -> Image.Image:
    """Return a SoundDeck logo as an RGBA PIL Image."""
    img    = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d      = ImageDraw.Draw(img)
    accent = (124, 92, 245, 255)
    dark   = (20, 20, 32, 255)
    d.ellipse([2, 2, size - 3, size - 3], fill=dark)
    d.rectangle([14, 22, 26, 42], fill=accent)
    points = [(26, 18), (42, 10), (42, 54), (26, 46)]
    d.polygon(points, fill=accent)
    for r, a in [(6, 200), (10, 160), (14, 120)]:
        d.arc([42-r, 32-r, 42+r, 32+r], start=-50, end=50,
              fill=(*accent[:3], a), width=2)
    return img


if __name__ == "__main__":
    img = make_icon()
    sizes = [16, 32, 48, 64]
    imgs  = [img.resize((s, s), Image.Resampling.LANCZOS) for s in sizes]
    imgs[0].save("sounddeck.ico", format="ICO",
                 sizes=[(s, s) for s in sizes],
                 append_images=imgs[1:])
    print("  Icon saved: sounddeck.ico")
