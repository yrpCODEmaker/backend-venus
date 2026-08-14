"""
Venus Backend — Servicio de generación de facturas en PDF y PNG.

Estrategia dual para máxima compatibilidad:
  - WeasyPrint: preferido en Docker/Linux (requiere Cairo/GTK del sistema).
  - xhtml2pdf:  fallback puro-Python para Windows sin Cairo.

Jinja2 se usa como motor de templating del HTML.
El mismo template HTML genera tanto PDF como PNG.

Configuración de empresa:
  Editar company_config.json en la raíz del proyecto.
  El campo 'rnc' es completamente opcional — si es null o vacío,
  no aparece ninguna mención del RNC en la factura generada.
"""

import io
import os
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

# ---------------------------------------------------------------------------
# Template engine (Jinja2)
# ---------------------------------------------------------------------------
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _render_invoice_html(context: dict) -> str:
    """Renderiza el template invoice.html con el contexto dado."""
    template = _jinja_env.get_template("invoice.html")
    return template.render(**context)


# ---------------------------------------------------------------------------
# Construcción del contexto de la factura
# ---------------------------------------------------------------------------

def _get_cliente_nombre(factura: dict) -> str:
    """Resuelve el nombre del cliente (puede venir de cliente_id join o del campo JSON cliente)."""
    nombre = factura.get("cliente_nombre") or ""
    apellido = factura.get("cliente_apellido") or ""
    full = f"{nombre} {apellido}".strip()
    if full:
        return full

    # Fallback: campo JSON embebido (factura rápida)
    import json as _json
    raw = factura.get("cliente")
    if raw:
        try:
            c = _json.loads(raw) if isinstance(raw, str) else raw
            n = (c.get("nombre") or "").strip()
            a = (c.get("apellido") or "").strip()
            return f"{n} {a}".strip() or "Cliente no identificado"
        except Exception:
            pass

    return factura.get("cliente_id") or "Cliente no identificado"


def _get_cliente_telefono(factura: dict) -> str:
    """Intenta obtener el teléfono del cliente desde datos embebidos."""
    import json as _json
    raw = factura.get("cliente")
    if raw:
        try:
            c = _json.loads(raw) if isinstance(raw, str) else raw
            return c.get("telefono") or ""
        except Exception:
            pass
    return ""


def _clean_attribute_value(val) -> str | None:
    """
    Limpia y formatea el valor de un atributo (material, tela, color, etc.).
    Convierte listas JSON o representaciones en string tipo '["Madera Pino"]'
    a texto limpio como 'Madera Pino'.
    Si el valor es None, vacío, 'null', '[]', o equivalente, retorna None.
    """
    if val is None:
        return None

    if isinstance(val, (list, tuple, set)):
        cleaned_list = []
        for elem in val:
            cleaned_elem = _clean_attribute_value(elem)
            if cleaned_elem:
                cleaned_list.append(cleaned_elem)
        if not cleaned_list:
            return None
        return ", ".join(cleaned_list)

    if not isinstance(val, str):
        val = str(val)

    val_str = val.strip()
    if not val_str or val_str.lower() in ("null", "none", "[]", '[""]', "''", '""'):
        return None

    # Intentar desestructurar JSON si parece un array o string JSON
    if (val_str.startswith("[") and val_str.endswith("]")) or (val_str.startswith('"') and val_str.endswith('"')):
        import json as _json
        try:
            parsed = _json.loads(val_str)
            return _clean_attribute_value(parsed)
        except Exception:
            pass

    # Limpiar comillas o corchetes sobrantes en caso de JSON mal formateado
    val_str = val_str.strip('"\'[]').strip()
    if not val_str or val_str.lower() in ("null", "none"):
        return None

    return val_str


def build_invoice_context(factura: dict, items: list, company: dict) -> dict:
    """
    Construye el diccionario de contexto para el template Jinja2.

    Args:
        factura: dict de la factura (con joins de cliente si están disponibles)
        items:   lista de dicts de ítems de la factura
        company: dict devuelto por config.get_company_config()

    Returns:
        Diccionario listo para pasar a _render_invoice_html().
    """
    fecha_raw = factura.get("fecha") or ""
    try:
        fecha_dt = datetime.fromisoformat(fecha_raw)
        fecha_fmt = fecha_dt.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        fecha_fmt = fecha_raw[:10] if fecha_raw else "—"

    generated_at = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    processed_items = []
    for item in items:
        item_copy = dict(item)
        item_copy["material"] = _clean_attribute_value(item_copy.get("material"))
        tela_val = item_copy.get("tela") or item_copy.get("color")
        item_copy["tela"] = _clean_attribute_value(tela_val)
        processed_items.append(item_copy)

    return {
        "company": company,
        "factura_id": factura.get("id", "—"),
        "fecha": fecha_fmt,
        "generated_at": generated_at,
        "currency": "RD$",
        # Cliente
        "cliente_nombre": _get_cliente_nombre(factura),
        "cliente_telefono": _get_cliente_telefono(factura),
        "direccion_entrega": factura.get("direccion_entrega") or "",
        "entrega_domicilio": bool(factura.get("entrega_domicilio")),
        # Garantía
        "garantia_hasta": factura.get("garantia_hasta") or "",
        # Financiero
        "total": float(factura.get("total") or 0),
        "monto_pagado": float(factura.get("monto_pagado") or 0),
        "saldo_pendiente": float(factura.get("saldo_pendiente") or 0),
        # Ítems
        "items": processed_items,
    }


# ---------------------------------------------------------------------------
# Generación de PDF — WeasyPrint
# ---------------------------------------------------------------------------

def generate_invoice_pdf(context: dict) -> bytes:
    """
    Genera la factura en PDF desde el contexto dado usando WeasyPrint.

    Returns:
        Bytes del archivo PDF.

    Raises:
        RuntimeError: si WeasyPrint no está instalado o faltan dependencias del sistema.
    """
    html_content = _render_invoice_html(context)

    try:
        from weasyprint import HTML
        buf = io.BytesIO()
        HTML(string=html_content, base_url=str(_TEMPLATES_DIR)).write_pdf(buf)
        return buf.getvalue()
    except Exception as e:
        raise RuntimeError(
            f"No se pudo generar el PDF con WeasyPrint. Error: {e}\n"
            "Asegúrate de tener instaladas las dependencias del sistema en Linux/Docker: "
            "apt-get install -y libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0"
        ) from e


# ---------------------------------------------------------------------------
# Generación de PNG
# ---------------------------------------------------------------------------

def generate_invoice_png(context: dict, dpi: int = 150) -> bytes:
    """
    Genera la factura en PNG desde el mismo contexto que el PDF.
    Renderiza primero el PDF con WeasyPrint y lo convierte a PNG usando pypdfium2, pdf2image o write_png.

    Returns:
        Bytes del archivo PNG.
    """
    # 1. Generar el PDF base con WeasyPrint
    pdf_bytes = generate_invoice_pdf(context)

    # 2. Convertir el PDF a PNG vía pypdfium2 (método nativo sin binarios externos de sistema)
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(pdf_bytes)
        if len(pdf) > 0:
            page = pdf[0]
            # scale=dpi/72.0 (72 DPI es la escala 1x estándar de PDF)
            image = page.render(scale=dpi / 72.0).to_pil()
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        pass

    # 3. Fallback: pdf2image
    try:
        from pdf2image import convert_from_bytes
        images = convert_from_bytes(pdf_bytes, dpi=dpi)
        if images:
            img_buf = io.BytesIO()
            images[0].save(img_buf, format="PNG")
            return img_buf.getvalue()
    except Exception:
        pass

    # 4. Fallback: WeasyPrint write_png nativo (en versiones antiguas que lo soporten)
    try:
        html_content = _render_invoice_html(context)
        from weasyprint import HTML
        html_obj = HTML(string=html_content, base_url=str(_TEMPLATES_DIR))
        if hasattr(html_obj, "write_png"):
            buf = io.BytesIO()
            html_obj.write_png(buf, resolution=dpi)
            return buf.getvalue()

        document = html_obj.render()
        if hasattr(document, "write_png"):
            result = document.write_png(resolution=dpi)
            png_bytes = result[0] if isinstance(result, tuple) else result
            if png_bytes and len(png_bytes) > 0:
                return png_bytes
    except Exception:
        pass

    raise RuntimeError(
        "No se pudo generar la imagen PNG de la factura. "
        "Asegúrate de tener instalado 'pypdfium2' en el entorno Python."
    )
