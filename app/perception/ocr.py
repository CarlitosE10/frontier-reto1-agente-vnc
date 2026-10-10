"""OCR con Tesseract en español.

Tesseract está hecho para páginas impresas y en una interfaz pierde justo lo que más importa:
el texto claro sobre fondo oscuro (botones primarios, barras de título) y el texto encerrado en
un recuadro (botones, campos, celdas), que descarta como si fuera una imagen. Por eso, antes de
leer, la captura se normaliza:

1. Se estima el color de fondo de cada zona con una mediana sobre una muestra dispersa de
   píxeles. La interfaz es de colores planos y el texto es minoría, así que la mediana es el
   fondo.
2. La "tinta" es la distancia de cada píxel a su fondo, en negro sobre blanco. Así un texto
   blanco sobre azul queda igual que uno negro sobre blanco, y los rellenos desaparecen.
3. Se borran las corridas largas de tinta (bordes de botones, campos y tablas), que ninguna
   letra de 12–16 px alcanza, junto con 2 px alrededor para llevarse las esquinas redondeadas.

Después la imagen se escala 2× y se lee con el idioma `spa`.

Límites conocidos: a 12 px, `#` y `@` suelen salir como `+` o `(H`, y los títulos en negrita
de 16 px o más pueden perder alguna letra.
"""

import numpy as np
import pytesseract
from PIL import Image, ImageFilter

LANG = "spa"
SCALE = 2
# psm 4 lee por renglones: mantiene juntos etiqueta y valor, y las celdas de una fila de tabla.
_PAGE_CONFIG = "--psm 4"
# psm 11 busca texto disperso: encuentra botones y palabras sueltas en un recorte.
_SPARSE_CONFIG = "--psm 11"

# Fondo: un píxel de cada 4×4 y mediana de 5×5 muestras (~20 px). Una ventana más grande se
# come las barras delgadas (menús, títulos) y deja manchas que se leen como letras.
_BG_STEP = 4
_BG_MEDIAN = 5
# Tinta plena desde 128 de diferencia con el fondo
_INK_GAIN = 2
# Una corrida de al menos estas longitudes, con 32 o más de diferencia, es una línea
_LINE_H = 40
_LINE_V = 24
_LINE_MIN_DIFF = 32
_LINE_PAD = 2
# words_near lee una región más ancha que el radio para no cortar las palabras del borde
_NEAR_MARGIN_X = 160
_NEAR_MARGIN_Y = 24
# Se recorta de los extremos de cada palabra: puntuación y restos de bordes
_STRIP = " \t:;,.¿?¡!()[]{}|\"'«»—–-_*=+"


def read_text(image: Image.Image, box: tuple[int, int, int, int] | None = None) -> str:
    """Texto de la captura, o de la región `box` (izquierda, arriba, derecha, abajo), por
    renglones."""
    page = _normalize(image)
    if box is not None:
        box = _clamp(box, page.size)
        if box[0] >= box[2] or box[1] >= box[3]:
            return ""
        page = page.crop(box)
    text = pytesseract.image_to_string(_upscale(page), lang=LANG, config=_PAGE_CONFIG)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def words_near(image: Image.Image, x: int, y: int, radius: int = 40) -> list[str]:
    """Palabras cuyo recuadro queda a `radius` píxeles o menos de (x, y), de la más cercana a
    la más lejana. Un recuadro que contiene el punto está a distancia 0."""
    left, top, right, bottom = _clamp(
        (
            x - radius - _NEAR_MARGIN_X,
            y - radius - _NEAR_MARGIN_Y,
            x + radius + _NEAR_MARGIN_X + 1,
            y + radius + _NEAR_MARGIN_Y + 1,
        ),
        image.size,
    )
    if left >= right or top >= bottom:
        return []
    region = _normalize(image).crop((left, top, right, bottom))
    data = pytesseract.image_to_data(
        _upscale(region), lang=LANG, config=_SPARSE_CONFIG, output_type=pytesseract.Output.DICT
    )

    found: list[tuple[float, str]] = []
    for text, conf, word_left, word_top, width, height in zip(
        data["text"],
        data["conf"],
        data["left"],
        data["top"],
        data["width"],
        data["height"],
        strict=True,
    ):
        word = text.strip(_STRIP)
        if not word or float(conf) < 0:
            continue
        word_box = (
            left + word_left / SCALE,
            top + word_top / SCALE,
            left + (word_left + width) / SCALE,
            top + (word_top + height) / SCALE,
        )
        distance = _distance(x, y, word_box)
        if distance <= radius:
            found.append((distance, word))
    found.sort(key=lambda item: item[0])  # estable: los empates quedan en orden de lectura
    return [word for _, word in found]


def _normalize(image: Image.Image) -> Image.Image:
    """Tinta negra sobre blanco, sin rellenos ni líneas largas (ver el docstring del módulo)."""
    gray = image.convert("L")
    sample = gray.resize(
        (max(1, gray.width // _BG_STEP), max(1, gray.height // _BG_STEP)),
        Image.Resampling.NEAREST,
    )
    if min(sample.size) >= _BG_MEDIAN:
        sample = sample.filter(ImageFilter.MedianFilter(_BG_MEDIAN))
    background = np.asarray(sample.resize(gray.size, Image.Resampling.NEAREST), dtype=np.int16)

    diff = np.abs(np.asarray(gray, dtype=np.int16) - background)
    faint = diff >= _LINE_MIN_DIFF
    lines = _long_runs(faint, _LINE_H, axis=1) | _long_runs(faint, _LINE_V, axis=0)
    lines = Image.fromarray(lines.astype(np.uint8) * 255).filter(
        ImageFilter.MaxFilter(2 * _LINE_PAD + 1)
    )
    ink = np.clip(diff * _INK_GAIN, 0, 255)
    ink[np.asarray(lines) > 0] = 0
    return Image.fromarray((255 - ink).astype(np.uint8))


def _long_runs(mask: np.ndarray, length: int, axis: int) -> np.ndarray:
    """Marca los píxeles de `mask` que forman parte de una corrida de al menos `length`."""
    runs = np.moveaxis(mask, axis, -1)
    n = runs.shape[-1]
    if n < length:
        return np.zeros_like(mask)
    zero = np.zeros(runs.shape[:-1] + (1,), dtype=np.int32)
    total = np.concatenate([zero, np.cumsum(runs, axis=-1, dtype=np.int32)], axis=-1)
    # full[i]: la ventana [i, i + length) está toda marcada
    full = (total[..., length:] - total[..., :-length]) == length
    starts = np.concatenate([zero, np.cumsum(full, axis=-1, dtype=np.int32)], axis=-1)
    # El píxel j está cubierto si alguna ventana completa empieza entre j - length + 1 y j
    j = np.arange(n)
    first = np.maximum(j - length + 1, 0)
    last = np.minimum(j, n - length)
    covered = starts[..., last + 1] - starts[..., first] > 0
    return np.moveaxis(covered, -1, axis)


def _upscale(image: Image.Image) -> Image.Image:
    return image.resize((image.width * SCALE, image.height * SCALE), Image.Resampling.LANCZOS)


def _clamp(box: tuple[int, int, int, int], size: tuple[int, int]) -> tuple[int, int, int, int]:
    width, height = size
    left, top, right, bottom = box
    return (
        min(max(left, 0), width),
        min(max(top, 0), height),
        min(max(right, 0), width),
        min(max(bottom, 0), height),
    )


def _distance(x: float, y: float, box: tuple[float, float, float, float]) -> float:
    """Distancia del punto al recuadro; 0 si el punto está adentro."""
    left, top, right, bottom = box
    dx = max(left - x, 0, x - right)
    dy = max(top - y, 0, y - bottom)
    return float(np.hypot(dx, dy))
