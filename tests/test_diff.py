"""Comparación de capturas (T04)."""

from pathlib import Path

from PIL import Image

from app.perception.diff import changed_pixels

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> Image.Image:
    with Image.open(FIXTURES / f"{name}.png") as image:
        return image.convert("RGB")


def test_identical_screens_have_no_changes():
    screen = load("formulario_cliente")
    assert changed_pixels(screen, screen) == 0
    assert changed_pixels(screen, load("formulario_cliente")) == 0


def test_a_changed_field_is_counted_and_nothing_else():
    before, after = load("formulario_cliente"), load("formulario_cliente_editado")
    assert changed_pixels(before, after) > 0

    # Solo cambió el valor del teléfono (campo en x 460–900, y 248–274)
    field = (460, 248, 901, 275)
    above = (0, 0, 1280, field[1])
    below = (0, field[3], 1280, 800)
    for box in (above, below):
        assert changed_pixels(before.crop(box), after.crop(box)) == 0
    assert changed_pixels(before.crop(field), after.crop(field)) == changed_pixels(before, after)


def test_counts_each_changed_pixel_once():
    before = Image.new("RGB", (10, 10), "white")
    after = before.copy()
    after.putpixel((0, 0), (0, 0, 0))  # cambian los tres canales
    after.putpixel((5, 5), (255, 254, 255))  # cambia uno solo
    after.putpixel((9, 9), (10, 20, 30))
    assert changed_pixels(before, after) == 3


def test_ignores_the_image_mode():
    screen = load("formulario_cliente")
    assert changed_pixels(screen, screen.convert("RGBA")) == 0


def test_a_new_resolution_counts_as_a_full_change():
    small = Image.new("RGB", (800, 600), "white")
    large = Image.new("RGB", (1280, 800), "white")
    assert changed_pixels(small, large) == 1280 * 800
