#!/usr/bin/env python3
"""Exporta el documento de diseño y sus diagramas a PDF y PNG.

Uso:
    python3 docs/exportar.py

Genera en docs/export/:
    diseno-sistema.pdf          documento completo (A4; los diagramas van en páginas horizontales)
    diagrama-componentes.pdf    diagrama de componentes (vectorial, recortado al contenido)
    diagrama-componentes.png    mismo diagrama en imagen (2x)
    diagrama-flujo.pdf          flujo de una tarea (vectorial)
    diagrama-flujo.png          mismo diagrama en imagen (2x)
Y actualiza docs/diagramas.html, una página que dibuja los diagramas en el navegador.

Requiere Google Chrome y conexión a internet: marked y mermaid se cargan desde jsDelivr.
"""

import functools
import json
import re
import subprocess
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = DOCS_DIR / "export"
SOURCE_MD = DOCS_DIR / "diseno-sistema.md"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MARKED_JS = "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"
MERMAID_JS = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"
# Nombre de archivo y título de cada bloque mermaid, en el orden en que aparecen en el documento.
DIAGRAM_NAMES = ["diagrama-componentes", "diagrama-flujo"]
DIAGRAM_TITLES = ["Diagrama de componentes", "Flujo de una tarea"]

VIEWER_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Diagramas de arquitectura</title>
<style>
  body {{ background: #ffffff; color: #1a1a1a; font-family: system-ui, sans-serif; margin: 0 auto; max-width: 1200px; padding: 16px; }}
  h1 {{ font-size: 1.4rem; }}
  h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
  pre.mermaid {{ background: none; overflow-x: auto; }}
</style>
</head>
<body>
<h1>Agente VNC para sistemas legacy · Diagramas</h1>
{sections}
<script src="{mermaid_js}"></script>
<script>
  mermaid.initialize({{ startOnLoad: false, theme: 'default' }});
  mermaid.run({{ querySelector: '.mermaid' }});
</script>
</body>
</html>
"""

DOCUMENT_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Diseño de sistema · Agente VNC</title>
<style>
  @page {{ size: A4; margin: 16mm 14mm; }}
  @page horizontal {{ size: A4 landscape; margin: 12mm; }}
  body {{ font: 10pt/1.45 -apple-system, "Helvetica Neue", Arial, sans-serif; color: #1a1a1a; }}
  h1 {{ font-size: 20pt; margin: 0 0 4pt; }}
  h2 {{ font-size: 14pt; margin-top: 18pt; border-bottom: 1px solid #ccc; padding-bottom: 3pt; break-after: avoid; }}
  h3 {{ font-size: 11.5pt; margin-top: 12pt; break-after: avoid; }}
  p, li {{ orphans: 3; widows: 3; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 8.5pt; margin: 6pt 0; }}
  th, td {{ border: 1px solid #ccc; padding: 3pt 5pt; vertical-align: top; text-align: left; }}
  th {{ background: #f2f2f2; }}
  tr {{ break-inside: avoid; }}
  code {{ font: 8.5pt Menlo, monospace; background: #f4f4f4; padding: 0 2pt; border-radius: 2pt; }}
  pre {{ background: #f6f6f6; padding: 6pt 8pt; font-size: 8pt; break-inside: avoid; white-space: pre-wrap; }}
  pre code {{ background: none; padding: 0; }}
  blockquote {{ border-left: 3px solid #ccc; margin: 6pt 0; padding: 2pt 10pt; color: #444; }}
  hr {{ border: 0; border-top: 1px solid #ddd; margin: 14pt 0; }}
  .diagram {{ page: horizontal; text-align: center; }}
  .diagram h3 {{ text-align: left; margin-top: 0; }}
  .diagram pre.mermaid {{ background: none; padding: 0; margin: 0; }}
</style>
</head>
<body>
<main id="content"></main>
<script type="application/json" id="markdown">{markdown_json}</script>
<script src="{marked_js}"></script>
<script src="{mermaid_js}"></script>
<script>
  const markdown = JSON.parse(document.getElementById('markdown').textContent);
  document.getElementById('content').innerHTML = marked.parse(markdown);

  // Cada diagrama va en su propia página horizontal, junto con el título que lo precede.
  document.querySelectorAll('pre > code.language-mermaid').forEach((code) => {{
    const block = code.parentElement;
    const page = document.createElement('div');
    page.className = 'diagram';
    const heading = block.previousElementSibling;
    if (heading && /^H[1-4]$/.test(heading.tagName)) page.appendChild(heading);
    const diagram = document.createElement('pre');
    diagram.className = 'mermaid';
    diagram.textContent = code.textContent;
    block.replaceWith(page);
    page.appendChild(diagram);
  }});

  mermaid.initialize({{ startOnLoad: false, theme: 'default' }});
  mermaid.run({{ querySelector: '.mermaid' }}).then(() => {{
    document.querySelectorAll('.diagram svg').forEach((svg) => {{
      svg.style.maxWidth = 'none';
      svg.style.width = '100%';
      svg.style.height = '165mm';
    }});
    document.body.dataset.ready = '1';
  }});
</script>
</body>
</html>
"""

DIAGRAM_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>{name}</title>
<style>
  html, body {{ margin: 0; background: #ffffff; }}
  #frame {{ display: inline-block; padding: 24px; }}
  pre.mermaid {{ margin: 0; }}
</style>
</head>
<body>
<div id="frame"><pre class="mermaid">{source}</pre></div>
<script src="{mermaid_js}"></script>
<script>
  mermaid.initialize({{
    startOnLoad: false,
    theme: 'default',
    flowchart: {{ useMaxWidth: false }},
    sequence: {{ useMaxWidth: false }},
  }});
  mermaid.run({{ querySelector: '.mermaid' }}).then(() => {{
    // La página PDF toma exactamente el tamaño del diagrama.
    const box = document.getElementById('frame').getBoundingClientRect();
    const width = Math.ceil(box.width);
    const height = Math.ceil(box.height);
    const pageSize = document.createElement('style');
    pageSize.textContent = `@page {{ size: ${{width}}px ${{height}}px; margin: 0; }}`;
    document.head.appendChild(pageSize);
    document.body.dataset.size = `${{width}}x${{height}}`;
    document.body.dataset.ready = '1';
  }});
</script>
</body>
</html>
"""


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def run_chrome(*args: str) -> str:
    command = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-pdf-header-footer",
        "--virtual-time-budget=20000",
        *args,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"Chrome falló ({result.returncode}): {result.stderr.strip()[-500:]}")
    return result.stdout


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def serve(directory: Path) -> ThreadingHTTPServer:
    """Sirve el directorio por HTTP local para que Chrome cargue las librerías sin restricciones de file://."""
    handler = functools.partial(QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def build_pages(markdown: str, workdir: Path) -> list[str]:
    """Escribe el HTML del documento y uno por diagrama. Devuelve los nombres de los diagramas."""
    markdown_json = json.dumps(markdown).replace("</", "<\\/")
    (workdir / "documento.html").write_text(
        DOCUMENT_TEMPLATE.format(markdown_json=markdown_json, marked_js=MARKED_JS, mermaid_js=MERMAID_JS),
        encoding="utf-8",
    )
    sources = re.findall(r"```mermaid\n(.*?)```", markdown, re.S)
    if len(sources) != len(DIAGRAM_NAMES):
        sys.exit(f"Se esperaban {len(DIAGRAM_NAMES)} diagramas en el documento y hay {len(sources)}.")
    for name, source in zip(DIAGRAM_NAMES, sources):
        (workdir / f"{name}.html").write_text(
            DIAGRAM_TEMPLATE.format(name=name, source=escape_html(source), mermaid_js=MERMAID_JS),
            encoding="utf-8",
        )
    sections = "\n".join(
        f'<section><h2>{title}</h2><pre class="mermaid">{escape_html(source)}</pre></section>'
        for title, source in zip(DIAGRAM_TITLES, sources)
    )
    (DOCS_DIR / "diagramas.html").write_text(
        VIEWER_TEMPLATE.format(sections=sections, mermaid_js=MERMAID_JS), encoding="utf-8"
    )
    return DIAGRAM_NAMES


def export_diagram(base_url: str, name: str) -> None:
    url = f"{base_url}/{name}.html"
    dom = run_chrome("--dump-dom", url)
    size = re.search(r'data-size="(\d+)x(\d+)"', dom)
    if not size:
        raise RuntimeError(f"El diagrama {name} no terminó de renderizar.")
    width, height = size.groups()
    run_chrome(
        f"--screenshot={OUTPUT_DIR / f'{name}.png'}",
        f"--window-size={width},{height}",
        "--force-device-scale-factor=2",
        url,
    )
    run_chrome(f"--print-to-pdf={OUTPUT_DIR / f'{name}.pdf'}", url)


def main() -> None:
    if not Path(CHROME).exists():
        sys.exit(f"No se encontró Google Chrome en {CHROME}.")
    OUTPUT_DIR.mkdir(exist_ok=True)
    markdown = SOURCE_MD.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        diagram_names = build_pages(markdown, workdir)
        server = serve(workdir)
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            run_chrome(f"--print-to-pdf={OUTPUT_DIR / 'diseno-sistema.pdf'}", f"{base_url}/documento.html")
            for name in diagram_names:
                export_diagram(base_url, name)
        finally:
            server.shutdown()

    for path in sorted(OUTPUT_DIR.iterdir()):
        print(f"{path.relative_to(DOCS_DIR.parent)}  ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
