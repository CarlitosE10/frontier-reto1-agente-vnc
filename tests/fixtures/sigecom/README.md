# Capturas reales de SIGECOM

Tomadas el 10/10/2026 del escritorio propio con `DesktopSession` (`python -m app.vnc.demo`). Son de 1280×800, en RGB y sin cursor (el cursor llega aparte por VNC y no se dibuja). La app muestra `Hoy: 14/10/2026 · Usuario: operador2` en la barra superior. Ninguna captura tiene cambios sin guardar ni ventanas emergentes.

| Archivo | Pantalla | Qué se ve |
|---|---|---|
| `clientes-lista.png` | Comercial › Maestros › Clientes | Filtros `Nombre`, `NIT`, `Ciudad` (`Todos`), botones `Buscar`, `Limpiar`, `Nuevo cliente`, `Exportar`. Tabla con `Código`, `Razón social o nombre`, `NIT`, `Ciudad`, `Teléfono`, `Estado`; primera fila `CL-0065 · Abarrotes Gomez S.A.S. · 825016886 · Bogotá`. Paginación `Anterior` (deshabilitado), `Página 1`, `Siguiente` |
| `clientes-busqueda-ana-torres.png` | Clientes, buscando `Ana Torres` | Los homónimos de E5: `CL-0005 · Ana Torres · 52345678 · Bogotá · 3112223344` y `CL-0031 · Ana Torres · 1019876543 · Cali · 3209998877` |
| `cliente-nuevo.png` | Clientes › Nuevo cliente | Formulario vacío: `Razón social o nombre *`, `NIT *`, `Teléfono *`, `Ciudad *` (`(seleccione)`), `Dirección`, `Correo`, `Estado` (`Activo`), `Observaciones`, botones `Guardar` y `Volver` |
| `cliente-cl-0005.png` | Cliente CL-0005 (abierto desde la búsqueda) | El mismo formulario con datos: `Ana Torres`, `52345678`, `3112223344`, `Bogotá`, `Calle 93 # 37-94`, `Activo` |
| `facturas-lista.png` | Cartera › Facturas | Filtros `Cliente` y `Estado` (`Todos`), `Buscar`, `Limpiar`, `Exportar`. Tabla con `Código`, `Cliente`, `Fecha`, `Vence`, `Valor`, `Estado`; primera fila `FV-10159 · Distribuciones Gómez La 14 · 01/03/2026 · 31/03/2026 · 1.810.000 · Vencida`. Estados visibles: `Vencida`, `Pendiente`, `Pagada`, `Anulada` |
