"""OCR con Tesseract en español (se implementa en T04)."""

from PIL import Image


def read_text(image: Image.Image, box: tuple[int, int, int, int] | None = None) -> str:
    raise NotImplementedError


def words_near(image: Image.Image, x: int, y: int, radius: int = 40) -> list[str]:
    raise NotImplementedError
