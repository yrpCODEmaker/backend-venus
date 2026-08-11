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
        "items": items,
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
    Genera la factura en PNG desde el mismo contexto que el PDF usando WeasyPrint.

    Returns:
        Bytes del archivo PNG.
    """
    html_content = _render_invoice_html(context)

    try:
        from weasyprint import HTML
        document = HTML(string=html_content, base_url=str(_TEMPLATES_DIR)).render()
        result = document.write_png(resolution=dpi)
        # En versiones distintas retorna bytes o (bytes, warnings)
        png_bytes = result[0] if isinstance(result, tuple) else result
        if png_bytes and len(png_bytes) > 0:
            return png_bytes
        raise RuntimeError("write_png devolvió un resultado vacío.")
    except Exception as e:
        raise RuntimeError(
            f"No se pudo generar el PNG con WeasyPrint. Error: {e}\n"
            "Asegúrate de tener instaladas las dependencias del sistema en Linux/Docker."
        ) from e
