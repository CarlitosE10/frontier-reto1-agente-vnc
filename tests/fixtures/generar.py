"""Genera capturas sintéticas de un formulario tipo SIGECOM para las pruebas de percepción.

Mientras no haya capturas reales, estas imitan una interfaz legacy de 1280×800: etiquetas con
tildes y ñ, valores en campos de texto, botones, un diálogo de confirmación y una tabla de
resultados, con texto de 12 a 14 px. Junto a cada PNG se escribe un JSON con el texto y el
recuadro de cada elemento, para que las pruebas no dependan de coordenadas escritas a mano.

Los PNG quedan versionados: las pruebas no necesitan estas fuentes. Para regenerarlos:

    uv run python tests/fixtures/generar.py
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FIXTURES = Path(__file__).resolve().parent
SIZE = (1280, 800)

# Primera fuente que exista: macOS y luego Linux.
FONTS = {
    "sans": [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
    "sans-bold": [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    "legacy": [
        "/System/Library/Fonts/Supplemental/Tahoma.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
    "legacy-bold": [
        "/System/Library/Fonts/Supplemental/Tahoma Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
}

CLIENTE = {
    "Razón social:": "Papelería Los Andes",
    "NIT:": "901234567",
    "Teléfono:": "3157654321",
    "Dirección:": "Calle 45 # 12-30",
    "Ciudad:": "Bogotá",
    "Correo electrónico:": "compras@papeleria.co",
}
CATEGORIAS = ["Papelería", "Ferretería", "Droguería"]


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for path in FONTS[name]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise FileNotFoundError(f"No hay ninguna fuente para {name!r}: {FONTS[name]}")


class Screen:
    """Lienzo que recuerda el recuadro de cada texto que dibuja."""

    def __init__(self) -> None:
        self.image = Image.new("RGB", SIZE, "#ECE9D8")
        self.draw = ImageDraw.Draw(self.image)
        self.elements: list[dict] = []

    def text(self, xy, text, face, size, fill="#000000", kind=None, anchor="la") -> None:
        typeface = font(face, size)
        self.draw.text(xy, text, font=typeface, fill=fill, anchor=anchor)
        if kind:
            box = self.draw.textbbox(xy, text, font=typeface, anchor=anchor)
            self.elements.append({"texto": text, "tipo": kind, "box": list(box)})

    def button(self, box, label, primary=False, face="sans-bold", size=14) -> None:
        # Primario: texto blanco sobre azul. Secundario: texto negro sobre gris.
        if primary:
            fill, outline, ink = "#2E6DA4", "#1F4E79", "#FFFFFF"
        else:
            fill, outline, ink = "#E1E1E1", "#8A8A8A", "#000000"
        self.draw.rounded_rectangle(box, radius=3, fill=fill, outline=outline)
        center = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        self.text(center, label, face, size, fill=ink, kind="boton", anchor="mm")

    def save(self, name: str) -> None:
        self.image.save(FIXTURES / f"{name}.png", optimize=True)
        data = {"tamano": list(SIZE), "elementos": self.elements}
        (FIXTURES / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def formulario(values: dict[str, str]) -> Screen:
    screen = Screen()
    draw = screen.draw

    # Barra de título y menú
    draw.rectangle((0, 0, SIZE[0], 32), fill="#1F3A5F")
    screen.text((16, 9), "SIGECOM · Sistema de Gestión Comercial", "sans-bold", 14, "#FFFFFF")
    screen.text((1000, 9), "Fecha: 10/10/2026", "sans", 13, "#FFFFFF", kind="fecha")
    draw.rectangle((0, 32, SIZE[0], 58), fill="#D6D3C4")
    x = 16
    for item in ["Clientes", "Facturas", "Pedidos", "Reportes", "Ayuda"]:
        screen.text((x, 38), item, "sans", 13, kind="menu")
        x += draw.textlength(item, font=font("sans", 13)) + 28

    # Panel del formulario
    draw.rectangle((240, 90, 1040, 690), fill="#FFFFFF", outline="#A0A0A0")
    draw.rectangle((240, 90, 1040, 124), fill="#E4E8EE", outline="#A0A0A0")
    screen.text((256, 99), "Nuevo cliente", "sans-bold", 16, kind="titulo")

    y = 156
    for label, value in values.items():
        screen.text((280, y + 5), label, "sans", 13, kind="etiqueta")
        draw.rectangle((460, y, 900, y + 26), fill="#FFFFFF", outline="#7A7A7A")
        screen.text((466, y + 7), value, "sans", 12, kind="valor")
        y += 46

    screen.text((280, y + 5), "Categoría:", "sans", 13, kind="etiqueta")
    x = 460
    for index, name in enumerate(CATEGORIAS):
        draw.ellipse((x, y + 6, x + 14, y + 20), fill="#FFFFFF", outline="#555555")
        if index == 0:
            draw.ellipse((x + 4, y + 10, x + 10, y + 16), fill="#1F1F1F")
        screen.text((x + 20, y + 6), name, "sans", 13, kind="opcion")
        x += 140

    screen.button((620, 600, 720, 632), "Guardar", primary=True)
    screen.button((760, 600, 860, 632), "Cancelar")

    # Barra de estado
    draw.rectangle((0, 776, SIZE[0], SIZE[1]), fill="#D6D3C4")
    screen.text((16, 781), "Listo · 12 clientes registrados", "sans", 12, kind="estado")
    return screen


def confirmacion() -> Screen:
    screen = formulario(CLIENTE)
    # Velo sobre el formulario, como lo haría una ventana modal
    veil = Image.new("RGB", SIZE, "#000000")
    screen.image = Image.blend(screen.image, veil, 0.35)
    screen.draw = ImageDraw.Draw(screen.image)
    screen.elements = []

    draw = screen.draw
    draw.rectangle((440, 300, 840, 470), fill="#F4F4F4", outline="#5A5A5A", width=2)
    draw.rectangle((440, 300, 840, 326), fill="#1F3A5F")
    screen.text((452, 306), "Confirmación", "legacy-bold", 13, "#FFFFFF", kind="titulo")
    screen.text((464, 352), "¿Desea guardar el cliente", "legacy", 13, kind="mensaje")
    screen.text((464, 374), "Papelería Los Andes?", "legacy", 13, kind="mensaje")
    screen.button((540, 420, 620, 450), "Sí", primary=True, face="legacy-bold", size=13)
    screen.button((660, 420, 740, 450), "No", face="legacy-bold", size=13)
    return screen


CLIENTES = [
    ("CL-0003", "Ana Torres", "52345678", "Pereira", "3104567890"),
    ("CL-0007", "Distribuciones El Faro", "900765432", "Medellín", "6045551234"),
    ("CL-0011", "Ana Torres", "1019876543", "Bogotá", "3157654321"),
    ("CL-0012", "Ferretería Ruiz", "800123456", "Cali", "6023334455"),
]


def lista_clientes() -> Screen:
    """Resultado de una búsqueda en una tabla con bordes, filas alternas y encabezado oscuro."""
    screen = formulario(CLIENTE)
    draw = screen.draw
    draw.rectangle((0, 59, SIZE[0], 775), fill="#ECE9D8")
    screen.elements = [e for e in screen.elements if e["tipo"] in ("fecha", "menu")]

    screen.text((40, 80), "Clientes", "sans-bold", 16, kind="titulo")
    screen.text((40, 116), "Buscar:", "sans", 13, kind="etiqueta")
    draw.rectangle((100, 110, 400, 136), fill="#FFFFFF", outline="#7A7A7A")
    screen.text((106, 117), "Ana Torres", "sans", 12, kind="valor")
    screen.button((416, 108, 506, 138), "Buscar", primary=True, size=13)

    columns = [
        ("Código", 40),
        ("Nombre", 160),
        ("Documento", 420),
        ("Ciudad", 580),
        ("Teléfono", 760),
    ]
    right = 960
    top, row = 160, 28
    draw.rectangle((40, top, right, top + row), fill="#1F3A5F")
    for name, x in columns:
        screen.text((x + 8, top + 7), name, "sans-bold", 13, "#FFFFFF", kind="encabezado")
    for index, values in enumerate(CLIENTES):
        y = top + row * (index + 1)
        draw.rectangle((40, y, right, y + row), fill="#FFFFFF" if index % 2 == 0 else "#F1F4F8")
        for (_, x), value in zip(columns, values, strict=True):
            screen.text((x + 8, y + 8), value, "sans", 12, kind="celda")
    bottom = top + row * (len(CLIENTES) + 1)
    for y in range(top, bottom + 1, row):
        draw.line((40, y, right, y), fill="#B0B0B0")
    for x in [x for _, x in columns] + [right]:
        draw.line((x, top, x, bottom), fill="#B0B0B0")
    screen.text((40, bottom + 14), "4 resultados", "sans", 12, kind="estado")
    return screen


def main() -> None:
    formulario(CLIENTE).save("formulario_cliente")
    formulario({**CLIENTE, "Teléfono:": "3014445566"}).save("formulario_cliente_editado")
    confirmacion().save("confirmacion")
    lista_clientes().save("lista_clientes")


if __name__ == "__main__":
    main()
