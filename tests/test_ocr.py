"""OCR sobre capturas sintéticas de formulario (T04).

Las capturas y sus recuadros salen de `tests/fixtures/generar.py`. Se saltan si Tesseract o el
paquete `spa` no están instalados.
"""

import json
import shutil
import subprocess
from functools import cache
from pathlib import Path

import pytest
from PIL import Image

from app.perception.ocr import read_text, words_near

FIXTURES = Path(__file__).parent / "fixtures"


def _has_spanish_tesseract() -> bool:
    if shutil.which("tesseract") is None:
        return False
    langs = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True)
    return "spa" in langs.stdout.split()


pytestmark = pytest.mark.skipif(
    not _has_spanish_tesseract(), reason="requiere Tesseract con el idioma spa"
)


@cache
def screen(name: str) -> Image.Image:
    with Image.open(FIXTURES / f"{name}.png") as image:
        return image.convert("RGB")


@cache
def elements(name: str) -> dict[str, dict]:
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return {element["texto"]: element for element in data["elementos"]}


def center(name: str, text: str) -> tuple[int, int]:
    left, top, right, bottom = elements(name)[text]["box"]
    return (left + right) // 2, (top + bottom) // 2


def padded(name: str, text: str, pad: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = elements(name)[text]["box"]
    return left - pad, top - pad, right + pad, bottom + pad


def test_read_text_recognizes_labels_values_and_buttons():
    text = read_text(screen("formulario_cliente"))
    for expected in [
        "Nuevo cliente",
        "Razón social: Papelería Los Andes",
        "Teléfono: 3157654321",
        "Dirección:",
        "Ciudad: Bogotá",
        "Correo electrónico:",
        "Categoría:",
        "Ferretería",
        "Droguería",
        "Guardar",
        "Cancelar",
        "Fecha: 10/10/2026",
    ]:
        assert expected in text


def test_read_text_finds_the_buttons_of_a_dialog():
    text = read_text(screen("confirmacion"))
    assert "¿Desea guardar el cliente" in text
    assert "Papelería Los Andes?" in text
    assert "Sí" in text.split()
    assert "No" in text.split()


def test_read_text_keeps_each_table_row_on_one_line():
    lines = read_text(screen("lista_clientes")).splitlines()
    assert "CL-0003 Ana Torres 52345678 Pereira 3104567890" in lines
    assert "CL-0011 Ana Torres 1019876543 Bogotá 3157654321" in lines


@pytest.mark.parametrize("label", ["Teléfono:", "Dirección:", "Razón social:", "Categoría:"])
def test_read_text_of_a_region(label):
    assert read_text(screen("formulario_cliente"), padded("formulario_cliente", label, 4)) == label


@pytest.mark.parametrize("button", ["Guardar", "Cancelar"])
def test_read_text_of_a_button_with_its_border(button):
    # Sin normalizar, Tesseract descarta el texto encerrado en el borde del botón
    box = padded("formulario_cliente", button, 30)
    assert read_text(screen("formulario_cliente"), box) == button


def test_read_text_of_a_region_outside_the_screen_is_empty():
    assert read_text(screen("formulario_cliente"), (1300, 0, 1400, 50)) == ""


FORM_TARGETS = [
    text
    for text, element in elements("formulario_cliente").items()
    if element["tipo"] in ("etiqueta", "boton", "opcion", "menu")
]


@pytest.mark.parametrize("text", FORM_TARGETS)
def test_words_near_the_center_of_a_form_element(text):
    first_word = text.split()[0].rstrip(":")
    words = words_near(screen("formulario_cliente"), *center("formulario_cliente", text))
    assert first_word in words


@pytest.mark.parametrize("button", ["Sí", "No"])
def test_words_near_the_buttons_of_a_dialog(button):
    assert button in words_near(screen("confirmacion"), *center("confirmacion", button))


def test_words_near_a_button_start_with_it_and_skip_the_next_one():
    words = words_near(screen("formulario_cliente"), *center("formulario_cliente", "Guardar"))
    assert words[0] == "Guardar"
    assert "Cancelar" not in words


def test_words_near_respect_the_radius():
    # Punto a 60 px a la derecha de la etiqueta, en el espacio antes del campo
    _, top, right, bottom = elements("formulario_cliente")["Teléfono:"]["box"]
    point = (right + 60, (top + bottom) // 2)
    image = screen("formulario_cliente")
    assert words_near(image, *point, radius=40) == []
    assert "Teléfono" in words_near(image, *point, radius=80)


def test_words_near_an_empty_area():
    assert words_near(screen("formulario_cliente"), 1150, 500) == []
