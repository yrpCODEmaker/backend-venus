# Descarga de Facturas — PDF y PNG

## Descripción

Este módulo implementa la generación y descarga de facturas en formato PDF y PNG directamente desde el backend. Ambos formatos son visualmente idénticos y generados server-side.

## Archivos Creados / Modificados

| Archivo | Acción |
|---------|--------|
| `company_config.json` | Nuevo — configuración editable de empresa |
| `templates/invoice.html` | Nuevo — template Jinja2 de la factura |
| `services/invoice_pdf_service.py` | Nuevo — lógica de generación |
| `routers/operacional.py` | Modificado — 2 endpoints de descarga agregados |
| `config.py` | Modificado — función `get_company_config()` |
| `requirements.txt` | Modificado — dependencias de generación |
| `tests/test_invoice_download.py` | Nuevo — 13 tests de cobertura |

---

## Configuración de Empresa (`company_config.json`)

La información de empresa se centraliza en el archivo `company_config.json` en la raíz del proyecto. **No se requiere tocar el código** para cambiar estos datos.

```json
{
  "nombre": "Venus Muebles",
  "logo_path": null,
  "ubicacion": "Santo Domingo, República Dominicana",
  "telefono": "+1 (809) 000-0000",
  "rnc": null
}
```

### Campos

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `nombre` | string | Nombre de la empresa (requerido) |
| `logo_path` | string \| null | Ruta absoluta o URL del logo. Si es `null`, se muestra la inicial del nombre |
| `ubicacion` | string | Dirección o ciudad de la empresa |
| `telefono` | string | Número telefónico visible en la factura |
| `rnc` | string \| null | RNC de la empresa. **Si es `null` o vacío, no aparece mención del RNC en la factura** |

---

## Endpoints

### `GET /api/v1/facturas/{factura_id}/download/pdf`

Descarga la factura en formato PDF.

**Autenticación:** JWT requerido (`facturas_ver`)

**Respuesta exitosa:**
- `Content-Type: application/pdf`
- `Content-Disposition: attachment; filename="factura_{id}.pdf"`
- Cuerpo: bytes del PDF

---

### `GET /api/v1/facturas/{factura_id}/download/png`

Descarga la factura en formato PNG (imagen de alta resolución, 150 DPI).

**Autenticación:** JWT requerido (`facturas_ver`)

**Respuesta exitosa:**
- `Content-Type: image/png`
- `Content-Disposition: attachment; filename="factura_{id}.png"`
- Cuerpo: bytes del PNG

---

## Contenido de la Factura

Ambos documentos muestran:

1. **Cabecera de empresa**: Logo/inicial, nombre, ubicación, teléfono, RNC (si existe)
2. **Identificación de factura**: ID único y fecha
3. **Datos del cliente**: Nombre completo, teléfono (si disponible), dirección de entrega
4. **Badges informativos**: "Entrega a domicilio", "Garantía: X meses"
5. **Tabla de artículos**: Número, nombre, material, color/tela, tipo (stock/encargo), cantidad, subtotal
6. **Resumen financiero**: Subtotal, monto pagado, total, saldo pendiente
7. **Footer**: Empresa y fecha de generación del documento

---

## Arquitectura de Generación

### Motor Dual (automático)

El servicio intenta generar el PDF/PNG en orden de preferencia:

```
generate_invoice_pdf():
  1. WeasyPrint (mejor calidad) ─── requiere Cairo/GTK (Linux/Docker)
  2. xhtml2pdf (fallback)       ─── puro Python, sin dependencias del sistema

generate_invoice_png():
  1. WeasyPrint write_png()     ─── requiere Cairo/GTK
  2. pdf2image + Poppler        ─── requiere Poppler instalado
  3. pypdfium2 (recomendado)    ─── sin dependencias del sistema, cross-platform
```

El cambio entre motores es transparente para los endpoints — siempre retornan el mismo resultado.

### Flujo de Datos

```
GET /facturas/{id}/download/pdf
     │
     ├─ Consulta factura (JOIN con clientes)
     ├─ Obtiene ítems por items_id CSV o factura_id
     ├─ Carga company_config.json (get_company_config())
     ├─ build_invoice_context() → dict Jinja2
     ├─ _render_invoice_html()  → HTML string
     ├─ generate_invoice_pdf()  → bytes PDF
     └─ StreamingResponse(bytes, media_type="application/pdf")
```

---

## Dependencias del Sistema

### Para Docker/Linux (producción)

```dockerfile
RUN apt-get install -y \
    libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0 \
    libfontconfig1 libcairo2
```

Esto habilita WeasyPrint para el mejor rendimiento.

### Para Windows (desarrollo)

No se requiere instalación de sistema. El fallback `xhtml2pdf` + `pypdfium2` funciona sin dependencias adicionales.

---

## Tests

```
tests/test_invoice_download.py — 13 tests
  TestBuildInvoiceContext (3)
    - test_cliente_nombre_desde_join
    - test_cliente_nombre_desde_json_embebido
    - test_rnc_none_in_context

  TestRenderTemplate (3)
    - test_html_renders_without_error
    - test_rnc_not_in_html_when_none
    - test_rnc_in_html_when_set

  TestDownloadEndpoints (7)
    - test_download_pdf_returns_200_with_pdf_bytes
    - test_download_png_returns_200_with_png_bytes
    - test_download_pdf_404_for_missing_factura
    - test_download_png_404_for_missing_factura
    - test_download_requires_auth
    - test_pdf_content_disposition_header
    - test_png_content_disposition_header
```
