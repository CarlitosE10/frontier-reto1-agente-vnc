"""Comparación de capturas."""

import numpy as np
from PIL import Image


def changed_pixels(a: Image.Image, b: Image.Image) -> int:
    """Cuántos píxeles difieren en algún canal entre dos capturas.

    Si los tamaños no coinciden (la resolución cambió), toda la pantalla cuenta como cambiada.
    """
    if a.size != b.size:
        return max(a.width * a.height, b.width * b.height)
    pixels_a = np.asarray(a.convert("RGB"))
    pixels_b = np.asarray(b.convert("RGB"))
    return int(np.any(pixels_a != pixels_b, axis=-1).sum())
