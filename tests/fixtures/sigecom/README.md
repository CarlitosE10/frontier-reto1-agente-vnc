# Capturas reales de SIGECOM

Tomadas el 10/10/2026 del escritorio propio con `DesktopSession` (`python -m app.vnc.demo`). Son de 1280×800, en RGB y sin cursor (el cursor llega aparte por VNC y no se dibuja). La app muestra `Hoy: 14/10/2026 · Usuario: operador2` en la barra superior. Ninguna se tomó guardando ni exportando: solo se abrieron menús, listas y formularios, se filtró y se descartó un formulario sin guardar.

Las primeras cinco no tienen cambios sin guardar ni ventanas emergentes. Las de T13 suman menús y listas desplegadas, filtros aplicados, un error de validación y una ventana emergente. Los objetivos etiquetados de cada captura están en `eval/grounding/`.

| Archivo | Pantalla | Qué se ve |
|---|---|---|
| `clientes-lista.png` | Comercial › Maestros › Clientes | Filtros `Nombre`, `NIT`, `Ciudad` (`Todos`), botones `Buscar`, `Limpiar`, `Nuevo cliente`, `Exportar`. Tabla con `Código`, `Razón social o nombre`, `NIT`, `Ciudad`, `Teléfono`, `Estado`; primera fila `CL-0065 · Abarrotes Gomez S.A.S. · 825016886 · Bogotá`. Paginación `Anterior` (deshabilitado), `Página 1`, `Siguiente` |
| `clientes-busqueda-ana-torres.png` | Clientes, buscando `Ana Torres` | Los homónimos de E5: `CL-0005 · Ana Torres · 52345678 · Bogotá · 3112223344` y `CL-0031 · Ana Torres · 1019876543 · Cali · 3209998877` |
| `cliente-nuevo.png` | Clientes › Nuevo cliente | Formulario vacío: `Razón social o nombre *`, `NIT *`, `Teléfono *`, `Ciudad *` (`(seleccione)`), `Dirección`, `Correo`, `Estado` (`Activo`), `Observaciones`, botones `Guardar` y `Volver` |
| `cliente-cl-0005.png` | Cliente CL-0005 (abierto desde la búsqueda) | El mismo formulario con datos: `Ana Torres`, `52345678`, `3112223344`, `Bogotá`, `Calle 93 # 37-94`, `Activo` |
| `facturas-lista.png` | Cartera › Facturas | Filtros `Cliente` y `Estado` (`Todos`), `Buscar`, `Limpiar`, `Exportar`. Tabla con `Código`, `Cliente`, `Fecha`, `Vence`, `Valor`, `Estado`; primera fila `FV-10159 · Distribuciones Gómez La 14 · 01/03/2026 · 31/03/2026 · 1.810.000 · Vencida`. Estados visibles: `Vencida`, `Pendiente`, `Pagada`, `Anulada` |
| `menu-comercial-ventas.png` | Menú Comercial abierto sobre Facturas | Opciones `Maestros` y `Ventas` (resaltada) y el submenú de Ventas con `Pedidos`. Maestros lleva a `Clientes` |
| `pedidos-filtrados.png` | Comercial › Ventas › Pedidos, filtrado | Filtros `Cliente`, `Estado` (`Entregado`), `Fecha desde` (`01/09/2026`), `Fecha hasta` (`30/09/2026`), `Buscar`, `Limpiar`; botones `Nuevo pedido` y `Exportar`. Tabla con `Código`, `Cliente`, `Fecha`, `Estado`, `Total`; primera fila `PD-0134 · Abarrotes Moreno · 26/09/2026 · Entregado · 8.250.000`. Es el filtro de E4, sin exportar |
| `pedidos-estado-desplegado.png` | Pedidos sin filtros, con la lista de `Estado` abierta | Opciones `Todos` (resaltada), `Borrador`, `Confirmado`, `Entregado`, `Anulado`, encima de la tabla. Las fechas vacías muestran el formato `dd/mm/aaaa` |
| `cliente-nuevo-invalido.png` | Nuevo cliente con datos sin guardar | `Razón social o nombre` dice `Papelería Prueba`; `Ciudad *` en rojo con el mensaje `Dato inválido.` debajo, que corre el resto del formulario 13 px hacia abajo |
| `dialogo-descartar-cambios.png` | Ventana emergente al pulsar `Volver` con cambios | Diálogo `Descartar cambios` con `¿Descartar cambios?` y los botones `Descartar` (principal) y `No`, sobre el formulario oscurecido. Se pulsó `Descartar`: no se guardó nada |
