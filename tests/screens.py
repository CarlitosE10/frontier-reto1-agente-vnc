"""Capturas sintéticas de SIGECOM hechas con PIL, mientras no haya capturas reales."""

from PIL import Image, ImageDraw, ImageFont

SIZE = (1280, 800)
BACKGROUND = (236, 236, 236)
TITLE_BAR = (40, 70, 120)
BUTTON = (40, 120, 60)

# Fuentes con tildes y ñ en macOS y en Debian; la de PIL no trae la «é».
_FONTS = ["Arial.ttf", "Helvetica.ttc", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]


def font(size: int = 18) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in _FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _window(title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, SIZE[0], 40), fill=TITLE_BAR)
    draw.text((16, 10), title, fill="white", font=font())
    return image, draw


def _field(draw: ImageDraw.ImageDraw, top: int, label: str, value: str = "") -> None:
    draw.text((80, top + 8), label, fill="black", font=font())
    draw.rectangle((240, top, 700, top + 36), fill="white", outline=(150, 150, 150))
    draw.text((250, top + 8), value, fill="black", font=font())


def _button(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], label: str) -> None:
    draw.rectangle(box, fill=BUTTON)
    width = draw.textlength(label, font=font())
    draw.text(((box[0] + box[2] - width) / 2, box[1] + 12), label, fill="white", font=font())


def new_client_form() -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Formulario vacío de cliente nuevo; devuelve la imagen y el recuadro del botón Guardar."""
    image, draw = _window("SIGECOM · Clientes · Nuevo cliente")
    for row, label in enumerate(["Nombre", "NIT", "Teléfono", "Ciudad"]):
        _field(draw, 100 + row * 60, label)
    button = (560, 360, 700, 404)
    _button(draw, button, "Guardar")
    return image, button
