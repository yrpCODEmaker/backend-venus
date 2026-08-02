from api_client import app_state
from api_client import init_state, app_state, handle_action, save_transient_state
from api_client import obtener_hora, obtener_hora_str
from api_client import check_expired_warranties, sync_cola_trabajos
from datetime import datetime, timedelta
import ast
import flet as ft
import json
import logging
import os
import re
import shutil
import threading


# ========================================
# ui/styles.py
# ========================================

# ============================================================

LIGHT_PALETTE = {
    "primary": "#1A3644",        # Azul oscuro corporativo
    "secondary": "#E0E5EC",      # Gris azulado claro
    "background": "#F0F4F8",     # Fondo general gris muy claro
    "surface": "#FFFFFF",        # Blanco puro
    "text_dark": "#2C3E50",      # Texto principal
    "text_light": "#7F8C8D",     # Texto secundario
    "accent_green": "#2E8B57",   # Verde
    "accent_red": "#E74C3C",     # Rojo
    "border": "#D1D9E6"          # Bordes sutiles
}

DARK_PALETTE = {
    "primary": "#4A90E2",        # Azul vibrante para destacar en fondo oscuro
    "secondary": "#2C3E50",      # Gris oscuro azulado para tarjetas secundarias
    "background": "#121212",     # Fondo general muy oscuro
    "surface": "#1E1E1E",        # Gris oscuro para tarjetas y contenedores elevados
    "text_dark": "#E0E5EC",      # Texto principal claro
    "text_light": "#95A5A6",     # Texto secundario más tenue
    "accent_green": "#2ECC71",   # Verde vibrante
    "accent_red": "#E74C3C",     # Rojo vibrante
    "border": "#333333"          # Bordes oscuros
}

COLORS = LIGHT_PALETTE.copy()

def apply_theme(is_dark: bool):
    palette = DARK_PALETTE if is_dark else LIGHT_PALETTE
    for key, value in palette.items():
        COLORS[key] = value

# ============================================================


# ========================================
# ui/components.py
# ========================================

# ============================================================


def build_image(item_data, **kwargs):
    img_path = item_data.get("url_imagen")
    if img_path and isinstance(img_path, str) and img_path.strip() != "":
        return ft.Image(src=img_path, **kwargs)

    img_id = item_data.get("image_id")
    if img_id and img_id in app_state.get("images_cache", {}):
        cached_img = app_state["images_cache"][img_id]
        # image_src: ruta relativa tipo "/archivo.jpg", funciona en desktop y web
        if "image_src" in cached_img and cached_img["image_src"]:
            return ft.Image(src=cached_img["image_src"], **kwargs)
        elif "base64_data" in cached_img and cached_img["base64_data"]:
            return ft.Image(src=f"data:image/jpeg;base64,{cached_img['base64_data']}", **kwargs)

    # Fallback genérico cuando no hay imagen válida para evitar que se rompa el layout
    c_kwargs = {}
    for k in ["width", "height", "expand"]:
        if k in kwargs:
            c_kwargs[k] = kwargs[k]

    return ft.Container(
        bgcolor=COLORS["border"],
        border_radius=kwargs.get("border_radius", 4),
        content=ft.Icon(ft.Icons.IMAGE_NOT_SUPPORTED, color=COLORS["text_light"]),
        alignment=ft.Alignment(0, 0),
        **c_kwargs
    )

def create_product_card(product: dict, is_selected: bool, on_action: callable) -> ft.Container:
    """
    Crea una tarjeta individual para un producto en la cuadrícula (ej. carrito).
    """
    card_content = ft.Column([
        ft.Container(
            content=build_image(product, fit="cover", border_radius=ft.BorderRadius(top_left=8, top_right=8, bottom_left=0, bottom_right=0), expand=True),
            height=140, # Altura un poco más compacta
            width=float("inf")
        ),
        ft.Container(
            content=ft.Column([
                ft.Text(product["nombre"], weight=ft.FontWeight.W_600, size=14, color=COLORS["text_dark"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"Color: {product['color']}\nMat: {product['material']}", size=11, color=COLORS["text_light"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Row([
                    ft.Text(f"${product['precio']}", weight=ft.FontWeight.BOLD, size=16, color=COLORS["text_dark"])
                ], alignment=ft.MainAxisAlignment.END)
            ], spacing=4),
            padding=ft.Padding(left=10, right=10, top=8, bottom=10),
            expand=True
        )
    ], spacing=0)

    return ft.Container(
        bgcolor=COLORS["surface"],
        border=ft.Border.all(3, COLORS["primary"]) if is_selected else ft.Border.all(1, COLORS["border"]),
        border_radius=8,
        shadow=ft.BoxShadow(spread_radius=1, blur_radius=8, color="#33000000") if is_selected else None,
        on_click=lambda e: on_action("toggle_product", product),
        content=card_content
    )

def create_stock_card(st: dict, is_selected: bool, on_action: callable = None, read_only=False):
    border_color = COLORS["primary"] if is_selected else COLORS["border"]
    border_width = 2 if is_selected else 1
    bg = COLORS["secondary"] if is_selected else COLORS["surface"]
    
    def on_click(e):
        if on_action and not read_only:
            on_action("add_to_cart_stock", st)
            
    card_content = ft.Column([
        ft.Container(
            content=build_image(st, fit="cover", border_radius=ft.BorderRadius(top_left=8, top_right=8, bottom_left=0, bottom_right=0), expand=True),
            height=180,
            width=float("inf")
        ),
        ft.Container(
            content=ft.Column([
                ft.Text(st["nombre"], weight=ft.FontWeight.W_600, size=15, color=COLORS["text_dark"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Row([
                    ft.Container(
                        content=ft.Text(st.get("tipo", "General"), size=10, color="#FFFFFF", weight=ft.FontWeight.W_500),
                        bgcolor=COLORS["primary"],
                        padding=ft.Padding(left=6, right=6, top=2, bottom=2),
                        border_radius=4,
                    ),
                ]),
                ft.Text(f"🎨 {st['color']}  |  🪵 {st['material']}", size=11, color=COLORS["text_light"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Row([
                    ft.Text(f"${st['precio']}", weight=ft.FontWeight.BOLD, size=18, color=COLORS["text_dark"]),
                    ft.Container(
                        content=ft.Text(f"Disp: {st['cantidad']}", size=11, color="#FFFFFF", weight=ft.FontWeight.BOLD),
                        bgcolor="#27AE60" if st["cantidad"] > 0 else "#E74C3C",
                        padding=ft.Padding.symmetric(horizontal=8, vertical=4), border_radius=4
                    )
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.END)
            ], spacing=6),
            padding=ft.Padding(left=12, right=12, top=8, bottom=12),
            expand=True
        )
    ], spacing=0)

    tooltip_text = st.get("descripcion", "")
    return ft.Container(
        bgcolor=bg, border=ft.Border.all(border_width, border_color), border_radius=8, ink=True, on_click=on_click,
        content=card_content,
        tooltip=tooltip_text if tooltip_text else None,
        shadow=ft.BoxShadow(spread_radius=0, blur_radius=4, color="#1A000000", offset=ft.Offset(0, 2))
    )

# ============================================================


def format_currency_input(e):
    if not e.control.value: return
    val = e.control.value.replace(",", "")
    val = re.sub(r'[^0-9.]', '', val)
    parts = val.split(".")
    if len(parts) > 2:
        parts = [parts[0], "".join(parts[1:])]
    try:
        if len(parts) == 1 and parts[0]:
            e.control.value = f"{int(parts[0]):,}"
        elif len(parts) == 2:
            left = f"{int(parts[0]):,}" if parts[0] else "0"
            e.control.value = f"{left}.{parts[1]}"
        else:
            e.control.value = ""
    except ValueError:
        pass
    e.control.update()


# ========================================
# ui/dialogs/client_dialogs.py
# ========================================

# ============================================================

def open_client_dialog(page: ft.Page, state: dict, on_action: callable, client_to_edit=None):
        
    nombre_in = ft.TextField(label="Nombre", value=client_to_edit["nombre"] if client_to_edit else "", dense=True, text_size=13, expand=True)
    apellido_in = ft.TextField(label="Apellido", value=client_to_edit.get("apellido", "") if client_to_edit else "", dense=True, text_size=13, expand=True)
    telefono_in = ft.TextField(label="Teléfono", value=client_to_edit.get("telefono", "") if client_to_edit else "", dense=True, text_size=13)
    domicilio_in = ft.TextField(label="Domicilio", value=client_to_edit.get("domicilio", "") if client_to_edit else "", dense=True, text_size=13, expand=True)

    def on_save(e):
        if not nombre_in.value:
            return
        
        client_data = {
            "nombre": nombre_in.value.strip(),
            "apellido": apellido_in.value.strip(),
            "telefono": telefono_in.value.strip(),
            "domicilio": domicilio_in.value.strip(),
        }
        if client_to_edit:
            client_data["id"] = client_to_edit["id"]
            
        on_action("save_client", client_data)
        dialog.open = False
        page.update()

    dialog = ft.AlertDialog(
        title=ft.Text("Editar Cliente" if client_to_edit else "Nuevo Cliente", weight=ft.FontWeight.BOLD),
        content=ft.Container(
            width=350,
            content=ft.Column([
                ft.Row([nombre_in, apellido_in]),
                telefono_in,
                domicilio_in
            ], tight=True, scroll=ft.ScrollMode.AUTO)
        ),
        actions=[
            ft.Button("Guardar", bgcolor=COLORS["accent_green"], color="white", on_click=on_save),
            ft.TextButton("Cancelar", on_click=lambda e: setattr(dialog, "open", False) or page.update())
        ]
    )
    page.overlay.append(dialog)
    dialog.open = True
    page.update()

# ============================================================


# ========================================
# ui/dialogs/catalog_dialogs.py
# ========================================

# ============================================================

# Directorio de uploads de imágenes (database/img_uploads/)
IMG_UPLOADS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'img_uploads'))


def _save_uploaded_image(file_path: str) -> tuple:
    """
    Copia una imagen seleccionada por el usuario al directorio de uploads.
    Retorna (image_id, dest_path) o (None, None) si falla.
    """
    if not file_path or not os.path.exists(file_path):
        return None, None

    os.makedirs(IMG_UPLOADS_DIR, exist_ok=True)

    # Generar nombre único con timestamp
    from api_client import obtener_hora_str
    timestamp = obtener_hora_str("%Y%m%d_%H%M%S_%f")
    ext = os.path.splitext(file_path)[1] or ".jpg"
    new_filename = f"ref_{timestamp}{ext}"
    dest_path = os.path.join(IMG_UPLOADS_DIR, new_filename)

    try:
        shutil.copy2(file_path, dest_path)
        # Registrar en la tabla images
        from api_client import insert_image
        image_id = insert_image(new_filename, 1.0)
        return image_id, dest_path
    except Exception as e:
        import logging
        logging.error(f"Error saving uploaded image: {e}", exc_info=True)
        return None, None


def open_add_to_cart_dialog(page: ft.Page, state: dict, on_action: callable, cat: dict):
    stock_for_cat = [s for s in state.get("stock_cache", []) if s["catalogo_id"] == cat["id"] and s["cantidad"] > 0]
    
    
    dialog_content = ft.Column(spacing=15, tight=True, scroll=ft.ScrollMode.AUTO)
    
    dialog_content.controls.append(ft.Text("Inventario Físico (En Stock):", weight=ft.FontWeight.BOLD, size=14))
    if not stock_for_cat:
        dialog_content.controls.append(ft.Text("No hay unidades en stock para este modelo.", italic=True, color=COLORS["text_light"], size=12))
    else:
        for s in stock_for_cat:
            item_card = ft.Container(
                content=ft.Column([
                    ft.Container(
                        content=build_image(s, fit="cover", border_radius=ft.BorderRadius(top_left=8, top_right=8, bottom_left=0, bottom_right=0), expand=True),
                        height=120,
                        width=float("inf")
                    ),
                    ft.Container(
                        content=ft.ListTile(
                            content_padding=0,
                            title=ft.Text(f"Color: {s['color']} | Tela: {s['material']}", size=13, weight=ft.FontWeight.W_500),
                            subtitle=ft.Text(f"{s.get('descripcion', '')} | Precio: ${s['precio']} | Disp: {s['cantidad']}", size=11),
                            trailing=ft.Button("Agregar", icon=ft.Icons.ADD, bgcolor=COLORS["accent_green"], color="white", 
                                on_click=lambda e, st=s: (on_action("add_to_cart_stock", st), setattr(dialog, "open", False), page.update()))
                        ),
                        padding=ft.Padding(left=10, right=10, top=5, bottom=5)
                    )
                ], spacing=0),
                border=ft.Border.all(1, COLORS["border"]),
                border_radius=8,
                bgcolor=COLORS["surface"]
            )
            dialog_content.controls.append(item_card)
            
    dialog_content.controls.append(ft.Divider(color=COLORS["border"]))
    
    dialog_content.controls.append(ft.Text("O, Crear Nuevo Encargo:", weight=ft.FontWeight.BOLD, size=14))
    
    colores = state.get("colores", [])
    color_options = [ft.dropdown.Option(c) for c in colores]
    color_in = ft.Dropdown(label="Color", options=color_options, border_color=COLORS["border"], expand=True, value=color_options[0].key if color_options else None)
    
    materiales = state.get("materiales", [])
    material_options = [ft.dropdown.Option(m) for m in materiales]
    mat_in = ft.Dropdown(label="Material", options=material_options, border_color=COLORS["border"], expand=True, value=material_options[0].key if material_options else None)
    
    desc_in = ft.TextField(label="Descripción Opcional", multiline=True, border_color=COLORS["border"])
    
    val_base = cat.get("precio_base", 0)
    fmt_base = f"{int(val_base):,}" if val_base == int(val_base) else f"{val_base:,.2f}"
    price_in = ft.TextField(label="Precio Acordado ($)", border_color=COLORS["border"], value=fmt_base, expand=True, on_change=format_currency_input)
    qty_in = ft.TextField(label="Cantidad", value="1", border_color=COLORS["border"], expand=True)

    # ── Imagen de Referencia (opcional) ──
    # Estado mutable para el image_id seleccionado
    ref_image_state = {"image_id": None, "file_path": None}

    # Vista previa de la imagen
    image_preview = ft.Container(
        content=ft.Column([
            ft.Icon(ft.Icons.ADD_PHOTO_ALTERNATE_OUTLINED, size=30, color=COLORS["text_light"]),
            ft.Text("Agregar imagen\nde referencia", size=10, color=COLORS["text_light"], text_align=ft.TextAlign.CENTER),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=4),
        width=90, height=90,
        bgcolor=COLORS.get("background", "#F0F4F8"),
        border=ft.Border.all(1, COLORS["border"]),
        border_radius=8,
        alignment=ft.Alignment(0, 0),
    )

    async def on_file_picked(e):
        result = await ft.FilePicker().pick_files(
            allow_multiple=False,
            allowed_extensions=["png", "jpg", "jpeg", "webp"],
            dialog_title="Seleccionar Imagen de Referencia"
        )
        if result and len(result) > 0:
            file_path = result[0].path
            img_id, abs_path = _save_uploaded_image(file_path)
            if img_id:
                ref_image_state["image_id"] = img_id
                ref_image_state["file_path"] = abs_path
                image_preview.content = ft.Image(src=abs_path, fit="cover", border_radius=8)
                image_preview.border = ft.Border.all(2, COLORS.get("accent_green", "#27AE60"))
                page.update()

    image_preview.on_click = on_file_picked

    def on_save_encargo(e):
        if not color_in.value or not mat_in.value:
            return
        try:
            qty = int(qty_in.value)
            price = float(price_in.value.replace(',', ''))
        except: return
        on_action("add_to_cart_encargo", {
            "catalogo_id": cat["id"],
            "color": color_in.value, "material": mat_in.value,
            "descripcion": desc_in.value, "precio": price, "cantidad": qty,
            "image_id": ref_image_state["image_id"],  # Puede ser None si no se seleccionó imagen
        })
        dialog.open = False
        page.update()
        
    dialog_content.controls.append(ft.Column([
        ft.Row([color_in, mat_in], spacing=10), desc_in, ft.Row([price_in, qty_in], spacing=10),
        # Sección de imagen de referencia
        ft.Row([
            image_preview,
            ft.Column([
                ft.Text("Imagen de Referencia", size=12, weight=ft.FontWeight.W_600, color=COLORS.get("text_dark", "#2C3E50")),
                ft.Text("Sube una foto del mueble deseado\npara guiar la producción.", size=11, color=COLORS["text_light"]),
            ], spacing=4, expand=True),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Button("Agregar Encargo a Factura", icon=ft.Icons.ADD_SHOPPING_CART, bgcolor=COLORS["secondary"], color=COLORS["primary"], on_click=on_save_encargo)
    ], spacing=10))
    
    dialog = ft.AlertDialog(
        title=ft.Text(f"Agregar '{cat['nombre']}' a Factura"),
        content=ft.Container(content=dialog_content, width=500),
        actions=[ft.TextButton("Cancelar", on_click=lambda e: setattr(dialog, "open", False) or page.update())]
    )
    page.overlay.append(dialog)
    dialog.open = True
    page.update()

# ============================================================

def open_encargo_from_stock_dialog(page: ft.Page, stock_item: dict, state: dict, on_action: callable):
    dialog_content = ft.Column(spacing=15, tight=True, scroll=ft.ScrollMode.AUTO)
    
    dialog_content.controls.append(ft.Text(f"No hay inventario disponible para '{stock_item['nombre']}'.", color=COLORS["accent_red"], weight=ft.FontWeight.BOLD))
    dialog_content.controls.append(ft.Text("¿Deseas agregarlo como un Encargo a medida rescatando los datos del lote original?", size=12, color=COLORS["text_light"]))
    
    colores = state.get("colores", [])
    color_options = [ft.dropdown.Option(c) for c in colores]
    val_color = stock_item.get("color", "")
    if val_color and val_color not in colores:
        color_options.append(ft.dropdown.Option(val_color))
    color_in = ft.Dropdown(label="Color", options=color_options, border_color=COLORS["border"], expand=True, value=val_color if val_color else (color_options[0].key if color_options else None))
    
    materiales = state.get("materiales", [])
    material_options = [ft.dropdown.Option(m) for m in materiales]
    val_mat = stock_item.get("material", "")
    if val_mat and val_mat not in materiales:
        material_options.append(ft.dropdown.Option(val_mat))
    mat_in = ft.Dropdown(label="Material", options=material_options, border_color=COLORS["border"], expand=True, value=val_mat if val_mat else (material_options[0].key if material_options else None))
    
    desc_in = ft.TextField(label="Descripción", value=stock_item.get("descripcion", ""), multiline=True, border_color=COLORS["border"])
    
    val_stock = stock_item.get("precio", 0)
    fmt_stock = f"{int(val_stock):,}" if val_stock == int(val_stock) else f"{val_stock:,.2f}"
    price_in = ft.TextField(label="Precio Unitario ($)", value=fmt_stock, border_color=COLORS["border"], expand=True, on_change=format_currency_input)
    qty_in = ft.TextField(label="Cantidad", value="1", border_color=COLORS["border"], expand=True)

    # ── Imagen de Referencia (opcional) ──
    ref_image_state = {"image_id": None, "file_path": None}

    image_preview = ft.Container(
        content=ft.Column([
            ft.Icon(ft.Icons.ADD_PHOTO_ALTERNATE_OUTLINED, size=30, color=COLORS["text_light"]),
            ft.Text("Agregar imagen\nde referencia", size=10, color=COLORS["text_light"], text_align=ft.TextAlign.CENTER),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=4),
        width=90, height=90,
        bgcolor=COLORS.get("background", "#F0F4F8"),
        border=ft.Border.all(1, COLORS["border"]),
        border_radius=8,
        alignment=ft.Alignment(0, 0),
    )

    async def on_file_picked(e):
        result = await ft.FilePicker().pick_files(
            allow_multiple=False,
            allowed_extensions=["png", "jpg", "jpeg", "webp"],
            dialog_title="Seleccionar Imagen de Referencia"
        )
        if result and len(result) > 0:
            file_path = result[0].path
            img_id, abs_path = _save_uploaded_image(file_path)
            if img_id:
                ref_image_state["image_id"] = img_id
                ref_image_state["file_path"] = abs_path
                image_preview.content = ft.Image(src=abs_path, fit="cover", border_radius=8)
                image_preview.border = ft.Border.all(2, COLORS.get("accent_green", "#27AE60"))
                page.update()

    image_preview.on_click = on_file_picked

    def on_save_encargo(e):
        if not color_in.value or not mat_in.value:
            return
        try:
            qty = int(qty_in.value)
            price = float(price_in.value.replace(',', ''))
        except: return
        on_action("add_to_cart_encargo", {
            "catalogo_id": stock_item.get("catalogo_id"),
            "color": color_in.value, 
            "material": mat_in.value,
            "descripcion": desc_in.value, 
            "precio": price, 
            "cantidad": qty,
            "image_id": ref_image_state["image_id"],  # Puede ser None
        })
        dialog.open = False
        page.update()
        
    dialog_content.controls.append(ft.Column([
        ft.Row([color_in, mat_in], spacing=10), desc_in, ft.Row([price_in, qty_in], spacing=10),
        # Sección de imagen de referencia
        ft.Row([
            image_preview,
            ft.Column([
                ft.Text("Imagen de Referencia", size=12, weight=ft.FontWeight.W_600, color=COLORS.get("text_dark", "#2C3E50")),
                ft.Text("Sube una foto del mueble deseado\npara guiar la producción.", size=11, color=COLORS["text_light"]),
            ], spacing=4, expand=True),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    ], spacing=10))
    
    dialog = ft.AlertDialog(
        title=ft.Text("Convertir a Encargo"),
        content=ft.Container(content=dialog_content, width=500),
        actions=[
            ft.Button("Agregar Encargo a Factura", icon=ft.Icons.ADD_SHOPPING_CART, bgcolor=COLORS["secondary"], color=COLORS["primary"], on_click=on_save_encargo),
            ft.TextButton("Cancelar", on_click=lambda e: setattr(dialog, "open", False) or page.update())
        ]
    )
    page.overlay.append(dialog)
    dialog.open = True
    page.update()

# ============================================================


# ========================================
# ui/dialogs/invoice_dialogs.py
# ========================================

# ============================================================


def dummy_create_stock_card(*args, **kwargs): pass

def open_options_dialog(page: ft.Page, fact: dict, state: dict, on_action: callable):
    def on_delete_click(ev):
        dialog.open = False
        page.update()
        on_action("delete_factura", fact["id"])
        
    def on_modify_click(ev):
        dialog.open = False
        page.update()
        open_modify_invoice_dialog(page, fact, state, on_action)
    
    def on_view_click(ev):
        dialog.open = False
        page.update()
        on_action("view_full_invoice", fact)
    
    def on_export_click(ev):
        dialog.open = False
        page.update()
        on_action("export_invoice", fact)
    
    def on_share_whatsapp_click(ev):
        dialog.open = False
        page.update()
        on_action("share_invoice_whatsapp", fact)
        
    dialog = ft.AlertDialog(
        title=ft.Text(f"Opciones de Factura #{fact['id']}"),
        content=ft.Column([
            ft.Text(f"Cliente: {fact.get('cliente_nombre', 'Cliente')}", size=14, color=COLORS["text_light"]),
            ft.Text(f"Total: ${fact['total']:.2f}", size=14, weight=ft.FontWeight.BOLD),
            ft.Divider(color=COLORS["border"]),
            ft.ListTile(
                leading=ft.Icon(ft.Icons.VISIBILITY, color=COLORS["primary"]),
                title=ft.Text("Ver Factura Completa", weight=ft.FontWeight.BOLD, color=COLORS["primary"]),
                subtitle=ft.Text("Previsualizar todos los detalles", size=12),
                on_click=on_view_click
            ),
            ft.ListTile(
                leading=ft.Icon(ft.Icons.PICTURE_AS_PDF, color="#E65100"),
                title=ft.Text("Exportar PDF / Imprimir", weight=ft.FontWeight.BOLD, color="#E65100"),
                subtitle=ft.Text("Abrir en navegador para guardar o imprimir", size=12),
                on_click=on_export_click
            ),
            ft.Divider(color=COLORS["border"], height=5),
            ft.Text("Compartir", size=13, weight=ft.FontWeight.BOLD, color=COLORS["text_light"]),
            ft.Row([
                ft.ElevatedButton(
                    "WhatsApp",
                    icon=ft.Icons.CHAT,
                    bgcolor="#25D366",
                    color="white",
                    on_click=on_share_whatsapp_click,
                    style=ft.ButtonStyle(padding=ft.Padding(12, 8, 12, 8))
                ),
            ], spacing=10),
            ft.Divider(color=COLORS["border"], height=5),
            ft.ListTile(
                leading=ft.Icon(ft.Icons.EDIT, color=COLORS["primary"]),
                title=ft.Text("Modificar Factura", weight=ft.FontWeight.BOLD, color=COLORS["primary"]),
                subtitle=ft.Text("Editar ítems, cantidades y precios", size=12),
                on_click=on_modify_click
            ),
            ft.ListTile(
                leading=ft.Icon(ft.Icons.DELETE, color=COLORS["accent_red"]),
                title=ft.Text("Eliminar Factura", weight=ft.FontWeight.BOLD, color=COLORS["accent_red"]),
                subtitle=ft.Text("Borrar registro y devolver stock", size=12),
                on_click=on_delete_click
            )
        ], tight=True, spacing=5),
        actions=[
            ft.TextButton("Cancelar", on_click=lambda ev: setattr(dialog, "open", False) or page.update())
        ]
    )
    page.overlay.append(dialog)
    dialog.open = True
    page.update()


def open_modify_invoice_dialog(page: ft.Page, fact: dict, state: dict, on_action: callable):
    on_action("start_modify_invoice", fact)
    
    dialog_content = ft.Column(spacing=15, scroll=ft.ScrollMode.AUTO)
    
    def rebuild_dialog_ui():
        mod_inv = state.get("modifying_invoice")
        if not mod_inv:
            return
            
        dialog_content.controls.clear()
        
        dialog_content.controls.append(
            ft.Row([
                ft.Column([
                    ft.Text(f"Cliente: {mod_inv['cliente_nombre']}", size=16, weight=ft.FontWeight.BOLD, color=COLORS["text_dark"]),
                    ft.Text(f"Fecha de Emisión: {mod_inv['fecha']}", size=12, color=COLORS["text_light"]),
                ]),
                ft.Container(
                    content=ft.Text(f"ID #{mod_inv['id']}", size=12, weight=ft.FontWeight.BOLD, color=COLORS["surface"]),
                    bgcolor=COLORS["primary"],
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                    border_radius=5
                )
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        )
        dialog_content.controls.append(ft.Divider(color=COLORS["border"], height=5))
        
        items_col = ft.Column(spacing=8)
        for item in mod_inv.get("items", []):
            unit_price = item["subtotal"] / item["cantidad"] if item["cantidad"] > 0 else 0
            is_stock = item.get("tipo") == "stock"
            tipo_lbl = "STOCK" if is_stock else "ENCARGO"
            tipo_color = COLORS["accent_green"] if is_stock else COLORS["accent_red"]
            
            items_col.controls.append(
                ft.Container(
                    padding=10,
                    border=ft.Border.all(1, COLORS["border"]),
                    border_radius=8,
                    bgcolor=COLORS["surface"],
                    content=ft.Row([
                        ft.Column([
                            ft.Row([
                                ft.Container(
                                    content=ft.Text(tipo_lbl, size=9, weight=ft.FontWeight.BOLD, color="white"),
                                    bgcolor=tipo_color,
                                    padding=ft.Padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=3
                                ),
                                ft.Text(item["nombre"], weight=ft.FontWeight.BOLD, size=14, color=COLORS["text_dark"]),
                            ], spacing=6),
                            ft.Text(f"Precio Unitario: ${unit_price:.2f}", size=11, color=COLORS["text_light"]),
                        ], expand=True),
                        
                        ft.Row([
                            ft.IconButton(
                                icon=ft.Icons.REMOVE,
                                icon_size=16,
                                on_click=lambda e, it_id=item["id"], it_type=item.get("tipo", "stock"): update_item_qty(it_id, it_type, -1)
                            ),
                            ft.Text(str(item["cantidad"]), weight=ft.FontWeight.BOLD, size=14),
                            ft.IconButton(
                                icon=ft.Icons.ADD,
                                icon_size=16,
                                on_click=lambda e, it_id=item["id"], it_type=item.get("tipo", "stock"): update_item_qty(it_id, it_type, 1)
                            )
                        ], spacing=2),
                        
                        ft.Text(f"${item['subtotal']:.2f}", weight=ft.FontWeight.BOLD, size=14, color=COLORS["primary"], width=80, text_align=ft.TextAlign.RIGHT),
                        
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            icon_color=COLORS["accent_red"],
                            icon_size=20,
                            tooltip="Eliminar de factura",
                            on_click=lambda e, it_id=item["id"], it_type=item.get("tipo", "stock"): remove_item(it_id, it_type)
                        )
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                )
            )
        
        if not mod_inv.get("items"):
            items_col.controls.append(
                ft.Container(
                    content=ft.Text("No hay productos en esta factura.", italic=True, color=COLORS["text_light"]),
                    padding=20, alignment=ft.Alignment(0, 0)
                )
            )
            
        dialog_content.controls.append(ft.Text("Productos en Factura:", weight=ft.FontWeight.BOLD, size=13))
        dialog_content.controls.append(items_col)
        dialog_content.controls.append(ft.Divider(color=COLORS["border"], height=5))
        
        dialog_content.controls.append(
            ft.Row([
                ft.Button(
                    "+ Stock",
                    icon=ft.Icons.INVENTORY_2,
                    bgcolor=COLORS["primary"],
                    color="white",
                    on_click=lambda e: open_stock_adder()
                ),
                ft.Button(
                    "+ Encargo",
                    icon=ft.Icons.ADD_SHOPPING_CART,
                    bgcolor=COLORS["secondary"],
                    color=COLORS["primary"],
                    on_click=lambda e: open_encargo_adder()
                )
            ], spacing=10)
        )
        dialog_content.controls.append(ft.Divider(color=COLORS["border"], height=5))
        
        dialog_content.controls.append(
            ft.Row([
                ft.Text("Total Actualizado:", size=16),
                ft.Text(f"${mod_inv['total']:.2f}", size=22, weight=ft.FontWeight.BOLD, color=COLORS["accent_green"])
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        )
        
        dialog.update()
        
    def update_item_qty(item_id, tipo, delta):
        on_action("update_modifying_qty", {"item_id": item_id, "tipo": tipo, "delta": delta})
        rebuild_dialog_ui()
        
    def remove_item(item_id, tipo):
        on_action("remove_modifying_item", {"item_id": item_id, "tipo": tipo})
        rebuild_dialog_ui()
        
    def open_stock_adder():
        def on_select_prod(prod):
            on_action("add_stock_to_modifying", prod)
            sub_dialog.open = False
            page.update()
            rebuild_dialog_ui()
            
        list_tiles = []
        for p in state.get("catalog_cache", []):
            original_qty = 0
            orig_inv = next((f for f in state.get("facturas_cache", []) if f["id"] == fact["id"]), None)
            if orig_inv:
                orig_item = next((it for it in orig_inv.get("items", []) if it["id"] == p["id"] and it.get("tipo") == "stock"), None)
                if orig_item:
                    original_qty = orig_item["cantidad"]
            
            current_added = 0
            mod_inv = state.get("modifying_invoice")
            if mod_inv:
                mod_item = next((it for it in mod_inv.get("items", []) if it["id"] == p["id"] and it.get("tipo") == "stock"), None)
                if mod_item:
                    current_added = mod_item["cantidad"]
                    
            available_phys = original_qty + p["stock"] - current_added
            
            list_tiles.append(
                ft.ListTile(
                    leading=build_image(p, width=40, height=40, fit="cover", border_radius=4),
                    title=ft.Text(p["nombre"], weight=ft.FontWeight.BOLD),
                    subtitle=ft.Text(f"Precio: ${p['precio']} | Disponible: {available_phys} uds"),
                    trailing=ft.Button("Elegir", bgcolor=COLORS["primary"], color="white", on_click=lambda e, prod=p: on_select_prod(prod), disabled=(available_phys < 1))
                )
            )
            
        sub_dialog = ft.AlertDialog(
            title=ft.Text("Elegir Producto en Stock"),
            content=ft.Container(
                content=ft.Column(list_tiles, spacing=5, tight=True, scroll=ft.ScrollMode.AUTO),
                width=400, height=300
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: setattr(sub_dialog, "open", False) or page.update())
            ]
        )
        page.overlay.append(sub_dialog)
        sub_dialog.open = True
        page.update()
        
    def open_encargo_adder():
        name_field = ft.TextField(label="Nombre del Mueble", hint_text="ej. Mesita de Noche Especial")
        price_field = ft.TextField(label="Precio Unitario ($)", hint_text="ej. 150", on_change=format_currency_input)
        qty_field = ft.TextField(label="Cantidad", value="1")
        
        def save_encargo(e):
            if not name_field.value.strip():
                return
            try:
                price = float(price_field.value.replace(',', ''))
                qty = int(qty_field.value)
            except ValueError:
                return
                
            on_action("add_encargo_to_modifying", {
                "nombre": name_field.value,
                "precio": price,
                "cantidad": qty
            })
            sub_dialog.open = False
            page.update()
            rebuild_dialog_ui()
            
        sub_dialog = ft.AlertDialog(
            title=ft.Text("Agregar Producto de Encargo (A Medida)"),
            content=ft.Column([
                name_field,
                ft.Row([price_field, qty_field], spacing=10)
            ], tight=True, spacing=10),
            actions=[
                ft.Button("Agregar", bgcolor=COLORS["accent_green"], color="white", on_click=save_encargo),
                ft.TextButton("Cancelar", on_click=lambda e: setattr(sub_dialog, "open", False) or page.update())
            ]
        )
        page.overlay.append(sub_dialog)
        sub_dialog.open = True
        page.update()
        
    def save_changes(e):
        dialog.open = False
        page.update()
        on_action("save_modified_invoice")
        
    dialog = ft.AlertDialog(
        title=ft.Text("Modificar Factura", weight=ft.FontWeight.BOLD),
        content=ft.Container(content=dialog_content, width=600, height=450),
        actions=[
            ft.Button("Guardar Cambios", bgcolor=COLORS["accent_green"], color="white", on_click=save_changes),
            ft.TextButton("Cancelar", on_click=lambda e: setattr(dialog, "open", False) or page.update())
        ]
    )
    page.overlay.append(dialog)
    dialog.open = True
    page.update()
    
    rebuild_dialog_ui()


def open_invoice_items_dialog(page: ft.Page, fact: dict):
    items = fact.get("items", [])
    
    rows = []
    for it in items:
        tipo = it.get("tipo") or ""
        tipo_str = "Encargo" if tipo == "encargo" else "Stock"
        desc = it.get("descripcion") or ""
        tela_tipo = it.get("tela_tipo")
        tela_color = it.get("tela_color") or ""
        if tela_tipo:
            desc += f" | Tela: {tela_tipo} ({tela_color})"
            
        nombre = it.get("nombre") or ""
        cantidad = it.get("cantidad") or 1
            
        rows.append(ft.DataRow(cells=[
            ft.DataCell(ft.Text(tipo_str)),
            ft.DataCell(ft.Text(nombre)),
            ft.DataCell(ft.Text(desc)),
            ft.DataCell(ft.Text(str(cantidad))),
        ]))
        
    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Tipo")),
            ft.DataColumn(ft.Text("Producto")),
            ft.DataColumn(ft.Text("Descripción")),
            ft.DataColumn(ft.Text("Cant.")),
        ],
        rows=rows
    )
    
    dlg = ft.AlertDialog(
        title=ft.Text(f"Ítems de Factura #{fact.get('id', '')}"),
        content=ft.Column([table], scroll=ft.ScrollMode.AUTO, tight=True),
        actions=[ft.TextButton("Cerrar", on_click=lambda e: close_dlg())]
    )
    def close_dlg():
        dlg.open = False
        page.update()
        
    page.overlay.append(dlg)
    dlg.open = True
    page.update()



# ============================================================

def open_checkout_dialog(page, payload: dict, state: dict, on_action: callable):
    is_fast_invoice = state.get("selected_client") is None
    total_monto = payload.get("total_override", 0.0)
    
    # Fast Invoice Fields
    fast_name_in = ft.TextField(label="Nombre del Cliente *", dense=True, text_size=13, expand=True)
    fast_phone_in = ft.TextField(label="Teléfono", dense=True, text_size=13, expand=True)
    fast_addr_in = ft.TextField(label="Dirección", dense=True, text_size=13, expand=True)
    
    # Payment Fields
    fmt_total = f"{int(total_monto):,}" if total_monto == int(total_monto) else f"{total_monto:,.2f}"
    monto_abonado_in = ft.TextField(
        label="Monto Pagado (Abono) $", 
        value=fmt_total, 
        dense=True, 
        text_size=16, 
        expand=True,
        text_align=ft.TextAlign.RIGHT,
        color=COLORS["accent_green"],
        text_style=ft.TextStyle(weight=ft.FontWeight.BOLD),
        on_change=format_currency_input
    )
    nota_pago_in = ft.TextField(label="Nota del Pago (Opcional)", dense=True, text_size=13, expand=True)
    
    def on_confirm(e):
        try:
            monto = float(monto_abonado_in.value.replace(',', ''))
        except ValueError:
            monto = 0.0
            
        state["monto_pagado"] = monto
        state["nota_pago"] = nota_pago_in.value
        
        if is_fast_invoice:
            if not fast_name_in.value.strip():
                page.snack_bar = ft.SnackBar(ft.Text("Debe ingresar el nombre del cliente para factura rápida."), bgcolor="red")
                page.snack_bar.open = True
                page.update()
                return
            state["is_fast_invoice"] = True
            state["fast_invoice_client_name"] = fast_name_in.value.strip()
            state["fast_invoice_client_phone"] = fast_phone_in.value.strip()
            state["fast_invoice_client_address"] = fast_addr_in.value.strip()
        else:
            state["is_fast_invoice"] = False
            
        dialog.open = False
        page.update()
        on_action("process_invoice", payload)

    content_cols = []
    
    if is_fast_invoice:
        content_cols.extend([
            ft.Text("Factura Rápida (Cliente no registrado)", weight=ft.FontWeight.BOLD, color=COLORS["accent_red"]),
            ft.Text("Para mantener un historial de abonos y envíos organizados, se recomienda registrar al cliente primero.", size=11, color=COLORS["text_light"]),
            ft.Divider(height=10, color=COLORS["border"]),
            ft.Row([fast_name_in, fast_phone_in], spacing=10),
            fast_addr_in,
            ft.Divider(height=10, color=COLORS["border"])
        ])
    else:
        client_name = f"{state['selected_client']['nombre']} {state['selected_client'].get('apellido', '')}".strip()
        content_cols.extend([
            ft.Text(f"Cliente: {client_name}", weight=ft.FontWeight.BOLD, size=16),
            ft.Divider(height=10, color=COLORS["border"])
        ])
        
    content_cols.extend([
        ft.Row([
            ft.Text("Total de la Factura:", size=16),
            ft.Text(f"${total_monto:.2f}", size=18, weight=ft.FontWeight.BOLD)
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ft.Row([
            monto_abonado_in,
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        nota_pago_in
    ])
    
    dialog = ft.AlertDialog(
        title=ft.Text("Completar Cobro", weight=ft.FontWeight.BOLD),
        content=ft.Container(
            width=400,
            content=ft.Column(content_cols, tight=True, spacing=10)
        ),
        actions=[
            ft.Button("Confirmar y Guardar", bgcolor=COLORS["accent_green"], color="white", on_click=on_confirm),
            ft.TextButton("Cancelar", on_click=lambda e: setattr(dialog, "open", False) or page.update())
        ]
    )
    
    page.overlay.append(dialog)
    dialog.open = True
    page.update()

# ============================================================

def open_full_invoice_dialog(page: ft.Page, fact: dict, state: dict, on_action: callable):
    # Determine client display
    cliente_str = (fact.get("cliente_nombre") or "") + " " + (fact.get("cliente_apellido") or "")
    if not cliente_str.strip():
        # Fast invoice, try to get from fact['cliente']
        import json
        c_str = fact.get("cliente")
        if c_str:
            try:
                c_json = json.loads(c_str)
                cliente_str = f"{c_json.get('nombre', '')} - {c_json.get('telefono', '')}"
            except:
                cliente_str = "Cliente Desconocido"
        else:
            cliente_str = "Cliente Desconocido"
            
    items_list = ft.ListView(spacing=10, height=200, padding=10)
    for it in fact.get("items", []):
        items_list.controls.append(
            ft.Container(
                padding=10,
                bgcolor=COLORS["surface"],
                border_radius=8,
                border=ft.Border.all(1, COLORS["border"]),
                content=ft.Row([
                    ft.Text(f"{it.get('cantidad', 1)}x", weight=ft.FontWeight.BOLD),
                    ft.Column([
                        ft.Text(it.get("nombre", ""), weight=ft.FontWeight.BOLD),
                        ft.Text(it.get("descripcion", ""), size=11, color=COLORS["text_light"])
                    ], expand=True),
                    ft.Text(f"${it.get('subtotal', 0):.2f}", weight=ft.FontWeight.BOLD)
                ])
            )
        )
        
    if not fact.get("items"):
        items_list.controls.append(ft.Text("No hay items registrados."))

    total = fact.get("total", 0.0)
    pagado = fact.get("monto_pagado", 0.0)
    saldo = fact.get("saldo_pendiente", total - pagado)
    
    summary_col = ft.Column([
        ft.Row([ft.Text("Total:", weight=ft.FontWeight.BOLD), ft.Text(f"${total:.2f}", weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ft.Row([ft.Text("Monto Pagado:", color=COLORS["accent_green"]), ft.Text(f"${pagado:.2f}", color=COLORS["accent_green"])], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ft.Divider(height=1),
        ft.Row([ft.Text("Saldo Pendiente:", weight=ft.FontWeight.BOLD, color=COLORS["accent_red"] if saldo > 0 else COLORS["text_dark"]), ft.Text(f"${saldo:.2f}", weight=ft.FontWeight.BOLD, color=COLORS["accent_red"] if saldo > 0 else COLORS["text_dark"])], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
    ])
    
    actions_row = []
    if saldo > 0:
        actions_row.append(
            ft.ElevatedButton("Registrar Abono", icon=ft.Icons.PAYMENTS, bgcolor=COLORS["accent_green"], color="white", on_click=lambda e: open_add_payment_dialog(page, fact, state, on_action))
        )
    actions_row.append(
        ft.TextButton("Cerrar", on_click=lambda e: setattr(dialog, "open", False) or page.update())
    )
    
    dialog = ft.AlertDialog(
        title=ft.Text(f"Factura #{fact['id']}", weight=ft.FontWeight.BOLD),
        content=ft.Container(
            width=500,
            content=ft.Column([
                ft.Text(f"Cliente: {cliente_str}", weight=ft.FontWeight.W_500),
                ft.Text(f"Fecha: {fact.get('fecha', '')}", size=12, color=COLORS["text_light"]),
                ft.Divider(),
                ft.Text("Productos:", weight=ft.FontWeight.BOLD),
                items_list,
                ft.Divider(),
                summary_col
            ], tight=True, spacing=5)
        ),
        actions=actions_row
    )
    
    page.overlay.append(dialog)
    dialog.open = True
    page.update()

def open_add_payment_dialog(page: ft.Page, fact: dict, state: dict, on_action: callable):
    saldo = fact.get("saldo_pendiente", 0.0)
    
    fmt_saldo = f"{int(saldo):,}" if saldo == int(saldo) else f"{saldo:,.2f}"
    monto_in = ft.TextField(label="Monto del Abono $", value=fmt_saldo, text_size=16, text_style=ft.TextStyle(weight=ft.FontWeight.BOLD), color=COLORS["accent_green"], text_align=ft.TextAlign.RIGHT, on_change=format_currency_input)
    nota_in = ft.TextField(label="Nota / Referencia", text_size=13)
    
    def on_save(e):
        try:
            m = float(monto_in.value.replace(',', ''))
        except ValueError:
            return
            
        if m <= 0 or m > saldo:
            page.snack_bar = ft.SnackBar(ft.Text("Monto inválido."), bgcolor="red")
            page.snack_bar.open = True
            page.update()
            return
            
        on_action("add_payment_to_invoice", {"factura_id": fact["id"], "monto": m, "nota": nota_in.value})
        dialog.open = False
        # Also close the parent full invoice dialog to refresh
        for control in page.overlay:
            if isinstance(control, ft.AlertDialog) and control.open:
                control.open = False
        page.update()

    dialog = ft.AlertDialog(
        title=ft.Text(f"Abonar a Factura #{fact['id']}"),
        content=ft.Column([
            ft.Text(f"Saldo Pendiente: ${saldo:.2f}", weight=ft.FontWeight.BOLD),
            monto_in,
            nota_in
        ], tight=True, spacing=10),
        actions=[
            ft.Button("Registrar", bgcolor=COLORS["accent_green"], color="white", on_click=on_save),
            ft.TextButton("Cancelar", on_click=lambda e: setattr(dialog, "open", False) or page.update())
        ]
    )
    page.overlay.append(dialog)
    dialog.open = True
    page.update()

# ============================================================

def open_download_dialog(page: ft.Page, fact: dict, company_info: dict):
    def download_format(fmt):
        import os
        from api_client import generate_invoice_pdf, generate_invoice_image
        output_dir = os.path.join(os.path.expanduser("~"), "Downloads", "VenusFacturas")
        os.makedirs(output_dir, exist_ok=True)
        base_name = f"Factura_{fact.get('id')}_{fact.get('cliente_nombre', 'Cliente').replace(' ', '_')}"
        
        path = ""
        try:
            if fmt == "pdf":
                out_path = os.path.join(output_dir, base_name + ".pdf")
                path = generate_invoice_pdf(fact, company_info, out_path)
            else:
                out_path = os.path.join(output_dir, base_name + ".png")
                path = generate_invoice_image(fact, company_info, out_path)
                
            page.snack_bar = ft.SnackBar(ft.Text(f"Factura guardada en: {path}"), bgcolor=COLORS["accent_green"])
        except Exception as ex:
            page.snack_bar = ft.SnackBar(ft.Text(f"Error: {ex}"), bgcolor=COLORS["accent_red"])
        page.snack_bar.open = True
        dlg.open = False
        page.update()
        
    dlg = ft.AlertDialog(
        title=ft.Text("Descargar Factura"),
        content=ft.Text("Selecciona el formato de descarga:"),
        actions=[
            ft.ElevatedButton("PDF", on_click=lambda e: download_format("pdf")),
            ft.ElevatedButton("PNG", on_click=lambda e: download_format("png")),
            ft.TextButton("Cancelar", on_click=lambda e: close_dlg())
        ]
    )
    def close_dlg():
        dlg.open = False
        page.update()
        
    page.overlay.append(dlg)
    dlg.open = True
    page.update()

def open_share_dialog(page: ft.Page, fact: dict, company_info: dict):
    def share_format(fmt):
        import os
        from api_client import generate_invoice_pdf, generate_invoice_image, share_file_to_whatsapp
        
        output_dir = os.path.join(os.path.expanduser("~"), "Downloads", "VenusFacturas")
        os.makedirs(output_dir, exist_ok=True)
        base_name = f"Factura_{fact.get('id')}_{fact.get('cliente_nombre', 'Cliente').replace(' ', '_')}"
        
        try:
            if fmt == "pdf":
                out_path = os.path.join(output_dir, base_name + ".pdf")
                path = generate_invoice_pdf(fact, company_info, out_path)
            else:
                out_path = os.path.join(output_dir, base_name + ".png")
                path = generate_invoice_image(fact, company_info, out_path)
            share_file_to_whatsapp(path)
        except Exception as ex:
            page.snack_bar = ft.SnackBar(ft.Text(f"Error: {ex}"), bgcolor=COLORS["accent_red"])
            page.snack_bar.open = True
            
        dlg.open = False
        page.update()
        
    dlg = ft.AlertDialog(
        title=ft.Text("Compartir por WhatsApp"),
        content=ft.Text("Selecciona el formato a compartir:"),
        actions=[
            ft.ElevatedButton("PDF", on_click=lambda e: share_format("pdf")),
            ft.ElevatedButton("PNG", on_click=lambda e: share_format("png")),
            ft.TextButton("Cancelar", on_click=lambda e: close_dlg())
        ]
    )
    def close_dlg():
        dlg.open = False
        page.update()
        
    page.overlay.append(dlg)
    dlg.open = True
    page.update()


# ========================================
# ui/views/catalog_view.py
# ========================================

# ============================================================


def create_catalog_view(state: dict, on_action: callable):
    # Agrupar catálogo por tipo
    catalog_items = state.get("catalog_cache") or []
    grouped_catalog = {}
    for cat in catalog_items:
        tipo = cat.get("tipo", "General")
        if not tipo:
            tipo = "General"
        if tipo not in grouped_catalog:
            grouped_catalog[tipo] = []
        grouped_catalog[tipo].append(cat)
        
    # Ordenar los tipos alfabéticamente para mantener consistencia
    sorted_tipos = sorted(grouped_catalog.keys())
    
    sections = []
    
    for tipo in sorted_tipos:
        items = grouped_catalog[tipo]
        
        # Título de la sección
        header = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.CATEGORY, color=COLORS["primary"], size=24),
                ft.Text(tipo.upper(), weight=ft.FontWeight.BOLD, size=18, color=COLORS["text_dark"]),
            ], spacing=8),
            padding=ft.Padding(top=20, bottom=10, left=5, right=5)
        )
        
        # Grid para esta sección
        grid = ft.GridView(max_extent=264, child_aspect_ratio=0.75, spacing=15, run_spacing=15)
        
        for cat in items:
            def make_on_click(c):
                return lambda e, current_cat=c: open_add_to_cart_dialog(e.control.page, state, on_action, current_cat)
            
            # Estricto: relación de aspecto controlada para la imagen
            card_content = ft.Column([
                ft.Container(
                    content=build_image(cat, fit="cover", border_radius=ft.BorderRadius(top_left=8, top_right=8, bottom_left=0, bottom_right=0), expand=True),
                    height=180,
                    width=float("inf")
                ),
                ft.Container(
                    content=ft.Column([
                        ft.Text(cat["nombre"], weight=ft.FontWeight.W_600, size=15, color=COLORS["text_dark"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Row([
                            ft.Container(
                                content=ft.Text(tipo, size=10, color="#FFFFFF", weight=ft.FontWeight.W_500),
                                bgcolor=COLORS["primary"],
                                padding=ft.Padding(left=6, right=6, top=2, bottom=2),
                                border_radius=4,
                            ),
                        ]),
                        ft.Row([
                            ft.Text("Desde", size=11, color=COLORS["text_light"]),
                            ft.Text(f"${cat.get('precio_base', cat.get('precio', 0))}", weight=ft.FontWeight.BOLD, size=18, color=COLORS["accent_green"])
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.END)
                    ], spacing=6),
                    padding=ft.Padding(left=12, right=12, top=8, bottom=12),
                    expand=True
                )
            ], spacing=0)
                
            card = ft.Container(
                bgcolor=COLORS["surface"], 
                border=ft.Border.all(1, COLORS["border"]), 
                border_radius=8,
                ink=True, 
                on_click=make_on_click(cat),
                content=card_content,
                shadow=ft.BoxShadow(spread_radius=0, blur_radius=4, color="#1A000000", offset=ft.Offset(0, 2))
            )
            grid.controls.append(card)
            
        sections.append(header)
        sections.append(grid)
        
    # Columna principal scrolleable
    content = ft.Column(
        controls=sections,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=10
    )
    
    return content

# ============================================================


# ========================================
# ui/views/stock_view.py
# ========================================

# ============================================================


def create_stock_view(state: dict, on_action: callable):
    content = None
    stock_form_open = state.get("stock_form_open", False)
    if stock_form_open:
        catalog = state.get("catalog_cache", [])
        options = [ft.dropdown.Option(str(c["id"]), text=c["nombre"]) for c in catalog]
        
        category_dropdown = ft.Dropdown(
            label="Seleccionar del Catálogo", options=options, border_color=COLORS["border"], expand=True, value=options[0].key if options else None
        )

        
        colores = state.get("colores", [])
        color_options = [ft.dropdown.Option(c) for c in colores]
        color_input = ft.Dropdown(label="Color", options=color_options, border_color=COLORS["border"], expand=True, value=color_options[0].key if color_options else None)
        
        materiales = state.get("materiales", [])
        material_options = [ft.dropdown.Option(m) for m in materiales]
        material_input = ft.Dropdown(label="Material / Tipo de Tela", options=material_options, border_color=COLORS["border"], expand=True, value=material_options[0].key if material_options else None)
        desc_input = ft.TextField(label="Descripción Opcional (Max 500)", max_length=500, multiline=True, border_color=COLORS["border"], expand=True)
        price_input = ft.TextField(label="Precio de Venta ($)", border_color=COLORS["border"], expand=True, on_change=format_currency_input)
        qty_input = ft.TextField(label="Cantidad", value="1", border_color=COLORS["border"], expand=True)
        
        selected_photo_path = [None]
        
        async def pick_photo(e):
            result = await ft.FilePicker().pick_files(allow_multiple=False, allowed_extensions=["jpg", "jpeg", "png"])
            if result and len(result) > 0:
                selected_photo_path[0] = result[0].path
                photo_preview.src = result[0].path
                preview_container.visible = True
                drop_zone.visible = False
                preview_container.update()
                drop_zone.update()

        def remove_photo(e):
            selected_photo_path[0] = None
            preview_container.visible = False
            drop_zone.visible = True
            preview_container.update()
            drop_zone.update()

        drop_zone = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.CLOUD_UPLOAD, size=40, color=COLORS["text_light"]),
                    ft.Text("Haz clic para seleccionar la imagen", color=COLORS["text_light"], size=14)
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=5
            ),
            width=400,
            height=120,
            border=ft.Border.all(2, COLORS["border"]),
            border_radius=8,
            bgcolor=COLORS["surface"],
            ink=True,
            alignment=ft.Alignment(0, 0),
            on_click=pick_photo
        )

        photo_preview = ft.Image(src="", width=400, height=200, fit="cover", border_radius=8)
        remove_photo_btn = ft.TextButton(
            "Eliminar foto", 
            icon=ft.Icons.DELETE, 
            icon_color="red",
            on_click=remove_photo
        )
        
        preview_container = ft.Column(
            [photo_preview, remove_photo_btn],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            visible=False
        )

        photo_container = ft.Container(
            content=ft.Column([drop_zone, preview_container], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            alignment=ft.Alignment(0, 0),
            padding=ft.Padding.symmetric(vertical=10, horizontal=0)
        )
        
        form_content = ft.Column([
            category_dropdown,
            ft.Row([color_input, material_input], spacing=15),
            desc_input,
            ft.Row([price_input, qty_input], spacing=15),
            photo_container,
            ft.Row([
                ft.Button("Guardar en Stock", icon=ft.Icons.SAVE, bgcolor=COLORS["accent_green"], color="white",
                    on_click=lambda e: on_action("save_stock_item", {
                        "catalogo_id": category_dropdown.value, "color": color_input.value,
                        "material": material_input.value, "descripcion": desc_input.value,
                        "precio": price_input.value.replace(',', ''), "cantidad": qty_input.value,
                        "url_imagen": selected_photo_path[0] if selected_photo_path[0] else ""
                    })),
                ft.TextButton("Cancelar", on_click=lambda e: on_action("close_stock_form"))
            ], alignment=ft.MainAxisAlignment.END)
        ], spacing=15, scroll=ft.ScrollMode.AUTO, expand=True)
        
        content = ft.Container(
            content=ft.Column([
                ft.Text("Ingresar Mueble al Stock Físico", size=22, weight=ft.FontWeight.BOLD, color=COLORS["text_dark"]),
                ft.Divider(color=COLORS["border"]),
                form_content
            ], expand=True), padding=20, bgcolor=COLORS["surface"], border_radius=12, border=ft.Border.all(1, COLORS["border"]), expand=True
        )
    else:
        grid = ft.GridView(expand=True, max_extent=288, child_aspect_ratio=0.75, spacing=15, run_spacing=15)
        
        add_card = ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.ADD_BOX, size=48, color=COLORS["primary"]),
                ft.Text("Nuevo Ingreso\nde Stock", size=16, weight=ft.FontWeight.BOLD, color=COLORS["primary"], text_align=ft.TextAlign.CENTER)
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=COLORS["secondary"], border_radius=10, border=ft.Border.all(2, COLORS["primary"]),
            on_click=lambda e: on_action("open_stock_form")
        )
        grid.controls.append(add_card)
        
        for st in state.get("stock_cache", []):
            grid.controls.append(create_stock_card(st, False, None, read_only=True))
            
        content = ft.Column([
            ft.Row([
                ft.Text("Inventario Físico (Stock)", size=20, weight=ft.FontWeight.BOLD, color=COLORS["text_dark"]),
                ft.Button("+ Ingresar", bgcolor=COLORS["primary"], color="white", on_click=lambda e: on_action("open_stock_form"))
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Divider(color=COLORS["border"]),
            grid
        ], expand=True)
        

    return content

# ============================================================


# ========================================
# ui/views/client_view.py
# ========================================

# ============================================================

def create_client_panel(state: dict, on_action: callable) -> ft.Container:
    """
    Crea la columna izquierda encargada de mostrar y buscar clientes.
    """
    selected_client = state.get("selected_client")
    
    if selected_client and state.get("viewing_client_details"):
        # VISTA DE DETALLE
        
        # NOMBRE
        if state.get("client_editing_field") == "nombre":
            nombre_input = ft.TextField(value=selected_client["nombre"], label="Nombre", dense=True, text_size=13, expand=True)
            apellido_input = ft.TextField(value=selected_client.get("apellido", ""), label="Apellido", dense=True, text_size=13, expand=True)
            nombre_row = ft.Column([
                ft.Row([nombre_input, apellido_input]),
                ft.Row([
                    ft.IconButton(ft.Icons.CHECK, icon_size=16, icon_color="green", tooltip="Guardar", on_click=lambda e: on_action("save_client_field", {"field": "nombre_apellido", "nombre": nombre_input.value, "apellido": apellido_input.value})),
                    ft.IconButton(ft.Icons.CLOSE, icon_size=16, icon_color="red", tooltip="Cancelar", on_click=lambda e: on_action("set_client_editing_field", None))
                ], alignment=ft.MainAxisAlignment.END)
            ])
        else:
            full_name = f"{selected_client['nombre']} {selected_client.get('apellido', '')}".strip()
            nombre_row = ft.Row([
                ft.Text(full_name, size=22, weight=ft.FontWeight.BOLD, color=COLORS["text_dark"], expand=True),
                ft.IconButton(ft.Icons.EDIT, icon_size=14, tooltip="Editar Nombre", on_click=lambda e: on_action("set_client_editing_field", "nombre"))
            ])

        # TELEFONO
        if state.get("client_editing_field") == "telefono":
            tel_input = ft.TextField(value=selected_client.get("telefono", ""), dense=True, text_size=13, expand=True)
            tel_row = ft.Row([
                ft.Icon(ft.Icons.PHONE, size=16, color=COLORS["text_light"]),
                tel_input,
                ft.IconButton(ft.Icons.CHECK, icon_size=16, icon_color="green", on_click=lambda e: on_action("save_client_field", {"field": "telefono", "value": tel_input.value})),
                ft.IconButton(ft.Icons.CLOSE, icon_size=16, icon_color="red", on_click=lambda e: on_action("set_client_editing_field", None))
            ])
        else:
            tel_row = ft.Row([
                ft.Icon(ft.Icons.PHONE, size=16, color=COLORS["text_light"]), 
                ft.Text(selected_client.get("telefono", ""), expand=True),
                ft.IconButton(ft.Icons.EDIT, icon_size=14, tooltip="Editar Teléfono", on_click=lambda e: on_action("set_client_editing_field", "telefono"))
            ])

        # DOMICILIO
        domicilio_str = selected_client.get("domicilio", "")
        if state.get("client_editing_field") == "domicilio":
            dir_input = ft.TextField(label="Domicilio", value=domicilio_str, dense=True, text_size=13, expand=True)
            ub_row = ft.Row([
                ft.Icon(ft.Icons.LOCATION_ON, size=16, color=COLORS["text_light"]),
                dir_input,
                ft.IconButton(ft.Icons.CHECK, icon_size=16, icon_color="green", tooltip="Guardar", on_click=lambda e: on_action("save_client_field", {"field": "domicilio", "value": dir_input.value})),
                ft.IconButton(ft.Icons.CLOSE, icon_size=16, icon_color="red", tooltip="Cancelar", on_click=lambda e: on_action("set_client_editing_field", None))
            ])
        else:
            if not domicilio_str:
                domicilio_text = ft.Text("Domicilio no especificado", color=COLORS["text_light"], italic=True)
            else:
                domicilio_text = ft.Text(domicilio_str, color=COLORS["text_dark"], expand=True)
                
            ub_row = ft.Row([
                ft.Icon(ft.Icons.LOCATION_ON, size=16, color=COLORS["text_light"]), 
                domicilio_text,
                ft.IconButton(ft.Icons.EDIT, icon_size=14, tooltip="Editar Domicilio", on_click=lambda e: on_action("set_client_editing_field", "domicilio"))
            ])

        content = ft.Column([
            ft.Row([
                ft.IconButton(
                    icon=ft.Icons.ARROW_BACK, 
                    on_click=lambda e: on_action("close_client_details", None),
                    tooltip="Volver a la lista"
                ),
            ]),
            ft.CircleAvatar(content=ft.Icon(ft.Icons.PERSON, size=30), radius=40, bgcolor=COLORS["secondary"]),
            nombre_row,
            ft.Divider(color=COLORS["border"]),
            
            ft.Text("Contacto", weight=ft.FontWeight.W_600, color=COLORS["text_dark"]),
            tel_row,
            
            ft.Divider(color=COLORS["border"]),
            ft.Text("Domicilio", weight=ft.FontWeight.W_600, color=COLORS["text_dark"]),
            ub_row,
            
            ft.Divider(color=COLORS["border"]),
            ft.Text("Últimos pedidos", weight=ft.FontWeight.W_600, color=COLORS["text_dark"]),
            ft.Column([
                ft.Text(f"{p['id']}: {p.get('item', 'Pedido')}  {p['fecha']}", size=13, color=COLORS["text_dark"]) for p in selected_client.get("pedidos_recientes", [])
            ] if selected_client.get("pedidos_recientes") else [ft.Text("Sin pedidos recientes", size=13, color=COLORS["text_light"], italic=True)]),

            ft.Divider(color=COLORS["border"]),
            ft.Container(
                content=ft.ElevatedButton(
                    content=ft.Row([
                        ft.Icon(ft.Icons.DELETE_OUTLINE, size=18, color="white"),
                        ft.Text("Eliminar contacto", color="white", weight=ft.FontWeight.W_600),
                    ], alignment=ft.MainAxisAlignment.CENTER, spacing=8),
                    style=ft.ButtonStyle(
                        bgcolor={
                            ft.ControlState.DEFAULT: COLORS.get("accent_red", "#E74C3C"),
                            ft.ControlState.HOVERED: "#C0392B",
                        },
                        shape=ft.RoundedRectangleBorder(radius=8),
                        elevation={ft.ControlState.DEFAULT: 0, ft.ControlState.HOVERED: 4},
                        animation_duration=200,
                    ),
                    on_click=lambda e: on_action("delete_client", selected_client["id"]),
                ),
                width=float("inf"),
                padding=ft.Padding(left=0, right=0, top=8, bottom=4),
            ),
        ], scroll=ft.ScrollMode.AUTO, expand=True)
    else:
        # VISTA DE LISTA
        clients_cache = state.get("clients_cache", [])
        clients_limit = state.get("clients_limit", 50)
        has_more_clients = len(clients_cache) >= clients_limit

        # ── Lista de clientes (se construye primero para que on_change pueda referenciarla) ──
        clients_list = ft.ListView(expand=True, spacing=5)

        def _build_client_tile(client: dict) -> ft.GestureDetector:
            """Crea un tile de cliente reutilizable."""
            nombre_str = client.get('nombre', '').strip()
            apellido_str = client.get('apellido', '').strip()
            full_name = f"{nombre_str} {apellido_str}".strip()

            name_elements = [ft.Text(full_name, weight=ft.FontWeight.W_500)]
            telefono = client.get("telefono", "")
            subtitle_text = str(telefono).strip() if telefono else ""
            if subtitle_text:
                name_elements.append(ft.Text(subtitle_text, color=COLORS["text_light"], size=13))

            is_selected = (
                state.get("selected_client", {}).get("id") == client.get("id")
                if state.get("selected_client") else False
            )

            card_content = ft.Container(
                content=ft.Column(name_elements, spacing=2),
                padding=ft.Padding.symmetric(horizontal=15, vertical=10),
                border_radius=8,
                bgcolor="black12" if is_selected else "surface",
                shadow=None if is_selected else ft.BoxShadow(
                    spread_radius=0, blur_radius=4,
                    color="black12", offset=ft.Offset(0, 1)
                )
            )
            return ft.GestureDetector(
                content=card_content,
                on_tap_down=lambda e, c=client: on_action("select_client", c),
                on_tap=lambda e, c=client: on_action("select_client", c),
                on_double_tap=lambda e, c=client: on_action("view_client_details", c),
                mouse_cursor=ft.MouseCursor.CLICK
            )

        def _populate_list(filtered: list):
            """Rellena clients_list con los clientes dados, sin re-renderizar la vista."""
            clients_list.controls.clear()
            for client in filtered:
                clients_list.controls.append(_build_client_tile(client))
            if has_more_clients and not filtered != clients_cache:
                clients_list.controls.append(load_more_container)
            try:
                clients_list.update()
            except Exception:
                pass  # Todavía no está en el árbol de Flet en el primer render

        def _on_search_change(e):
            """
            Filtrado local en tiempo real:
            - Filtra clients_cache en memoria → no hay re-render → el TextField NO pierde el foco.
            - Actualiza state para que el valor persista entre renders.
            - NO llama a refresh_clients_cache() para evitar el re-render completo.
            """
            term = e.control.value.strip().lower()
            state["clients_filter_text"] = e.control.value  # Mantener sincronizado
            if not term:
                _populate_list(clients_cache)
            else:
                filtered = [
                    c for c in clients_cache
                    if term in (c.get("nombre") or "").lower()
                    or term in (c.get("apellido") or "").lower()
                    or term in (c.get("telefono") or "").lower()
                ]
                _populate_list(filtered)

        # ── Campo de búsqueda ──
        search_row = ft.Row([
            ft.TextField(
                hint_text="Buscar cliente...",
                value=state.get("clients_filter_text", ""),
                expand=True,
                dense=True,
                content_padding=10,
                border_color=COLORS["border"],
                # on_change: filtrado local instantáneo, sin perder el foco
                on_change=_on_search_change,
                # on_submit: búsqueda completa en BD (cubre clientes fuera del límite cargado)
                on_submit=lambda e: on_action("search_clients", e.control.value),
                icon=ft.Icons.SEARCH
            )
        ])

        btn_nuevo_cliente = ft.Button(
            "+ Nuevo Cliente",
            bgcolor=COLORS["primary"],
            color="white",
            width=float('inf'),
            on_click=lambda e: on_action("open_client_dialog", None)
        )

        # Poblar la lista inicial (respetando el filtro activo si hay uno)
        initial_term = state.get("clients_filter_text", "").strip().lower()
        if initial_term:
            initial_clients = [
                c for c in clients_cache
                if initial_term in (c.get("nombre") or "").lower()
                or initial_term in (c.get("apellido") or "").lower()
                or initial_term in (c.get("telefono") or "").lower()
            ]
        else:
            initial_clients = clients_cache

        for client in initial_clients:
            clients_list.controls.append(_build_client_tile(client))

        if has_more_clients:
            load_more_container = ft.Container(alignment=ft.Alignment(0, 0), padding=5)

            def on_click_more_clients(e):
                load_more_container.content = ft.Row([
                    ft.ProgressRing(width=16, height=16, stroke_width=2, color=COLORS["primary"]),
                    ft.Text("Cargando clientes...", size=13, color=COLORS["text_light"])
                ], alignment=ft.MainAxisAlignment.CENTER, spacing=8)
                try:
                    load_more_container.update()
                except RuntimeError:
                    return

                import time
                time.sleep(0.15)
                on_action("load_more_clients")

            load_more_container.content = ft.TextButton(
                "Cargar más clientes...",
                icon=ft.Icons.ADD,
                on_click=on_click_more_clients
            )
            clients_list.controls.append(load_more_container)

        content = ft.Column([
            search_row,
            btn_nuevo_cliente,
            ft.Divider(color=COLORS["border"]),
            clients_list
        ])

    is_factura = state.get("central_view", "catalogo") == "catalogo"
    return ft.Container(
        content=content if is_factura else None,
        visible=is_factura,
        width=280 if is_factura else 0,
        padding=15 if is_factura else 0,
        bgcolor=COLORS["surface"] if is_factura else None,
        border_radius=15,
        border=ft.Border.all(1, COLORS["border"]) if is_factura else None
    )

# ============================================================


# ========================================
# ui/views/config_view.py
# ========================================

# ============================================================


def create_config_view(state: dict, on_action: callable):
    content = None
    # Interfaz básica de Configuración
    config_list = ft.ListView(expand=True, spacing=10)
    config_list.controls.append(ft.Text("Gestión de Inventario (Config.json)", size=20, weight=ft.FontWeight.BOLD, color=COLORS["text_dark"]))
    
    for prod in (state.get("catalog_cache") or []):
        config_list.controls.append(
            ft.ListTile(
                leading=build_image(prod, width=50, height=50, fit="cover"),
                title=ft.Text(prod["nombre"], weight=ft.FontWeight.BOLD),
                subtitle=ft.Text(f"Precio: ${prod.get('precio_base', prod.get('precio', 0))} | Stock actual: {prod.get('stock', 0)}"),
                trailing=ft.IconButton(ft.Icons.EDIT, tooltip="Editar (En desarrollo)")
            )
        )
        
    content = ft.Container(
        content=config_list,
        padding=20, bgcolor=COLORS["surface"], border_radius=10, expand=True
    )

    return content

def create_config_catalog_tab(state: dict, on_action: callable) -> ft.Container:
    if state.get("catalogo_form_open", False):
        nombre_input = ft.TextField(label="Nombre del Modelo", expand=True, border_color=COLORS["border"])
        precio_input = ft.TextField(label="Precio Base ($)", width=150, border_color=COLORS["border"], prefix="$", on_change=format_currency_input)
        
        tipo_dropdown = ft.Dropdown(
            label="Tipo (ej. Sofá)",
            options=[ft.dropdown.Option(t) for t in (state.get("tipos") or [])],
            expand=True, border_color=COLORS["border"]
        )
        tipo_input = ft.TextField(label="Nuevo Tipo", expand=True, border_color=COLORS["border"], visible=False)
        
        def toggle_new_tipo(e):
            page = e.control.page
            if tipo_input.visible:
                if tipo_input.value:
                    on_action("add_tipo", tipo_input.value)
                    return
                tipo_input.visible = False
                tipo_dropdown.visible = True
                new_tipo_btn.icon = ft.Icons.ADD
            else:
                tipo_dropdown.visible = False
                tipo_input.visible = True
                new_tipo_btn.icon = ft.Icons.CHECK
            page.update()
            
        new_tipo_btn = ft.IconButton(icon=ft.Icons.ADD, on_click=toggle_new_tipo, tooltip="Agregar nuevo tipo", icon_color=COLORS["primary"])
        
        area_dropdown = ft.Dropdown(
            label="Área (ej. Tapicería)",
            options=[ft.dropdown.Option(a) for a in (state.get("areas") or [])],
            expand=True, border_color=COLORS["border"]
        )
        area_input = ft.TextField(label="Nueva Área", expand=True, border_color=COLORS["border"], visible=False)
        
        def toggle_new_area(e):
            page = e.control.page
            if area_input.visible:
                if area_input.value:
                    on_action("add_area", area_input.value)
                    return
                area_input.visible = False
                area_dropdown.visible = True
                new_area_btn.icon = ft.Icons.ADD
            else:
                area_dropdown.visible = False
                area_input.visible = True
                new_area_btn.icon = ft.Icons.CHECK
            page.update()

        new_area_btn = ft.IconButton(icon=ft.Icons.ADD, on_click=toggle_new_area, tooltip="Agregar nueva área", icon_color=COLORS["primary"])
        
        selected_photo_path = [None]
        photo_preview = ft.Image(src="", width=150, height=150, fit="cover", border_radius=8)
        
        async def open_file_picker(e):
            result = await ft.FilePicker().pick_files(allow_multiple=False, allowed_extensions=["png", "jpg", "jpeg", "webp"])
            if result and len(result) > 0:
                selected_photo_path[0] = result[0].path
                photo_preview.src = result[0].path
                photo_preview.update()
                preview_container.visible = True
                drop_zone.visible = False
                photo_container.update()

        def remove_photo(e):
            selected_photo_path[0] = None
            preview_container.visible = False
            drop_zone.visible = True
            photo_container.update()

        drop_zone = ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.ADD_A_PHOTO, size=40, color=COLORS["text_light"]),
                ft.Text("Seleccionar Imagen de Referencia", color=COLORS["text_light"])
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            width=300, height=150, alignment=ft.Alignment(0, 0),
            border=ft.Border.all(2, COLORS["border"]), border_radius=10, ink=True,
            on_click=open_file_picker
        )
        
        remove_photo_btn = ft.TextButton("Eliminar foto", icon=ft.Icons.DELETE, icon_color="red", on_click=remove_photo)
        preview_container = ft.Column([photo_preview, remove_photo_btn], horizontal_alignment=ft.CrossAxisAlignment.CENTER, visible=False)
        photo_container = ft.Container(content=ft.Column([drop_zone, preview_container], horizontal_alignment=ft.CrossAxisAlignment.CENTER), alignment=ft.Alignment(0, 0), padding=ft.Padding.symmetric(vertical=10))
        
        form_content = ft.Column([
            nombre_input,
            ft.Row([tipo_dropdown, tipo_input, new_tipo_btn], spacing=10),
            ft.Row([area_dropdown, area_input, new_area_btn], spacing=10),
            precio_input,
            photo_container,
            ft.Row([
                ft.ElevatedButton("Guardar Modelo", icon=ft.Icons.SAVE, bgcolor=COLORS["accent_green"], color="white",
                    on_click=lambda e: on_action("save_catalogo_item", {
                        "nombre": nombre_input.value,
                        "tipo": tipo_input.value if tipo_input.visible else tipo_dropdown.value,
                        "area": area_input.value if area_input.visible else area_dropdown.value,
                        "precio_base": precio_input.value.replace(',', ''),
                        "url_imagen": selected_photo_path[0]
                    })),
                ft.TextButton("Cancelar", on_click=lambda e: on_action("close_catalogo_form"))
            ], alignment=ft.MainAxisAlignment.END)
        ], spacing=15, scroll=ft.ScrollMode.AUTO, expand=True)
        
        return ft.Container(
            content=ft.Column([
                ft.Text("Agregar Nuevo Modelo al Catálogo", size=22, weight=ft.FontWeight.BOLD, color=COLORS["text_dark"]),
                ft.Divider(color=COLORS["border"]),
                form_content
            ], expand=True), padding=20, expand=True
        )

    grid = ft.GridView(
        expand=True,
        max_extent=320,
        child_aspect_ratio=1.4,
        spacing=15,
        run_spacing=15
    )
    for prod in (state.get("catalog_cache") or []):
        grid.controls.append(
            ft.Container(
                content=ft.Row([
                    build_image(prod, width=90, height=90, fit="cover", border_radius=8),
                    ft.Column([
                        ft.Text(prod["nombre"], weight=ft.FontWeight.BOLD, size=15, color=COLORS["text_dark"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(prod.get("area", "Ebanistería") + " - " + prod.get("tipo", "Mueble"), size=11, color=COLORS["text_light"]),
                        ft.Row([
                            ft.Text(f"${prod.get('precio_base', prod.get('precio', 0))}", weight=ft.FontWeight.BOLD, size=15, color=COLORS["primary"]),
                            ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color=COLORS["accent_red"], icon_size=18, tooltip="Eliminar (No implementado)")
                        ], spacing=5, alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                    ], expand=True, alignment=ft.MainAxisAlignment.SPACE_EVENLY)
                ], spacing=10),
                padding=10,
                bgcolor=COLORS["surface"],
                border_radius=12,
                border=ft.Border.all(1, COLORS["border"]),
                shadow=ft.BoxShadow(spread_radius=1, blur_radius=4, color="#10000000")
            )
        )
        
    return ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text("Gestión de Catálogo", size=20, weight=ft.FontWeight.BOLD, color=COLORS["text_dark"]),
                ft.ElevatedButton("Agregar Modelo", icon=ft.Icons.ADD, bgcolor=COLORS["primary"], color=COLORS["surface"], on_click=lambda e: on_action("open_catalogo_form"))
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Divider(color=COLORS["border"]),
            grid
        ], expand=True),
        padding=20, expand=True
    )

def create_config_network_tab(state: dict, on_action: callable) -> ft.Container:
    api_config = state.get("api_config", {})
    api_url = api_config.get("api_url", "")
    api_token = api_config.get("api_token", "")
    
    url_field = ft.TextField(label="URL del Servidor / API", value=api_url, expand=True, border_color=COLORS["border"], prefix_icon=ft.Icons.LINK)
    token_field = ft.TextField(label="Token de Autenticación", value=api_token, password=True, can_reveal_password=True, expand=True, border_color=COLORS["border"], prefix_icon=ft.Icons.SECURITY)
    
    return ft.Container(
        content=ft.Column([
            ft.Text("Configuración de Red y Seguridad", size=20, weight=ft.FontWeight.BOLD, color=COLORS["text_dark"]),
            ft.Text("Preparado para futura sincronización en la nube (ej. a través de VPN o Endpoint público).", size=13, color=COLORS["text_light"]),
            ft.Divider(color=COLORS["border"]),
            ft.Column([
                ft.Row([url_field], spacing=20),
                ft.Row([token_field], spacing=20),
                ft.Container(
                    content=ft.Row([
                        ft.ElevatedButton("Guardar Configuración de Red", icon=ft.Icons.SAVE, bgcolor=COLORS["primary"], color=COLORS["surface"], 
                            on_click=lambda e: on_action("save_api_config", {"api_url": url_field.value, "api_token": token_field.value}))
                    ], alignment=ft.MainAxisAlignment.END),
                    padding=ft.Padding.only(top=10)
                )
            ])
        ], expand=True),
        padding=20, expand=True
    )

def create_config_materials_tab(state: dict, on_action: callable) -> ft.Container:
    materiales = state.get("materiales") or []
    colores = state.get("colores") or []
    
    mat_input = ft.TextField(label="Nuevo Material", expand=True, height=40, content_padding=10, text_size=13, border_color=COLORS["border"])
    col_input = ft.TextField(label="Nuevo Color", expand=True, height=40, content_padding=10, text_size=13, border_color=COLORS["border"])
    
    def build_list(items, remove_action):
        lv = ft.ListView(expand=True, spacing=5)
        for item in items:
            lv.controls.append(ft.Container(
                content=ft.Row([
                    ft.Text(item, size=14, color=COLORS["text_dark"], expand=True),
                    ft.IconButton(icon=ft.Icons.DELETE, icon_color=COLORS["accent_red"], icon_size=16, on_click=lambda e, i=item: on_action(remove_action, i))
                ]),
                padding=ft.Padding.symmetric(horizontal=10, vertical=0),
                bgcolor=COLORS["surface"],
                border_radius=5,
                border=ft.Border.all(1, COLORS["border"])
            ))
        return lv

    return ft.Container(
        content=ft.Column([
            ft.Text("Materiales y Colores", size=20, weight=ft.FontWeight.BOLD, color=COLORS["text_dark"]),
            ft.Text("Gestiona las opciones disponibles al registrar stock y encargos.", size=13, color=COLORS["text_light"]),
            ft.Divider(color=COLORS["border"]),
            ft.Row([
                ft.Column([
                    ft.Text("Materiales (Telas, Maderas, etc.)", weight=ft.FontWeight.BOLD, color=COLORS["text_dark"]),
                    ft.Row([mat_input, ft.IconButton(icon=ft.Icons.ADD_CIRCLE, icon_color=COLORS["primary"], on_click=lambda e: (on_action("add_material", mat_input.value) if mat_input.value else None))]),
                    ft.Container(content=build_list(materiales, "remove_material"), expand=True, border=ft.Border.all(1, COLORS["border"]), border_radius=5, padding=5)
                ], expand=True),
                ft.VerticalDivider(color=COLORS["border"]),
                ft.Column([
                    ft.Text("Colores", weight=ft.FontWeight.BOLD, color=COLORS["text_dark"]),
                    ft.Row([col_input, ft.IconButton(icon=ft.Icons.ADD_CIRCLE, icon_color=COLORS["primary"], on_click=lambda e: (on_action("add_color", col_input.value) if col_input.value else None))]),
                    ft.Container(content=build_list(colores, "remove_color"), expand=True, border=ft.Border.all(1, COLORS["border"]), border_radius=5, padding=5)
                ], expand=True)
            ], expand=True)
        ], expand=True),
        padding=20, expand=True
    )

def create_full_config_layout(state: dict, on_action: callable) -> ft.Container:
    active_tab = state.get("config_active_tab", 0)
    
    rail = ft.NavigationRail(
        selected_index=active_tab,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=100,
        min_extended_width=150,
        group_alignment=-0.9,
        destinations=[
            ft.NavigationRailDestination(icon=ft.Icons.LIBRARY_BOOKS_OUTLINED, selected_icon=ft.Icons.LIBRARY_BOOKS, label="Catálogo"),
            ft.NavigationRailDestination(icon=ft.Icons.CLOUD_SYNC_OUTLINED, selected_icon=ft.Icons.CLOUD_SYNC, label="Red (API)"),
            ft.NavigationRailDestination(icon=ft.Icons.PALETTE_OUTLINED, selected_icon=ft.Icons.PALETTE, label="Materiales"),
        ],
        on_change=lambda e: on_action("change_config_tab", e.control.selected_index),
        bgcolor=COLORS["surface"]
    )
    
    right_content = ft.Container()
    if active_tab == 0:
        right_content = create_config_catalog_tab(state, on_action)
    elif active_tab == 1:
        right_content = create_config_network_tab(state, on_action)
    elif active_tab == 2:
        right_content = create_config_materials_tab(state, on_action)
        
    back_btn = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.ARROW_BACK, color=COLORS["surface"], size=18),
            ft.Text("Volver Atrás", color=COLORS["surface"], weight=ft.FontWeight.BOLD, size=13)
        ], alignment=ft.MainAxisAlignment.CENTER, spacing=6),
        bgcolor=COLORS["primary"],
        padding=ft.Padding.symmetric(horizontal=16, vertical=10),
        border_radius=8,
        on_click=lambda e: on_action("change_view", "catalogo"),
        ink=True
    )
    
    header = ft.Row([
        ft.Column([
            ft.Text("Configuración del Sistema", size=26, weight=ft.FontWeight.BOLD, color=COLORS["text_dark"]),
            ft.Text("Módulos de administración y parámetros de la tienda", size=13, color=COLORS["text_light"]),
        ]),
        back_btn
    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    return ft.Container(
        content=ft.Column([
            header,
            ft.Divider(color=COLORS["border"], height=25),
            ft.Row([
                rail,
                ft.VerticalDivider(width=1, color=COLORS["border"]),
                right_content
            ], expand=True)
        ], expand=True),
        padding=25,
        bgcolor=COLORS["background"],
        expand=True
    )

# ============================================================


# ========================================
# ui/views/invoice_view.py
# ========================================

# ============================================================

def _make_load_more_btn(on_click_handler):
    """Crea el botón premium de 'Descubrir más facturas'."""
    return ft.ElevatedButton(
        content=ft.Row([
            ft.Icon(ft.Icons.KEYBOARD_DOUBLE_ARROW_DOWN_ROUNDED, size=20),
            ft.Text("Descubrir más facturas", size=14, weight=ft.FontWeight.BOLD)
        ], alignment=ft.MainAxisAlignment.CENTER, spacing=8),
        style=ft.ButtonStyle(
            color={
                ft.ControlState.HOVERED: COLORS["background"],
                ft.ControlState.DEFAULT: COLORS["primary"],
            },
            bgcolor={
                ft.ControlState.HOVERED: COLORS["primary"],
                ft.ControlState.DEFAULT: COLORS["secondary"],
            },
            padding=ft.Padding.symmetric(horizontal=35, vertical=20),
            shape=ft.RoundedRectangleBorder(radius=30),
            elevation={ft.ControlState.DEFAULT: 0, ft.ControlState.HOVERED: 8},
            animation_duration=300
        ),
        on_click=on_click_handler,
    )

def create_invoice_view(state: dict, on_action: callable, _fui):
    content = None
    filter_text = state.get("facturas_filter_text", "").strip()
    filter_period = state.get("facturas_filter_period", "Hoy")
    start_date_str = state.get("facturas_filter_start_date", "").strip()
    end_date_str = state.get("facturas_filter_end_date", "").strip()
    
    filtered_facturas = state.get("facturas_cache", [])
    
    search_field = ft.TextField(
        hint_text="Buscar por cliente, fecha o folio...",
        value=filter_text,
        expand=True,
        dense=True,
        prefix_icon=ft.Icons.SEARCH,
        border_color=COLORS["border"],
        on_submit=lambda e: on_action("update_factura_filter", {"text": e.control.value})
    )
    
    search_btn = ft.IconButton(
        icon=ft.Icons.SEARCH,
        icon_color=COLORS["primary"],
        tooltip="Buscar",
        on_click=lambda e: on_action("update_factura_filter", {"text": search_field.value})
    )
    
    period_dropdown = ft.Dropdown(
        label="Período",
        value=filter_period,
        dense=True,
        border_color=COLORS["border"],
        width=200,
        options=[
            ft.dropdown.Option("Hoy"),
            ft.dropdown.Option("Todo"),
            ft.dropdown.Option("Esta semana"),
            ft.dropdown.Option("Este mes"),
            ft.dropdown.Option("Rango personalizado")
        ],
        on_select=lambda e: on_action("update_factura_filter", {"period": e.control.value})
    )
    
    custom_date_row = None
    if filter_period == "Rango personalizado":
        def open_start_picker(e):
            dp = ft.DatePicker(
                on_change=lambda ev: on_action("update_factura_filter", {"start_date": ev.control.value.strftime("%Y-%m-%d")}) if ev.control.value else None
            )
            e.control.page.overlay.append(dp)
            dp.open = True
            e.control.page.update()
            
        def open_end_picker(e):
            dp = ft.DatePicker(
                on_change=lambda ev: on_action("update_factura_filter", {"end_date": ev.control.value.strftime("%Y-%m-%d")}) if ev.control.value else None
            )
            e.control.page.overlay.append(dp)
            dp.open = True
            e.control.page.update()
            
        custom_date_row = ft.Row([
            ft.TextField(
                label="Desde (AAAA-MM-DD)",
                value=start_date_str,
                dense=True,
                expand=True,
                border_color=COLORS["border"],
                on_change=lambda e: on_action("update_factura_filter", {"start_date": e.control.value})
            ),
            ft.IconButton(
                icon=ft.Icons.CALENDAR_MONTH,
                icon_color=COLORS["primary"],
                tooltip="Elegir Fecha Inicio",
                on_click=open_start_picker
            ),
            ft.TextField(
                label="Hasta (AAAA-MM-DD)",
                value=end_date_str,
                dense=True,
                expand=True,
                border_color=COLORS["border"],
                on_change=lambda e: on_action("update_factura_filter", {"end_date": e.control.value})
            ),
            ft.IconButton(
                icon=ft.Icons.CALENDAR_MONTH,
                icon_color=COLORS["primary"],
                tooltip="Elegir Fecha Fin",
                on_click=open_end_picker
            )
        ], spacing=10)
        
    clear_filters_btn = ft.IconButton(
        icon=ft.Icons.CLEAR_ALL,
        icon_color=COLORS["accent_red"],
        tooltip="Limpiar Filtros",
        on_click=lambda e: on_action("update_factura_filter", {"text": "", "period": "Todo", "start_date": "", "end_date": ""})
    )
    
    filters_bar = ft.Column([
        ft.Row([
            search_field,
            search_btn,
            period_dropdown,
            clear_filters_btn
        ], spacing=10),
    ], spacing=10)
    
    if custom_date_row:
        filters_bar.controls.append(custom_date_row)

    # -----------------------------------------------------------------------
    # SINGLETON DE CONTROLES: _fui siempre apunta a los objetos VIVOS en el
    # arbol de Flet. Esto resuelve el problema de los closures capturando
    # objetos nuevos (no en el arbol) en cada re-render.
    # -----------------------------------------------------------------------
    _fui.state_ref = state  # app_state es siempre el mismo dict, OK

    if _fui.data_table is None:
        # PRIMER RENDER: crear todos los controles y registrarlos en el singleton
        from api_client import load_config
        company_info = load_config()

        def build_row_for_fact(fact):
            """Construye una DataRow a partir de un dict de factura."""
            garantia = fact.get("garantia_hasta") or "—"
            status_garantia = fact.get("status_garantia") or "No Aplica"
            venc_garantia = fact.get("venc_garantia") or ""
            if venc_garantia:
                venc_garantia = venc_garantia[:10]
            
            # Formatear el texto de garantía y color
            garantia_color = COLORS.get("secondary", "#E0E5EC")
            texto_color = COLORS.get("text_dark", "#000")
            if status_garantia == "Vigente":
                garantia_color = COLORS.get("accent_green", "#2E8B57")
                texto_color = "#FFFFFF"
            elif status_garantia == "Expirada":
                garantia_color = COLORS.get("accent_red", "#E74C3C")
                texto_color = "#FFFFFF"
            
            garantia_text = garantia
            if venc_garantia:
                garantia_text += f"\nVence: {venc_garantia}"

            # — Resolución de nombre de cliente —
            # Si es facturación rápida: leer del JSON guardado en la columna 'cliente'.
            # Si es factura normal: usar el JOIN con la tabla clientes.
            es_rapida = bool(fact.get("facturacion_rapida", 0))
            if es_rapida:
                import json as _json
                raw_cliente = fact.get("cliente") or "{}"
                try:
                    c_data = _json.loads(raw_cliente)
                except Exception:
                    c_data = {}
                cliente_nombre = c_data.get("nombre", "").strip() or "Consumidor Final"
            else:
                nombre = fact.get("cliente_nombre") or ""
                apellido = fact.get("cliente_apellido") or ""
                cliente_nombre = f"{nombre} {apellido}".strip() or "Sin cliente"

            fecha_str = fact.get("fecha") or "—"
            if len(fecha_str) > 10:
                fecha_str = fecha_str[:10]
            total_val = fact.get("total") or 0.0

            # Célula de cliente: nombre + badge "Rápida" si aplica
            nombre_cell_controls = [ft.Text(cliente_nombre, weight=ft.FontWeight.W_500)]
            if es_rapida:
                nombre_cell_controls.append(ft.Container(
                    content=ft.Text("Rápida", size=9, color="#FFFFFF", weight=ft.FontWeight.W_600),
                    bgcolor="#8E44AD",
                    border_radius=4,
                    padding=ft.Padding(left=5, right=5, top=2, bottom=2),
                ))
            nombre_cell = ft.Row(controls=nombre_cell_controls, spacing=6, tight=True)

            actions = ft.Row([
                ft.Container(content=ft.IconButton(ft.Icons.REMOVE_RED_EYE, tooltip="Ver Detalles", on_click=lambda e, f=fact: open_full_invoice_dialog(e.control.page, f, state, on_action)), padding=0),
                ft.Container(content=ft.IconButton(ft.Icons.DOWNLOAD, tooltip="Descargar", on_click=lambda e, f=fact: open_download_dialog(e.control.page, f, company_info)), padding=0),
                ft.Container(content=ft.IconButton(ft.Icons.SHARE, tooltip="Compartir WhatsApp", on_click=lambda e, f=fact: open_share_dialog(e.control.page, f, company_info)), padding=0),
            ], spacing=0)
            return ft.DataRow(cells=[
                ft.DataCell(ft.Text(f"#{fact.get('id', '')}", weight=ft.FontWeight.BOLD, color=COLORS["text_dark"])),
                ft.DataCell(nombre_cell),
                ft.DataCell(ft.Text(fecha_str, color=COLORS["text_light"])),
                ft.DataCell(ft.Container(
                    content=ft.Text(garantia_text, size=11, color=texto_color, text_align=ft.TextAlign.CENTER),
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                    bgcolor=garantia_color,
                    border_radius=4
                )),
                ft.DataCell(ft.Text(f"${total_val:.2f}", weight=ft.FontWeight.BOLD, color=COLORS["accent_green"])),
                ft.DataCell(actions),
            ])

        _fui.build_row_fn = build_row_for_fact

        def on_click_more_invoices(e):
            """Carga mas facturas usando SIEMPRE _fui (referencias vivas al arbol)."""
            page = e.control.page
            try:
                # Spinner - modificamos el objeto VIVO via _fui
                _fui.load_more_container.content = ft.Container(
                    content=ft.Row([
                        ft.ProgressRing(width=16, height=16, stroke_width=2, color=COLORS["primary"]),
                        ft.Text("Consultando registros...", size=14, color=COLORS["primary"], weight=ft.FontWeight.W_600)
                    ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
                    padding=ft.Padding.symmetric(horizontal=30, vertical=15),
                    bgcolor=COLORS["secondary"],
                    border_radius=30,
                )
                page.update()

                # Calcular nuevo limite
                s = _fui.state_ref
                current_limit = s.get("facturas_limit", 50)
                new_limit = current_limit + 50

                from api_client import get_all_facturas
                search_term = s.get("facturas_filter_text", "").strip() or None
                period_val = s.get("facturas_filter_period", "Hoy")
                start_date = s.get("facturas_filter_start_date", "").strip() or None
                end_date = s.get("facturas_filter_end_date", "").strip() or None

                all_new = get_all_facturas(search=search_term, period=period_val, start_date=start_date, end_date=end_date, limit=new_limit)

                existing_ids = set()
                for row in _fui.data_table.rows:
                    try:
                        existing_ids.add(row.cells[0].content.value.lstrip('#'))
                    except:
                        pass

                nuevas = [f for f in all_new if str(f.get('id', '')) not in existing_ids]

                if nuevas:
                    for f in nuevas:
                        _fui.data_table.rows.append(_fui.build_row_fn(f))
                    # Reasignar para disparar el dirty flag de Flet
                    _fui.data_table.rows = list(_fui.data_table.rows)
                    s["facturas_limit"] = new_limit
                    s["facturas_cache"] = all_new

                if len(all_new) < new_limit:
                    _fui.load_more_container.visible = False
                else:
                    _fui.load_more_container.content = _make_load_more_btn(on_click_more_invoices)
                    _fui.load_more_container.visible = True

                page.update()

            except Exception as ex:
                page.snack_bar = ft.SnackBar(
                    ft.Text(f"Error: {ex}", color="white"), bgcolor="red"
                )
                page.snack_bar.open = True
                page.update()
                raise

        rows = [build_row_for_fact(f) for f in filtered_facturas] if filtered_facturas else []

        _fui.data_table = ft.DataTable(
            expand=True,
            columns=[
                ft.DataColumn(ft.Text("Número", color="white", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Cliente", color="white", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Fecha", color="white", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Garantía", color="white", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Importe", color="white", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Acciones", color="white", weight=ft.FontWeight.BOLD)),
            ],
            rows=rows,
            bgcolor=COLORS["surface"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=12,
            heading_row_color=COLORS["primary"],
            heading_row_height=45,
            data_row_min_height=55,
            data_row_max_height=55,
            column_spacing=20,
            horizontal_lines=ft.BorderSide(1, COLORS["secondary"]),
        )
        _fui.load_more_container = ft.Container(
            alignment=ft.Alignment(0, 0),
            padding=10,
            content=_make_load_more_btn(on_click_more_invoices),
            visible=len(filtered_facturas) >= state.get("facturas_limit", 50)
        )
        _fui.invoices_list = ft.Column(
            expand=True, spacing=15,
            scroll=ft.ScrollMode.ALWAYS,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH
        )
    else:
        # RE-RENDER: los controles ya existen en el arbol. Solo actualizar contenido.
        from api_client import load_config
        company_info = load_config()

        def build_row_for_fact(fact):
            garantia = fact.get("garantia_hasta") or "—"
            status_garantia = fact.get("status_garantia") or "No Aplica"
            venc_garantia = fact.get("venc_garantia") or ""
            if venc_garantia:
                venc_garantia = venc_garantia[:10]
            
            garantia_color = COLORS.get("secondary", "#E0E5EC")
            texto_color = COLORS.get("text_dark", "#000")
            if status_garantia == "Vigente":
                garantia_color = COLORS.get("accent_green", "#2E8B57")
                texto_color = "#FFFFFF"
            elif status_garantia == "Expirada":
                garantia_color = COLORS.get("accent_red", "#E74C3C")
                texto_color = "#FFFFFF"
            
            garantia_text = garantia
            if venc_garantia:
                garantia_text += f"\nVence: {venc_garantia}"

            # — Resolución de nombre de cliente —
            es_rapida = bool(fact.get("facturacion_rapida", 0))
            if es_rapida:
                import json as _json
                raw_cliente = fact.get("cliente") or "{}"
                try:
                    c_data = _json.loads(raw_cliente)
                except Exception:
                    c_data = {}
                cliente_nombre = c_data.get("nombre", "").strip() or "Consumidor Final"
            else:
                nombre = fact.get("cliente_nombre") or ""
                apellido = fact.get("cliente_apellido") or ""
                cliente_nombre = f"{nombre} {apellido}".strip() or "Sin cliente"

            fecha_str = fact.get("fecha") or "—"
            if len(fecha_str) > 10:
                fecha_str = fecha_str[:10]
            total_val = fact.get("total") or 0.0

            nombre_cell_controls = [ft.Text(cliente_nombre, weight=ft.FontWeight.W_500)]
            if es_rapida:
                nombre_cell_controls.append(ft.Container(
                    content=ft.Text("Rápida", size=9, color="#FFFFFF", weight=ft.FontWeight.W_600),
                    bgcolor="#8E44AD",
                    border_radius=4,
                    padding=ft.Padding(left=5, right=5, top=2, bottom=2),
                ))
            nombre_cell = ft.Row(controls=nombre_cell_controls, spacing=6, tight=True)

            actions = ft.Row([
                ft.Container(content=ft.IconButton(ft.Icons.REMOVE_RED_EYE, tooltip="Ver Detalles", on_click=lambda e, f=fact: open_full_invoice_dialog(e.control.page, f, state, on_action)), padding=0),
                ft.Container(content=ft.IconButton(ft.Icons.DOWNLOAD, tooltip="Descargar", on_click=lambda e, f=fact: open_download_dialog(e.control.page, f, company_info)), padding=0),
                ft.Container(content=ft.IconButton(ft.Icons.SHARE, tooltip="Compartir WhatsApp", on_click=lambda e, f=fact: open_share_dialog(e.control.page, f, company_info)), padding=0),
            ], spacing=0)
            return ft.DataRow(cells=[
                ft.DataCell(ft.Text(f"#{fact.get('id', '')}", weight=ft.FontWeight.BOLD, color=COLORS["text_dark"])),
                ft.DataCell(nombre_cell),
                ft.DataCell(ft.Text(fecha_str, color=COLORS["text_light"])),
                ft.DataCell(ft.Container(
                    content=ft.Text(garantia_text, size=11, color=texto_color, text_align=ft.TextAlign.CENTER),
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                    bgcolor=garantia_color,
                    border_radius=4
                )),
                ft.DataCell(ft.Text(f"${total_val:.2f}", weight=ft.FontWeight.BOLD, color=COLORS["accent_green"])),
                ft.DataCell(actions),
            ])

        _fui.build_row_fn = build_row_for_fact
        # Actualizar filas de la tabla con los datos filtrados actuales
        _fui.data_table.rows = [build_row_for_fact(f) for f in filtered_facturas] if filtered_facturas else []
        _fui.load_more_container.visible = len(filtered_facturas) >= state.get("facturas_limit", 50)

    # Reconstruir controles del invoices_list desde el singleton
    _fui.invoices_list.controls.clear()
    if not filtered_facturas:
        _fui.invoices_list.controls.append(
            ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.RECEIPT_LONG, size=60, color=COLORS["text_light"]),
                    ft.Text("No se encontraron facturas con los filtros aplicados.", size=16, color=COLORS["text_light"], weight=ft.FontWeight.W_500, text_align=ft.TextAlign.CENTER)
                ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=40, alignment=ft.Alignment(0, 0)
            )
        )
    else:
        _fui.invoices_list.controls.append(_fui.data_table)
        _fui.invoices_list.controls.append(_fui.load_more_container)

    invoices_list = _fui.invoices_list

    content = ft.Column([
        ft.Row([
            ft.Column([
                ft.Text("Historial de Facturas Emitidas", size=22, weight=ft.FontWeight.BOLD, color=COLORS["text_dark"]),
                ft.Text("Consulta, filtra, modifica o elimina las últimas facturas del taller", size=13, color=COLORS["text_light"]),
            ]),
            ft.Icon(ft.Icons.RECEIPT_LONG, size=35, color=COLORS["primary"])
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ft.Divider(color=COLORS["border"]),
        filters_bar,
        ft.Divider(color=COLORS["border"], height=10),
        invoices_list
    ], expand=True)
    

    return content

# ============================================================


# ========================================
# ui/views/trabajo_view.py
# ========================================

# ============================================================

"""
Módulo de Trabajos (Flujo de Producción) - Venus MVP
=====================================================
Este módulo visualiza el estado de producción de cada ítem de las facturas.
Permite filtrar por área, tipo y estado, cambiar fases de producción,
y gestionar los envíos a domicilio.

Flujo de estados de ítems:
  Pendiente → Procesando → Procesado

Flujo de estados de envíos:
  Pendiente de Envío → En Ruta → Entregado
"""


# ──────────────────────────────────────────────────────────────
# CONSTANTES DE DISEÑO
# ──────────────────────────────────────────────────────────────

STATUS_CONFIG = {
    "pendiente": {
        "label": "Pendiente",
        "color": "#E67E22",          # Naranja cálido (menos saturado)
        "bg_tint": "#FDF2E9",        # Fondo suave para badges en tema claro
        "icon": ft.Icons.PENDING_ACTIONS,
        "next_status": "procesando",
        "next_label": "Iniciar Fabricación",
        "next_icon": ft.Icons.PLAY_CIRCLE_FILLED,
    },
    "procesando": {
        "label": "En Fabricación",
        "color": "#3498DB",          # Azul medio (más descansado)
        "bg_tint": "#EBF5FB",
        "icon": ft.Icons.PRECISION_MANUFACTURING,
        "next_status": "procesado",
        "next_label": "Marcar como Listo",
        "next_icon": ft.Icons.CHECK_CIRCLE,
    },
    "procesado": {
        "label": "Listo",
        "color": "#27AE60",          # Verde equilibrado
        "bg_tint": "#EAFAF1",
        "icon": ft.Icons.DONE_ALL,
        "next_status": None,
        "next_label": None,
        "next_icon": None,
    },
}

ENVIO_CONFIG = {
    "Pendiente de Envío": {
        "color": "#E67E22",
        "icon": ft.Icons.LOCAL_SHIPPING,
        "next": "En Ruta",
    },
    "En Ruta": {
        "color": "#3498DB",
        "icon": ft.Icons.DELIVERY_DINING,
        "next": "Entregado",
    },
    "Entregado": {
        "color": "#27AE60",
        "icon": ft.Icons.WHERE_TO_VOTE,
        "next": None,
    },
}


def _fmt_date(raw):
    """Formatea una fecha ISO a formato legible."""
    if not raw:
        return "—"
    try:
        dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        try:
            dt = datetime.strptime(raw[:10], "%Y-%m-%d")
            return dt.strftime("%d/%m/%Y")
        except Exception:
            return raw[:16] if len(raw) > 16 else raw


def _time_since(raw):
    """Calcula el tiempo transcurrido desde una fecha."""
    if not raw:
        return ""
    try:
        dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        # obtener_hora() devuelve datetime con tzinfo (UTC-4); lo volvemos naive
        # para comparar con dt (que viene de la BD y ya está en hora local RD)
        delta = obtener_hora().replace(tzinfo=None) - dt
        if delta.days > 0:
            return f"hace {delta.days}d"
        hours = delta.seconds // 3600
        if hours > 0:
            return f"hace {hours}h"
        mins = delta.seconds // 60
        return f"hace {mins}m"
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────
# HELPERS REUTILIZABLES
# ──────────────────────────────────────────────────────────────

def _status_badge(label: str, color: str, status_value: str = None, on_action: callable = None, size: int = 11) -> ft.Container:
    """Crea un badge de estado consistente y legible."""
    return ft.Container(
        content=ft.Text(
            label,
            size=size,
            color="#FFFFFF",
            weight=ft.FontWeight.W_600,
        ),
        bgcolor=color,
        border_radius=4,
        padding=ft.Padding(left=10, right=10, top=4, bottom=4),
        on_click=lambda e: on_action("filter_trabajos", {"status": status_value}) if on_action and status_value else None,
    )


def _detail_chip(icon_name, text: str, color: str = None) -> ft.Row:
    """Crea un chip inline para detalles como color, material, etc."""
    text_color = color or COLORS.get("text_light", "#7F8C8D")
    return ft.Row(
        controls=[
            ft.Icon(icon_name, size=13, color=text_color),
            ft.Text(text, size=12, color=text_color),
        ],
        spacing=3,
        tight=True,
    )


def _view_tab(label: str, icon, index: int, active: bool, count: int, on_action: callable) -> ft.Container:
    """Pestaña customizada para cambiar la sección (Ítems, Facturas, Envíos)."""
    color = COLORS.get("primary", "#1A3644") if active else COLORS.get("text_light", "#7F8C8D")
    weight = ft.FontWeight.BOLD if active else ft.FontWeight.W_500
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Icon(icon, size=16, color=color),
                ft.Text(f"{label} ({count})", size=13, color=color, weight=weight),
            ],
            spacing=6,
        ),
        padding=ft.Padding(left=12, right=12, top=10, bottom=10),
        border=ft.Border(bottom=ft.BorderSide(3, color)) if active else ft.Border(bottom=ft.BorderSide(3, "transparent")),
        on_click=lambda e: on_action("change_trabajos_tab", index),
        ink=True,
    )


def _status_tab(label: str, count: int, color: str, status_value: str, current_status: str, on_action: callable) -> ft.Container:
    """Pestaña customizada para filtrar por estado, funciona como indicador y filtro."""
    active = (status_value == current_status)
    text_color = color if active else COLORS.get("text_light", "#7F8C8D")
    weight = ft.FontWeight.BOLD if active else ft.FontWeight.W_500
    
    badge = ft.Container(
        content=ft.Text(str(count), size=11, color="#FFFFFF", weight=ft.FontWeight.BOLD),
        bgcolor=color if active else COLORS.get("text_light", "#7F8C8D"),
        border_radius=10,
        padding=ft.Padding(left=6, right=6, top=1, bottom=1),
    )
    
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Text(label, size=13, color=text_color, weight=weight),
                badge,
            ],
            spacing=6,
        ),
        padding=ft.Padding(left=12, right=12, top=10, bottom=10),
        border=ft.Border(bottom=ft.BorderSide(3, color)) if active else ft.Border(bottom=ft.BorderSide(3, "transparent")),
        on_click=lambda e: on_action("filter_trabajos", {"status": status_value}),
        ink=True,
    )

# ──────────────────────────────────────────────────────────────
# COMPONENTE: Tarjeta de Ítem de Producción
# ──────────────────────────────────────────────────────────────

# Directorio de uploads de imágenes
IMG_UPLOADS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'img_uploads'))


async def _handle_edit_image_click(e, item_id: int, on_action: callable):
    """Abre un FilePicker para cambiar la imagen de referencia de un ítem de producción."""
    page = e.control.page

    result = await ft.FilePicker().pick_files(
        allow_multiple=False,
        allowed_extensions=["png", "jpg", "jpeg", "webp"],
        dialog_title="Cambiar Imagen de Referencia"
    )
    if result and len(result) > 0:
        file_path = result[0].path
        if not file_path or not os.path.exists(file_path):
            return
        os.makedirs(IMG_UPLOADS_DIR, exist_ok=True)
        from datetime import datetime as _dt
        timestamp = obtener_hora_str("%Y%m%d_%H%M%S_%f")
        ext = os.path.splitext(file_path)[1] or ".jpg"
        new_filename = f"ref_{timestamp}{ext}"
        dest_path = os.path.join(IMG_UPLOADS_DIR, new_filename)
        try:
            shutil.copy2(file_path, dest_path)
            from api_client import insert_image
            image_id = insert_image(new_filename, 1.0)
            # Refrescar el cache de imágenes para que la nueva imagen esté disponible
            from api_client import get_all_images
            from api_client import app_state as _app_state
            _app_state["images_cache"] = get_all_images()
            # Despachar la acción de actualizar la imagen del ítem
            on_action("update_item_image", {"item_id": item_id, "image_id": image_id})
        except Exception as ex:
            import logging
            logging.error(f"Error uploading ref image for item {item_id}: {ex}", exc_info=True)

def _build_item_card(item: dict, on_action: callable) -> ft.Container:
    """
    Tarjeta de un ítem de producción rediseñada.
    Layout: [Thumbnail con botón editar] + [Column: Header, Metadatos, Cliente, Acción]
    La imagen de referencia viene de COALESCE(item.image_id, catalogo.image_id).
    """
    status = item.get("status", "pendiente")
    cfg = STATUS_CONFIG.get(status, STATUS_CONFIG["pendiente"])

    cliente_nombre = item.get("cliente_nombre", "")
    cliente_apellido = item.get("cliente_apellido", "")
    cliente_full = f"{cliente_nombre} {cliente_apellido}".strip() or "Sin cliente"

    area = item.get("area", "—")
    tipo_mueble = item.get("tipo_mueble", "—")

    # Fechas de transición
    fecha_emision = _fmt_date(item.get("factura_fecha"))
    fecha_procesando = _fmt_date(item.get("fecha_procesando"))
    fecha_procesado = _fmt_date(item.get("fecha_procesado"))

    # Indicador de tiempo en fase actual
    if status == "pendiente":
        time_in_phase = _time_since(item.get("factura_fecha"))
    elif status == "procesando":
        time_in_phase = _time_since(item.get("fecha_procesando"))
    else:
        time_in_phase = ""

    # ── Thumbnail de imagen de referencia ──
    ref_image_id = item.get("ref_image_id")
    from api_client import app_state as _app_state
    images_cache = _app_state.get("images_cache", {})

    if ref_image_id and ref_image_id in images_cache:
        cached_img = images_cache[ref_image_id]
        img_src = cached_img.get("image_src")
        if img_src:
            thumbnail_content = ft.Image(src=img_src, fit="cover", border_radius=6, width=220, height=220)
        else:
            thumbnail_content = ft.Container(
                content=ft.Icon(ft.Icons.IMAGE_NOT_SUPPORTED, size=64, color=COLORS.get("text_light", "#7F8C8D")),
                width=220, height=220, bgcolor=COLORS.get("background", "#F0F4F8"),
                border_radius=6, alignment=ft.Alignment(0, 0),
            )
    else:
        thumbnail_content = ft.Container(
            content=ft.Icon(ft.Icons.CHAIR_ALT, size=72, color=COLORS.get("text_light", "#7F8C8D")),
            width=220, height=220, bgcolor=COLORS.get("background", "#F0F4F8"),
            border_radius=6, alignment=ft.Alignment(0, 0),
        )

    # Botón de editar superpuesto en la esquina inferior-derecha de la imagen
    edit_icon = ft.Container(
        content=ft.Icon(ft.Icons.EDIT, size=14, color="#FFFFFF"),
        width=26, height=26, bgcolor="#00000099",
        border_radius=13, alignment=ft.Alignment(0, 0),
    )

    async def _on_edit_click(e):
        await _handle_edit_image_click(e, item["id"], on_action)

    thumbnail_with_edit = ft.Container(
        content=ft.Stack(
            controls=[
                thumbnail_content,
                ft.Container(
                    content=edit_icon,
                    alignment=ft.Alignment(1, 1),  # Esquina inferior-derecha
                ),
            ],
            width=220, height=220,
        ),
        width=220, height=220,
        border=ft.Border.all(1, COLORS.get("border", "#D1D9E6")),
        border_radius=8,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        data=item["id"],  # Guardar item_id en el control para el handler
        on_click=_on_edit_click,
    )

    # ── Fila 1: Nombre del mueble + Badge de estado ──
    header = ft.Row(
        controls=[
            ft.Icon(cfg["icon"], color=cfg["color"], size=18),
            ft.Text(
                item.get("nombre", "Sin nombre"),
                weight=ft.FontWeight.W_600,
                size=15,
                color=COLORS.get("text_dark", "#2C3E50"),
                expand=True,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
            _status_badge(cfg["label"], cfg["color"], status, on_action),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # ── Fila 2: Área, Tipo, Color, Material agrupados en línea ──
    meta_chips = []
    # Tags de categoría (Área y Tipo)
    meta_chips.append(ft.Container(
        content=ft.Text(area, size=11, color=COLORS.get("text_dark", "#2C3E50"), weight=ft.FontWeight.W_500),
        bgcolor=COLORS.get("secondary", "#E0E5EC"),
        border_radius=4,
        padding=ft.Padding(left=8, right=8, top=3, bottom=3),
    ))
    if tipo_mueble and tipo_mueble != "—":
        meta_chips.append(ft.Container(
            content=ft.Text(tipo_mueble, size=11, color=COLORS.get("text_dark", "#2C3E50"), weight=ft.FontWeight.W_500),
            bgcolor=COLORS.get("secondary", "#E0E5EC"),
            border_radius=4,
            padding=ft.Padding(left=8, right=8, top=3, bottom=3),
        ))

    # Separador visual sutil
    meta_chips.append(ft.Container(width=1, height=16, bgcolor=COLORS.get("border", "#D1D9E6")))

    # Color y Material inline
    if item.get("color"):
        meta_chips.append(_detail_chip(ft.Icons.PALETTE_OUTLINED, item["color"]))
    if item.get("material"):
        meta_chips.append(_detail_chip(ft.Icons.LAYERS_OUTLINED, item["material"]))

    meta_row = ft.Row(
        controls=meta_chips,
        spacing=6,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        wrap=True,
    )

    # ── Fila 3: Cliente + Factura + Fechas, todo en una línea ──
    info_parts = [
        ft.Icon(ft.Icons.PERSON_OUTLINED, size=14, color=COLORS.get("text_light", "#7F8C8D")),
        ft.Text(cliente_full, size=12, color=COLORS.get("text_light", "#7F8C8D"), max_lines=1),
        ft.Text("·", size=12, color=COLORS.get("border", "#D1D9E6")),
        ft.Text(f"Fact #{item.get('factura_id', '?')}", size=12, color=COLORS.get("primary", "#1A3644"), weight=ft.FontWeight.W_500),
    ]

    # Fechas compactas: mostrar la más relevante
    if status == "pendiente":
        info_parts.append(ft.Text("·", size=12, color=COLORS.get("border", "#D1D9E6")))
        info_parts.append(ft.Text(f"Emitido {fecha_emision}", size=11, color=COLORS.get("text_light", "#7F8C8D")))
    elif status == "procesando" and fecha_procesando != "—":
        info_parts.append(ft.Text("·", size=12, color=COLORS.get("border", "#D1D9E6")))
        info_parts.append(ft.Text(f"Inicio {fecha_procesando}", size=11, color=COLORS.get("text_light", "#7F8C8D")))
    elif status == "procesado" and fecha_procesado != "—":
        info_parts.append(ft.Text("·", size=12, color=COLORS.get("border", "#D1D9E6")))
        info_parts.append(ft.Text(f"Listo {fecha_procesado}", size=11, color=COLORS.get("text_light", "#7F8C8D")))

    info_row = ft.Row(
        controls=info_parts,
        spacing=4,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        wrap=True,
    )

    # Tiempo transcurrido (sutil, debajo de la info)
    time_text = None
    if time_in_phase:
        time_text = ft.Text(time_in_phase, size=11, color=COLORS.get("text_light", "#7F8C8D"), italic=True)

    # ── Fila 4: Acción (botón avanzar estado) ──
    action_row = None
    if cfg["next_status"]:
        next_cfg = STATUS_CONFIG[cfg["next_status"]]
        action_row = ft.Row(
            controls=[
                time_text if time_text else ft.Container(width=0, height=0),
                ft.OutlinedButton(
                    cfg["next_label"],
                    icon=cfg["next_icon"],
                    icon_color=next_cfg["color"],
                    style=ft.ButtonStyle(
                        color=next_cfg["color"],
                        shape=ft.RoundedRectangleBorder(radius=6),
                        padding=ft.Padding(left=14, right=14, top=6, bottom=6),
                        side=ft.BorderSide(width=1.5, color=next_cfg["color"]),
                    ),
                    height=34,
                    on_click=lambda e, item_id=item["id"], ns=cfg["next_status"]: on_action("change_item_status", {"item_id": item_id, "new_status": ns}),
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    # ── Descripción del ítem (si existe) ──
    desc_text = (item.get("descripcion") or "").strip()
    desc_row = None
    if desc_text:
        desc_row = ft.Row(
            controls=[
                ft.Icon(ft.Icons.NOTES_OUTLINED, size=13, color=COLORS.get("text_light", "#7F8C8D")),
                ft.Text(
                    desc_text,
                    size=12,
                    color=COLORS.get("text_light", "#7F8C8D"),
                    italic=True,
                    max_lines=3,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    expand=True,
                ),
            ],
            spacing=5,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

    # ── Ensamblaje: [Thumbnail] + [Datos del ítem] ──
    right_col_children = [header, meta_row]
    right_col_children.append(info_row)
    if desc_row:
        right_col_children.append(desc_row)
    if action_row:
        right_col_children.append(action_row)
    elif time_text:
        right_col_children.append(time_text)

    right_column = ft.Column(controls=right_col_children, spacing=6, expand=True)

    card_content = ft.Row(
        controls=[thumbnail_with_edit, right_column],
        spacing=14,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )

    return ft.Container(
        content=card_content,
        bgcolor=COLORS.get("surface", "#FFFFFF"),
        border=ft.Border(
            left=ft.BorderSide(width=4, color=cfg["color"]),
            top=ft.BorderSide(width=1, color=COLORS.get("border", "#D1D9E6")),
            right=ft.BorderSide(width=1, color=COLORS.get("border", "#D1D9E6")),
            bottom=ft.BorderSide(width=1, color=COLORS.get("border", "#D1D9E6")),
        ),
        border_radius=8,
        padding=ft.Padding(left=12, right=16, top=12, bottom=12),
        animate=ft.Animation(200, ft.AnimationCurve.EASE_IN_OUT),
    )


CARD_WIDTH = 200  # Ancho fijo de cada tarjeta de ítem en la cuadrícula


def _build_factura_item_card(item: dict, on_action: callable) -> ft.Container:
    """
    Tarjeta visual de ítem para la cuadrícula 'Por Factura'.
    Layout vertical: foto encima, datos debajo. Ancho fijo para que se
    apilen en fila y salten de línea automáticamente (wrap).
    El borde completo refleja el color del estado de fabricación.
    """
    status = item.get("status", "pendiente")
    cfg = STATUS_CONFIG.get(status, STATUS_CONFIG["pendiente"])
    status_color = cfg["color"]

    area = item.get("area", "—")
    tipo_mueble = item.get("tipo_mueble", "—")

    # ── Foto (ocupa todo el ancho de la tarjeta) ──
    ref_image_id = item.get("ref_image_id")
    from api_client import app_state as _app_state
    images_cache = _app_state.get("images_cache", {})

    PHOTO_H = 150  # 4:3 exacto para CARD_WIDTH=200px (200 × 3/4 = 150)
    PHOTO_BG = COLORS.get("background", "#F0F4F8")  # fondo para letterbox

    if ref_image_id and ref_image_id in images_cache:
        cached_img = images_cache[ref_image_id]
        img_src = cached_img.get("image_src")
        if img_src:
            # fit="contain" → imagen completa sin recorte; el bgcolor rellena
            # los espacios vacíos de imágenes con proporciones distintas a 4:3
            photo = ft.Container(
                content=ft.Image(
                    src=img_src, fit="contain",
                    width=CARD_WIDTH, height=PHOTO_H,
                ),
                width=CARD_WIDTH, height=PHOTO_H,
                bgcolor=PHOTO_BG,
                border_radius=ft.BorderRadius(top_left=7, top_right=7, bottom_left=0, bottom_right=0),
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            )
        else:
            photo = ft.Container(
                content=ft.Icon(ft.Icons.IMAGE_NOT_SUPPORTED, size=36, color=COLORS.get("text_light", "#7F8C8D")),
                width=CARD_WIDTH, height=PHOTO_H,
                bgcolor=PHOTO_BG,
                border_radius=ft.BorderRadius(top_left=7, top_right=7, bottom_left=0, bottom_right=0),
                alignment=ft.Alignment(0, 0),
            )
    else:
        photo = ft.Container(
            content=ft.Icon(ft.Icons.CHAIR_ALT, size=48, color=COLORS.get("text_light", "#7F8C8D")),
            width=CARD_WIDTH, height=PHOTO_H,
            bgcolor=PHOTO_BG,
            border_radius=ft.BorderRadius(top_left=7, top_right=7, bottom_left=0, bottom_right=0),
            alignment=ft.Alignment(0, 0),
        )

    # ── Badge de estado superpuesto sobre la foto (esquina superior derecha) ──
    status_badge_overlay = ft.Container(
        content=ft.Container(
            content=ft.Text(cfg["label"], size=10, color="#FFFFFF", weight=ft.FontWeight.W_700),
            bgcolor=status_color,
            border_radius=ft.BorderRadius(top_left=0, top_right=7, bottom_left=6, bottom_right=0),
            padding=ft.Padding(left=8, right=8, top=4, bottom=4),
        ),
        alignment=ft.Alignment(1, -1),  # esquina top-right
    )

    photo_stack = ft.Stack(
        controls=[photo, status_badge_overlay],
        width=CARD_WIDTH, height=PHOTO_H,
    )

    # ── Nombre del ítem ──
    nombre_row = ft.Row(
        controls=[
            ft.Icon(cfg["icon"], color=status_color, size=14),
            ft.Text(
                item.get("nombre", "Sin nombre"),
                weight=ft.FontWeight.W_700,
                size=13,
                color=COLORS.get("text_dark", "#2C3E50"),
                max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS,
                expand=True,
            ),
        ],
        spacing=5,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )

    # ── Chips: Área y Tipo ──
    chips = []
    if area and area != "—":
        chips.append(ft.Container(
            content=ft.Text(area, size=9, color=COLORS.get("text_dark", "#2C3E50"), weight=ft.FontWeight.W_500),
            bgcolor=COLORS.get("secondary", "#E0E5EC"),
            border_radius=4,
            padding=ft.Padding(left=6, right=6, top=2, bottom=2),
        ))
    if tipo_mueble and tipo_mueble != "—":
        chips.append(ft.Container(
            content=ft.Text(tipo_mueble, size=9, color=COLORS.get("text_dark", "#2C3E50"), weight=ft.FontWeight.W_500),
            bgcolor=COLORS.get("secondary", "#E0E5EC"),
            border_radius=4,
            padding=ft.Padding(left=6, right=6, top=2, bottom=2),
        ))
    chips_row = ft.Row(controls=chips, spacing=4, wrap=True) if chips else ft.Container(height=0)

    # ── Color y Material ──
    mat_parts = []
    if item.get("color"):
        mat_parts.append(ft.Row(controls=[
            ft.Icon(ft.Icons.PALETTE_OUTLINED, size=12, color=COLORS.get("text_light", "#7F8C8D")),
            ft.Text(item["color"], size=11, color=COLORS.get("text_light", "#7F8C8D"), max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=3, tight=True))
    if item.get("material"):
        mat_parts.append(ft.Row(controls=[
            ft.Icon(ft.Icons.LAYERS_OUTLINED, size=12, color=COLORS.get("text_light", "#7F8C8D")),
            ft.Text(item["material"], size=11, color=COLORS.get("text_light", "#7F8C8D"), max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=3, tight=True))
    mat_col = ft.Column(controls=mat_parts, spacing=3) if mat_parts else ft.Container(height=0)

    # ── Botón de avance de estado ──
    action_btn = None
    if cfg["next_status"]:
        next_cfg = STATUS_CONFIG[cfg["next_status"]]
        action_btn = ft.OutlinedButton(
            cfg["next_label"],
            icon=cfg["next_icon"],
            icon_color=next_cfg["color"],
            style=ft.ButtonStyle(
                color=next_cfg["color"],
                shape=ft.RoundedRectangleBorder(radius=6),
                padding=ft.Padding(left=8, right=8, top=4, bottom=4),
                side=ft.BorderSide(width=1.5, color=next_cfg["color"]),
            ),
            height=30,
            on_click=lambda e, iid=item["id"], ns=cfg["next_status"]: on_action("change_item_status", {"item_id": iid, "new_status": ns}),
        )

    info_col = ft.Column(
        controls=[
            nombre_row,
            chips_row,
            mat_col,
            ft.Row([action_btn], alignment=ft.MainAxisAlignment.END) if action_btn else ft.Container(height=0),
        ],
        spacing=6,
        width=CARD_WIDTH,
    )

    card_body = ft.Column(
        controls=[photo_stack, ft.Container(content=info_col, padding=ft.Padding(left=10, right=10, top=8, bottom=10))],
        spacing=0,
        width=CARD_WIDTH,
    )

    # Marco: color del estado en borde superior grueso + borde fino resto
    return ft.Container(
        content=card_body,
        bgcolor=cfg.get("bg_tint", "#FFFFFF"),
        border=ft.Border(
            top=ft.BorderSide(width=3, color=status_color),
            left=ft.BorderSide(width=1, color=status_color),
            right=ft.BorderSide(width=1, color=status_color),
            bottom=ft.BorderSide(width=1, color=status_color),
        ),
        border_radius=10,
        width=CARD_WIDTH,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        animate=ft.Animation(200, ft.AnimationCurve.EASE_IN_OUT),
        shadow=ft.BoxShadow(
            spread_radius=0,
            blur_radius=6,
            color="#1A000000",
            offset=ft.Offset(0, 2),
        ),
    )


# ──────────────────────────────────────────────────────────────
# COMPONENTE: Fila de Factura con Progreso
# ──────────────────────────────────────────────────────────────

def _build_factura_progress_card(factura: dict, items: list, on_action: callable, expanded: bool = False) -> ft.Container:
    """Tarjeta de factura con barra de progreso y cuadrícula de ítems expandible."""
    total_items = factura.get("total_items", len(items))
    items_listos = factura.get("items_listos", 0)
    items_procesando = factura.get("items_procesando", 0)
    items_pendientes = factura.get("items_pendientes", 0)

    if total_items > 0:
        progress = items_listos / total_items
    else:
        progress = 0

    cliente = f"{factura.get('cliente_nombre', '')} {factura.get('cliente_apellido', '')}".strip() or "Sin cliente"

    # ── Barra de progreso segmentada ──
    segments = []
    if total_items > 0:
        if items_listos > 0:
            segments.append(ft.Container(
                bgcolor="#27AE60", expand=items_listos,
                height=10,
                border_radius=ft.BorderRadius(
                    top_left=5, bottom_left=5,
                    top_right=0 if (items_procesando > 0 or items_pendientes > 0) else 5,
                    bottom_right=0 if (items_procesando > 0 or items_pendientes > 0) else 5,
                ),
            ))
        if items_procesando > 0:
            segments.append(ft.Container(
                bgcolor="#3498DB", expand=items_procesando, height=10,
                border_radius=ft.BorderRadius(
                    top_left=0 if items_listos > 0 else 5,
                    bottom_left=0 if items_listos > 0 else 5,
                    top_right=0 if items_pendientes > 0 else 5,
                    bottom_right=0 if items_pendientes > 0 else 5,
                ),
            ))
        if items_pendientes > 0:
            segments.append(ft.Container(
                bgcolor="#E67E22", expand=items_pendientes,
                height=10,
                border_radius=ft.BorderRadius(
                    top_left=0 if (items_listos > 0 or items_procesando > 0) else 5,
                    bottom_left=0 if (items_listos > 0 or items_procesando > 0) else 5,
                    top_right=5, bottom_right=5,
                ),
            ))

    progress_bar = ft.Row(
        controls=segments, spacing=1, expand=True,
    ) if segments else ft.Container(
        height=10, bgcolor=COLORS.get("border", "#D1D9E6"), border_radius=5, expand=True,
    )

    # ── Header ──
    header = ft.Row(
        controls=[
            ft.Icon(ft.Icons.RECEIPT, size=18, color=COLORS.get("primary", "#1A3644")),
            ft.Text(f"Factura #{factura.get('id', '?')}", weight=ft.FontWeight.W_600, size=15, color=COLORS.get("text_dark", "#2C3E50")),
            ft.Text(f"·  {cliente}", size=13, color=COLORS.get("text_light", "#7F8C8D"), expand=True, max_lines=1),
            ft.Text(_fmt_date(factura.get('fecha', factura.get('factura_fecha', ''))), size=12, color=COLORS.get("text_light", "#7F8C8D")),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=6,
    )

    # ── Progreso + Leyenda en una sola fila ──
    summary = ft.Row(
        controls=[
            progress_bar,
            ft.Text(
                f"{items_listos}/{total_items}",
                size=13, weight=ft.FontWeight.W_600,
                color="#27AE60" if items_listos == total_items else COLORS.get("text_light", "#7F8C8D"),
            ),
        ],
        spacing=10,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    legend = ft.Row(
        controls=[
            ft.Row(controls=[
                ft.Container(width=10, height=10, bgcolor="#E67E22", border_radius=3),
                ft.Text(f"{items_pendientes} Pend.", size=11, color=COLORS.get("text_light", "#7F8C8D")),
            ], spacing=4),
            ft.Row(controls=[
                ft.Container(width=10, height=10, bgcolor="#3498DB", border_radius=3),
                ft.Text(f"{items_procesando} Fabric.", size=11, color=COLORS.get("text_light", "#7F8C8D")),
            ], spacing=4),
            ft.Row(controls=[
                ft.Container(width=10, height=10, bgcolor="#27AE60", border_radius=3),
                ft.Text(f"{items_listos} Listos", size=11, color=COLORS.get("text_light", "#7F8C8D")),
            ], spacing=4),
        ],
        spacing=14,
    )

    # ── Items expandibles en cuadrícula (wrap) ──
    items_list = ft.Row(spacing=10, run_spacing=10, wrap=True, visible=expanded)
    if items:
        for it in items:
            items_list.controls.append(_build_factura_item_card(it, on_action))

    # ── Expandir/Contraer ──
    def toggle_expand(e):
        items_list.visible = not items_list.visible
        expand_btn.icon = ft.Icons.EXPAND_LESS if items_list.visible else ft.Icons.EXPAND_MORE
        expand_btn.update()
        items_list.update()

    expand_btn = ft.IconButton(
        icon=ft.Icons.EXPAND_LESS if expanded else ft.Icons.EXPAND_MORE,
        icon_size=20,
        icon_color=COLORS.get("text_light", "#7F8C8D"),
        on_click=toggle_expand,
        tooltip="Ver ítems",
    )

    # ── Botón de Despacho ──
    dispatch_btn = None
    if items_listos == total_items and total_items > 0:
        btn_text = "Enviar a Logística" if factura.get("entrega_domicilio") else "Entregar y Completar"
        dispatch_btn = ft.OutlinedButton(
            btn_text,
            icon=ft.Icons.LOCAL_SHIPPING if factura.get("entrega_domicilio") else ft.Icons.CHECK_CIRCLE,
            style=ft.ButtonStyle(
                color="#27AE60",
                shape=ft.RoundedRectangleBorder(radius=6),
                side=ft.BorderSide(width=1.5, color="#27AE60"),
                padding=ft.Padding(left=14, right=14, top=6, bottom=6),
            ),
            on_click=lambda e: on_action("dispatch_factura", {
                "factura_id": factura.get("id"),
                "entrega": factura.get("entrega_domicilio"),
                "direccion": factura.get("direccion_entrega")
            })
        )

    card_content = ft.Column(
        controls=[
            ft.Row(controls=[
                ft.Column(controls=[header, summary, legend], expand=True, spacing=6),
                expand_btn,
            ], vertical_alignment=ft.CrossAxisAlignment.START),
            items_list,
            ft.Row([dispatch_btn], alignment=ft.MainAxisAlignment.END) if dispatch_btn else ft.Container(height=0, width=0),
        ],
        spacing=6,
    )

    # Color del borde izquierdo según progreso
    left_color = "#27AE60" if progress >= 1.0 else ("#3498DB" if progress > 0 else "#E67E22")

    return ft.Container(
        content=card_content,
        bgcolor=COLORS.get("surface", "#FFFFFF"),
        border=ft.Border(
            top=ft.BorderSide(width=1, color=COLORS.get("border", "#D1D9E6")),
            right=ft.BorderSide(width=1, color=COLORS.get("border", "#D1D9E6")),
            bottom=ft.BorderSide(width=1, color=COLORS.get("border", "#D1D9E6")),
            left=ft.BorderSide(width=3, color=left_color),
        ),
        border_radius=8,
        padding=ft.Padding(left=16, right=12, top=14, bottom=14),
    )


# ──────────────────────────────────────────────────────────────
# COMPONENTE: Fila de Envío
# ──────────────────────────────────────────────────────────────

def _build_envio_row(envio: dict, on_action: callable) -> ft.Container:
    """Tarjeta de envío con pipeline de estados clickeable."""
    estado = envio.get("estado", "Pendiente de Envío")
    cfg = ENVIO_CONFIG.get(estado, ENVIO_CONFIG["Pendiente de Envío"])
    cliente = f"{envio.get('cliente_nombre', '')} {envio.get('cliente_apellido', '')}".strip() or "—"

    envio_keys = list(ENVIO_CONFIG.keys())
    current_idx = envio_keys.index(estado) if estado in envio_keys else 0

    # Pipeline de chips de estado
    estado_chips = []
    for idx, (est_key, est_cfg) in enumerate(ENVIO_CONFIG.items()):
        is_current = est_key == estado
        is_past = idx < current_idx
        is_future = idx > current_idx

        # Determinar estilos
        if is_current:
            chip_bg = est_cfg["color"]
            chip_text_color = "#FFFFFF"
            chip_weight = ft.FontWeight.W_600
        elif is_past:
            chip_bg = "transparent"
            chip_text_color = est_cfg["color"]
            chip_weight = ft.FontWeight.W_500
        else:
            chip_bg = "transparent"
            chip_text_color = COLORS.get("text_light", "#7F8C8D")
            chip_weight = ft.FontWeight.NORMAL

        chip_border_color = est_cfg["color"] if (is_current or is_past) else COLORS.get("border", "#D1D9E6")

        chip = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(est_cfg["icon"], size=14, color=chip_text_color),
                    ft.Text(est_key, size=11, color=chip_text_color, weight=chip_weight),
                ],
                spacing=4,
                tight=True,
            ),
            bgcolor=chip_bg,
            border=ft.Border(
                top=ft.BorderSide(1, chip_border_color),
                bottom=ft.BorderSide(1, chip_border_color),
                left=ft.BorderSide(1, chip_border_color),
                right=ft.BorderSide(1, chip_border_color),
            ),
            border_radius=16,
            padding=ft.Padding(left=10, right=10, top=5, bottom=5),
            on_click=(lambda e, eid=envio["id"], target=est_key: on_action("update_envio_status", {"envio_id": eid, "new_status": target})) if is_future else None,
            tooltip=f"Marcar como {est_key}" if is_future else None,
        )
        estado_chips.append(chip)

        # Conector entre chips
        if est_key != "Entregado":
            connector_color = est_cfg["color"] if (is_past or is_current) else COLORS.get("border", "#D1D9E6")
            estado_chips.append(ft.Container(
                width=20, height=2, bgcolor=connector_color,
            ))

    return ft.Container(
        content=ft.Column(
            controls=[
                # Línea 1: Factura + Cliente + Fecha
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.LOCAL_SHIPPING, size=18, color=cfg["color"]),
                        ft.Text(f"Factura #{envio.get('factura_id', '?')}", weight=ft.FontWeight.W_600, size=14, color=COLORS.get("text_dark", "#2C3E50")),
                        ft.Text(f"·  {cliente}", size=13, color=COLORS.get("text_light", "#7F8C8D"), expand=True),
                        ft.Text(_fmt_date(envio.get("factura_fecha", "")), size=12, color=COLORS.get("text_light", "#7F8C8D")),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=6,
                ),
                # Línea 2: Dirección
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.LOCATION_ON_OUTLINED, size=14, color=COLORS.get("text_light", "#7F8C8D")),
                        ft.Text(envio.get("direccion_entrega", "Sin dirección"), size=12, color=COLORS.get("text_light", "#7F8C8D"), expand=True, max_lines=1),
                    ],
                    spacing=4,
                ),
                # Línea 3: Pipeline de estados
                ft.Row(
                    controls=estado_chips,
                    alignment=ft.MainAxisAlignment.CENTER,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=0,
                ),
            ],
            spacing=8,
        ),
        bgcolor=COLORS.get("surface", "#FFFFFF"),
        border=ft.Border(
            top=ft.BorderSide(1, COLORS.get("border", "#D1D9E6")),
            bottom=ft.BorderSide(1, COLORS.get("border", "#D1D9E6")),
            left=ft.BorderSide(3, cfg["color"]),
            right=ft.BorderSide(1, COLORS.get("border", "#D1D9E6")),
        ),
        border_radius=8,
        padding=ft.Padding(left=16, right=16, top=14, bottom=14),
    )


# ──────────────────────────────────────────────────────────────
# VISTA PRINCIPAL: create_trabajo_view
# ──────────────────────────────────────────────────────────────

def create_trabajo_view(state: dict, on_action: callable) -> ft.Container:
    """
    Construye la vista principal del módulo de Trabajos.
    Incluye la cabecera unificada con Pestañas de Vista, Filtros y Pestañas de Estado.
    """
    areas = ["Todos"] + state.get("areas", [])
    tipos = ["Todos"] + state.get("tipos", [])
    
    current_area = state.get("trabajos_filter_area", "Todos")
    current_tipo = state.get("trabajos_filter_tipo", "Todos")
    current_status = state.get("trabajos_filter_status", "Todos")
    current_tab = state.get("trabajos_active_tab", 0)

    trabajos = state.get("trabajos_cache", [])
    envios = state.get("envios_cache", [])
    facturas_work = state.get("facturas_work_cache", [])

    # ── Contadores ──
    n_pendientes = len([t for t in trabajos if t.get("status") == "pendiente"])
    n_procesando = len([t for t in trabajos if t.get("status") == "procesando"])
    n_procesados = len([t for t in trabajos if t.get("status") == "procesado"])
    n_total = len(trabajos)

    # ── Cabecera Unificada (Unified Header Row) ──
    # 1. Pestañas de Sección (Views)
    views_tabs = ft.Row(
        controls=[
            _view_tab("Por Ítems", ft.Icons.VIEW_LIST, 0, current_tab == 0, n_total, on_action),
            _view_tab("Por Factura", ft.Icons.RECEIPT_LONG, 1, current_tab == 1, len(facturas_work), on_action),
            _view_tab("Envíos", ft.Icons.LOCAL_SHIPPING, 2, current_tab == 2, len(envios), on_action),
        ],
        spacing=0,
    )

    # 2. Filtros (Dropdowns)
    filters_dropdowns = ft.Row(
        controls=[
            ft.Row(
                controls=[
                    ft.Text("Área:", size=12, weight=ft.FontWeight.W_500, color=COLORS.get("text_light", "#7F8C8D")),
                    ft.Dropdown(
                        value=current_area,
                        options=[ft.dropdown.Option(a) for a in areas],
                        width=140, height=35, text_size=12,
                        content_padding=ft.Padding(10, 0, 10, 0),
                        border_color=COLORS.get("border", "#D1D9E6"),
                        bgcolor=COLORS.get("surface", "#FFFFFF"),
                        border_radius=6,
                        color=COLORS.get("text_dark", "#2C3E50"),
                        on_select=lambda e: on_action("filter_trabajos", {"area": e.control.value}),
                        tooltip="Área",
                    )
                ],
                spacing=6,
            ),
            ft.Row(
                controls=[
                    ft.Text("Tipo:", size=12, weight=ft.FontWeight.W_500, color=COLORS.get("text_light", "#7F8C8D")),
                    ft.Dropdown(
                        value=current_tipo,
                        options=[ft.dropdown.Option(t) for t in tipos],
                        width=140, height=35, text_size=12,
                        content_padding=ft.Padding(10, 0, 10, 0),
                        border_color=COLORS.get("border", "#D1D9E6"),
                        bgcolor=COLORS.get("surface", "#FFFFFF"),
                        border_radius=6,
                        color=COLORS.get("text_dark", "#2C3E50"),
                        on_select=lambda e: on_action("filter_trabajos", {"tipo": e.control.value}),
                        tooltip="Tipo",
                    )
                ],
                spacing=6,
            ),
        ],
        spacing=12,
    )

    # 3. Pestañas de Estado (Status Indicators)
    status_tabs = ft.Row(
        controls=[
            _status_tab("Todos", n_total, "#1A3644", "Todos", current_status, on_action),
            _status_tab("Pendientes", n_pendientes, "#E67E22", "pendiente", current_status, on_action),
            _status_tab("Fabricación", n_procesando, "#3498DB", "procesando", current_status, on_action),
            _status_tab("Listos", n_procesados, "#27AE60", "procesado", current_status, on_action),
        ],
        spacing=0,
    )

    # Ensamblar Header (Scrollable horizontalmente si falta espacio)
    unified_header = ft.Row(
        controls=[
            views_tabs,
            ft.Container(width=1, height=20, bgcolor=COLORS.get("border", "#D1D9E6"), margin=ft.Margin(left=10, right=10, top=0, bottom=0)),
            filters_dropdowns,
            ft.Container(width=1, height=20, bgcolor=COLORS.get("border", "#D1D9E6"), margin=ft.Margin(left=10, right=10, top=0, bottom=0)),
            status_tabs,
        ],
        scroll=ft.ScrollMode.ADAPTIVE,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # ── Filtrado Local por Estado (Solo aplica al tab de Ítems) ──
    if current_status != "Todos":
        trabajos_filtrados = [t for t in trabajos if t.get("status") == current_status]
    else:
        trabajos_filtrados = trabajos

    # ── TAB 1: Vista por Ítems ──
    if trabajos_filtrados:
        items_list = ft.ListView(
            controls=[_build_item_card(item, on_action) for item in trabajos_filtrados],
            spacing=10, padding=ft.Padding(0, 6, 0, 6), expand=True,
        )
    else:
        items_list = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(ft.Icons.ENGINEERING, size=48, color=COLORS.get("text_light", "#7F8C8D")),
                    ft.Text("No hay trabajos en esta sección", size=16, color=COLORS.get("text_light", "#7F8C8D"), weight=ft.FontWeight.W_500),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8,
            ),
            alignment=ft.Alignment.CENTER, expand=True, padding=40,
        )

    # ── TAB 2: Vista por Factura ──
    if facturas_work:
        factura_cards = []
        for fw in facturas_work:
            factura_items = [t for t in trabajos if t.get("factura_id") == fw.get("id")]
            factura_cards.append(_build_factura_progress_card(fw, factura_items, on_action))
        facturas_list = ft.ListView(
            controls=factura_cards, spacing=10, padding=ft.Padding(0, 6, 0, 6), expand=True,
        )
    else:
        facturas_list = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(ft.Icons.RECEIPT_LONG, size=48, color=COLORS.get("text_light", "#7F8C8D")),
                    ft.Text("No hay facturas con trabajos en curso", size=16, color=COLORS.get("text_light", "#7F8C8D")),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8,
            ),
            alignment=ft.Alignment.CENTER, expand=True, padding=40,
        )

    # ── TAB 3: Panel de Envíos ──
    if envios:
        envios_list = ft.ListView(
            controls=[_build_envio_row(env, on_action) for env in envios],
            spacing=10, padding=ft.Padding(0, 6, 0, 6), expand=True,
        )
    else:
        envios_list = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(ft.Icons.LOCAL_SHIPPING, size=48, color=COLORS.get("text_light", "#7F8C8D")),
                    ft.Text("No hay envíos pendientes", size=16, color=COLORS.get("text_light", "#7F8C8D")),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8,
            ),
            alignment=ft.Alignment.CENTER, expand=True, padding=40,
        )

    # Seleccionar vista activa
    if current_tab == 0:
        active_view = items_list
    elif current_tab == 1:
        active_view = facturas_list
    else:
        active_view = envios_list

    # ── Ensamblaje final ──
    return ft.Container(
        content=ft.Column(
            controls=[
                # Título
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.ENGINEERING, size=24, color=COLORS.get("primary", "#1A3644")),
                        ft.Text("Módulo de Trabajos", size=20, weight=ft.FontWeight.BOLD, color=COLORS.get("text_dark", "#2C3E50")),
                    ],
                    spacing=8,
                ),
                # Cabecera Unificada (Tabs + Filtros + Status)
                unified_header,
                ft.Divider(height=1, color=COLORS.get("border", "#D1D9E6")),
                # Vista Principal (Lista)
                active_view,
            ],
            spacing=10,
            expand=True,
        ),
        expand=True,
        padding=ft.Padding(left=16, right=16, top=10, bottom=10),
    )

# ============================================================


# ========================================
# ui/panels.py
# ========================================

# ============================================================



class _FacturasUI:
    """
    Singleton que mantiene referencias ESTABLES a los controles de la vista de Facturas.
    
    El problema con Flet + update_control_tree: cada render crea nuevos objetos Python,
    pero el arbol visual preserva los PRIMEROS objetos creados. Los closures del botton
    capturaban los objetos NUEVOS (no en el arbol), causando que page.update() no hiciera nada.
    
    Solucion: singleton que SIEMPRE apunta a los controles vivos en el arbol.
    """
    data_table: ft.DataTable = None
    load_more_container: ft.Container = None
    invoices_list: ft.Column = None
    build_row_fn = None  # funcion para construir una DataRow desde un dict de factura
    state_ref: dict = None  # referencia al app_state

_fui = _FacturasUI()


# Imports refactored

def create_top_bar(state: dict, on_action: callable) -> ft.Row:
    """
    Crea la barra superior con los módulos principales y el menú de utilidades.
    """
    active_view = state.get("central_view", "catalogo")
    
    def create_main_btn(icon: str, text: str, view_id: str):
        is_active = active_view == view_id
        
        bg_color = COLORS["primary"] if is_active else COLORS["secondary"]
        text_color = COLORS["surface"] if is_active else COLORS["primary"]
        
        return ft.Container(
            content=ft.Column([
                ft.Icon(icon, size=35, color=text_color),
                ft.Text(text, size=14, weight=ft.FontWeight.BOLD, color=text_color, text_align=ft.TextAlign.CENTER)
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=bg_color,
            padding=10,
            border_radius=10,
            expand=True,
            on_click=lambda e: on_action("change_view", view_id)
        )

    return ft.Row([
        create_main_btn(ft.Icons.RECEIPT_LONG, "Generar Factura", "catalogo"),
        create_main_btn(ft.Icons.HARDWARE, "Trabajos", "entregas"),
        create_main_btn(ft.Icons.INVENTORY_2, "Productos en Stock", "stock"),
        create_main_btn(ft.Icons.RECEIPT, "Facturas", "facturas")
    ], spacing=15, height=100)


def create_stock_card(st: dict, is_selected: bool, on_action: callable = None, read_only=False):
    border_color = COLORS["primary"] if is_selected else COLORS["border"]
    border_width = 2 if is_selected else 1
    bg = COLORS["secondary"] if is_selected else COLORS["surface"]
    
    def on_click(e):
        if on_action and not read_only:
            on_action("add_to_cart_stock", st)
            
    from api_client import app_state
    aspect_ratio = 1.0
    img_id = st.get("image_id")
    if img_id and img_id in app_state.get("images_cache", {}):
        aspect_ratio = app_state["images_cache"][img_id].get("aspect_ratio", 1.0)
        
    is_portrait = aspect_ratio < 1.0
    
    if is_portrait:
        content = ft.Row([
            build_image(st, width=90, fit="cover", border_radius=5),
            ft.Column([
                ft.Text(st["nombre"], weight=ft.FontWeight.BOLD, size=14, color=COLORS["text_dark"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"{st.get('area', '')} - {st.get('tipo', '')}", size=10, color=COLORS["primary"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS) if st.get('tipo') else ft.Container(),
                ft.Text(f"Color: {st['color']} | {st['material']}", size=11, color=COLORS["text_light"]),
                ft.Text(st.get("descripcion", ""), size=10, color=COLORS["text_light"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS) if st.get("descripcion") else ft.Container(),
                ft.Row([
                    ft.Text(f"${st['precio']}", weight=ft.FontWeight.BOLD, size=15, color=COLORS["text_dark"]),
                    ft.Container(
                        content=ft.Text(f"Disp: {st['cantidad']}", size=11, color=COLORS["surface"], weight=ft.FontWeight.BOLD),
                        bgcolor=COLORS["primary"] if st["cantidad"] > 0 else COLORS["accent_red"],
                        padding=ft.Padding.symmetric(horizontal=8, vertical=4), border_radius=5
                    )
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            ], expand=True, alignment=ft.MainAxisAlignment.CENTER)
        ], expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
    else:
        content = ft.Column([
            build_image(st, height=130, fit="cover", border_radius=5),
            ft.Text(st["nombre"], weight=ft.FontWeight.BOLD, size=14, color=COLORS["text_dark"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(f"{st.get('area', '')} - {st.get('tipo', '')}", size=10, color=COLORS["primary"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS) if st.get('tipo') else ft.Container(),
            ft.Text(f"Color: {st['color']} | {st['material']}", size=11, color=COLORS["text_light"]),
            ft.Text(st.get("descripcion", ""), size=10, color=COLORS["text_light"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS) if st.get("descripcion") else ft.Container(),
            ft.Row([
                ft.Text(f"${st['precio']}", weight=ft.FontWeight.BOLD, size=15, color=COLORS["text_dark"]),
                ft.Container(
                    content=ft.Text(f"Disp: {st['cantidad']}", size=11, color=COLORS["surface"], weight=ft.FontWeight.BOLD),
                    bgcolor=COLORS["primary"] if st["cantidad"] > 0 else COLORS["accent_red"],
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4), border_radius=5
                )
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        ])

    return ft.Container(
        padding=10, bgcolor=bg, border=ft.Border.all(border_width, border_color), border_radius=10, ink=True, on_click=on_click,
        content=content
    )


def create_central_zone(state: dict, on_action: callable) -> ft.Container:
    view = state.get("central_view", "catalogo")
    content = None
    
    if view == "catalogo":
        content = create_catalog_view(state, on_action)
    elif view == "stock":
        content = create_stock_view(state, on_action)
    elif view == "facturas":
        content = create_invoice_view(state, on_action, _fui)
    elif view == "entregas":
        content = create_trabajo_view(state, on_action)
    elif view == "busqueda":
        content = ft.Container(
            content=ft.Text("Búsqueda Profunda en Base de Datos\\n(Funcionalidad en desarrollo)", size=24, color=COLORS["text_light"], text_align=ft.TextAlign.CENTER),
            alignment=ft.Alignment(0, 0), expand=True
        )
    elif view == "configuracion":
        content = create_config_view(state, on_action)
        
    if not content:
        content = ft.Container(ft.Text("Vista no encontrada"), expand=True)


    
    fab = ft.Container(
        content=ft.FloatingActionButton(
            icon=ft.Icons.SETTINGS,
            bgcolor=COLORS["primary"],
            shape=ft.CircleBorder(),
            on_click=lambda e: on_action("change_view", "configuracion")
        ),
        right=15,
        bottom=15
    )

    return ft.Container(
        content=ft.Stack(
            controls=[
                ft.Container(content=content, expand=True),
                fab
            ],
            expand=True
        ),
        expand=True,
        padding=ft.Padding.only(top=15)
    )

def create_right_panel(state: dict, on_action: callable) -> ft.Container:
    view = state.get("central_view", "catalogo")
    selected_products = state.get("selected_products", [])
    
    if len(selected_products) > 0:
        title = ft.Text("Resumen de Factura", size=18, weight=ft.FontWeight.BOLD)
        items_list = ft.ListView(expand=True, spacing=10)
        total_items_price = 0
        
        for p in selected_products:
            total_items_price += p["subtotal"]
            
            img_src = ""
            color_tela = ""
            
            item_con_imagen = p
            if p["tipo"] == "stock":
                stock_entry = next((s for s in state.get("stock_cache", []) if s["id"] == p["stock_id"]), None)
                if stock_entry:
                    color_tela = f"Color: {stock_entry.get('color', 'N/A')} | Material: {stock_entry.get('material', 'N/A')}"
                    item_con_imagen = stock_entry
            else:
                cat_entry = next((c for c in state.get("catalog_cache", []) if c["id"] == p["catalogo_id"]), None)
                if cat_entry:
                    item_con_imagen = cat_entry
                color_tela = f"Color: {p.get('color', 'A medida')} | Tela: {p.get('material', 'A medida')}"

            items_list.controls.append(
                ft.Container(
                    border_radius=8,
                    border=ft.Border.all(1, ft.Colors.GREY_300),
                    padding=10,
                    bgcolor=COLORS["surface"],
                    content=ft.Column([
                        ft.Row([
                            build_image(item_con_imagen, width=40, height=40, border_radius=4, fit="cover"),
                            ft.Column([
                                ft.Text(p['nombre'], weight=ft.FontWeight.BOLD, size=13, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(color_tela, size=11, color=ft.Colors.GREY_600)
                            ], expand=True, spacing=2),
                            ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_400, icon_size=18, on_click=lambda e, cid=p["cart_id"]: on_action("remove_from_cart", cid))
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Row([
                            ft.Row([
                                ft.IconButton(icon=ft.Icons.REMOVE, icon_size=16, on_click=lambda e, cid=p["cart_id"]: on_action("update_cart_quantity", {"cart_id": cid, "delta": -1})),
                                ft.Text(str(p["cantidad"]), weight=ft.FontWeight.BOLD),
                                ft.IconButton(icon=ft.Icons.ADD, icon_size=16, on_click=lambda e, cid=p["cart_id"]: on_action("update_cart_quantity", {"cart_id": cid, "delta": 1}))
                            ], spacing=0),
                            ft.Text(f"${p['subtotal']:.2f}", weight=ft.FontWeight.BOLD)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                    ])
                )
            )
            
        company_info = state.get("company", {})
        habilitar_itbis = company_info.get("habilitar_itbis", False)
        porcentaje_itbis = float(company_info.get("porcentaje_itbis", 0.18))
        itbis_incluido = company_info.get("itbis_incluido", False)
        
        if habilitar_itbis:
            if itbis_incluido:
                total_pagar = total_items_price
                subtotal = total_pagar / (1 + porcentaje_itbis)
                itbis_monto = total_pagar - subtotal
            else:
                subtotal = total_items_price
                itbis_monto = subtotal * porcentaje_itbis
                total_pagar = subtotal + itbis_monto
        else:
            subtotal = total_items_price
            itbis_monto = 0
            total_pagar = total_items_price
            
        totales_col = ft.Column([
            ft.Divider(color=COLORS["border"]),
            ft.Row([ft.Text("Subtotal"), ft.Text(f"${subtotal:.2f}")], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        ], spacing=5)
        
        if habilitar_itbis:
            totales_col.controls.append(
                ft.Row([ft.Text(f"ITBIS ({int(porcentaje_itbis*100)}%)"), ft.Text(f"${itbis_monto:.2f}")], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            )
            
        totales_col.controls.extend([
            ft.Divider(color=COLORS["border"]),
            ft.Row([ft.Text("Total a Pagar", size=16, weight=ft.FontWeight.BOLD), ft.Text(f"${total_pagar:.2f}", size=16, weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        ])
            
        checkbox_entrega = ft.Checkbox(
            label="¿Entrega a domicilio?",
            value=state.get("entrega_activa", True),
            on_change=lambda e: on_action("update_entrega_info", {"activa": e.control.value}),
            fill_color=COLORS["primary"]
        )
        
        direccion_input = ft.TextField(
            label="Dirección de Entrega",
            value=state.get("direccion_entrega", ""),
            visible=state.get("entrega_activa", True),
            dense=True,
            text_size=12,
            on_change=lambda e: None
        )
        
        garantia_dropdown = ft.Dropdown(
            label="Tiempo de Garantía",
            value="Sin Garantía",
            options=[
                ft.dropdown.Option("Sin Garantía"),
                ft.dropdown.Option("1 Mes"),
                ft.dropdown.Option("3 Meses"),
                ft.dropdown.Option("6 Meses"),
                ft.dropdown.Option("1 Año"),
                ft.dropdown.Option("2 Años")
            ],
            dense=True,
            text_size=13
        )
        
        summary = ft.Column([
            totales_col,
            ft.Container(
                content=ft.Column([
                    garantia_dropdown,
                    ft.Divider(color=COLORS["border"], height=1),
                    checkbox_entrega,
                    direccion_input
                ]),
                padding=10,
                bgcolor=COLORS["background"],
                border_radius=8
            ),
            
            ft.ElevatedButton(
                "Finalizar y Cobrar",
                bgcolor="#0A2A4A",
                color=ft.Colors.WHITE,
                width=float('inf'),
                height=45,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
                on_click=lambda e: on_action("open_checkout_dialog", {"direccion_entrega": direccion_input.value, "entrega_activa": checkbox_entrega.value, "garantia_hasta": garantia_dropdown.value, "total_override": total_pagar})
            )
        ])
        
        dynamic_content = ft.Column([title, items_list, summary], expand=True)
        return ft.Container(
            content=dynamic_content,
            width=320, padding=15, bgcolor=COLORS["surface"], border_radius=15, border=ft.Border.all(1, COLORS["border"])
        )
    else:
        return ft.Container(visible=False, width=0, height=0)


# ========================================
# main.py
# ========================================

def copy_visual_props(existing, new):
    props = ["bgcolor", "color", "border", "border_radius", "border_color", "shadow", "padding", "margin", "icon_color"]
    for p in props:
        if hasattr(new, p):
            setattr(existing, p, getattr(new, p))

def update_control_tree(existing, new):
    """
    Actualiza recursivamente un árbol de controles Flet en su lugar (in-place)
    para conservar las referencias de contenedores scrollables (ListView, GridView)
    y evitar perder la posición de scroll al redibujar.
    """
    if existing is None:
        return new
    if new is None:
        return None
    if type(existing) != type(new):
        return new
        
    if isinstance(existing, ft.Container):
        copy_visual_props(existing, new)
        existing.content = update_control_tree(existing.content, new.content)
        return existing
        
    elif isinstance(existing, (ft.Column, ft.Row, ft.Stack)):
        copy_visual_props(existing, new)
        for i, new_child in enumerate(new.controls):
            if i < len(existing.controls):
                existing_child = existing.controls[i]
                if type(existing_child) == type(new_child) and isinstance(existing_child, (ft.ListView, ft.GridView)):
                    existing_child.controls = new_child.controls
                else:
                    # In-place update to prevent list clear() which resets layout and scroll
                    existing.controls[i] = update_control_tree(existing_child, new_child)
            else:
                existing.controls.append(new_child)
        
        while len(existing.controls) > len(new.controls):
            existing.controls.pop()
        return existing
        
    elif isinstance(existing, (ft.ListView, ft.GridView)):
        existing.controls = new.controls
        return existing
        
    elif isinstance(existing, ft.DataTable):
        copy_visual_props(existing, new)
        existing.columns = new.columns
        
        # Reutilizar DataRows mutándolos in-place para que Flet no envíe un comando clear()
        for i, new_row in enumerate(new.rows):
            if i < len(existing.rows):
                ext_row = existing.rows[i]
                ext_row.cells = new_row.cells
                if hasattr(new_row, 'color'): ext_row.color = new_row.color
                if hasattr(new_row, 'selected'): ext_row.selected = new_row.selected
            else:
                existing.rows.append(new_row)
                
        while len(existing.rows) > len(new.rows):
            existing.rows.pop()
            
        return existing
        
    return new

def main(page: ft.Page):
    """
    Punto de entrada principal refactorizado y optimizado para evitar parpadeos.
    """
    page.title = "Gestor de Muebles v1.0 - San Francisco de Macorís"
    page.padding = 15
    page.bgcolor = COLORS["background"]
    page.theme_mode = ft.ThemeMode.LIGHT
    
    # Chequeo asíncrono de garantías expiradas al iniciar
    threading.Thread(target=check_expired_warranties, daemon=True).start()
    # Sincronización asíncrona de cola de trabajos al iniciar
    threading.Thread(target=sync_cola_trabajos, daemon=True).start()
    
    # Interceptar el evento de cierre de ventana para guardar el estado transitorio
    page.window_prevent_close = True
    
    def on_window_event(e):
        if e.data == "close":
            save_transient_state()
            try:
                page.window.destroy()
            except Exception:
                logging.error("Error closing Flet window", exc_info=True)
            import os
            os._exit(0)
            
    page.on_window_event = on_window_event
    
    # En Flet >= 0.80, FilePicker es un servicio y no se agrega al overlay.
    


    # Contenedores estables para evitar parpadeo y reconstrucción masiva
    main_layout_container = None
    config_layout_container = None
    
    # Referencias de controles para actualización local reactiva
    left_panel_ref = None
    top_bar_ref = None
    central_area_ref = None
    right_panel_ref = None

    # ----------------------------------------
    # EL MOTOR DE RENDERIZADO OPTIMIZADO
    # ----------------------------------------
    def render_ui():
        nonlocal main_layout_container, config_layout_container
        nonlocal left_panel_ref, top_bar_ref, central_area_ref, right_panel_ref
        
        # Aplicar el tema globalmente antes de construir cualquier control
        is_dark = False
        apply_theme(is_dark)
        page.theme_mode = ft.ThemeMode.LIGHT
        page.bgcolor = COLORS["background"]
        
        view = app_state.get("central_view")
        
        if view == "configuracion":
            # Ocultar layout principal
            if main_layout_container:
                main_layout_container.visible = False
                main_layout_container.update()
                
            config_layout = create_full_config_layout(app_state, handle_action)
            if not config_layout_container:
                config_layout_container = ft.Container(content=config_layout, expand=True)
                page.add(config_layout_container)
            else:
                config_layout_container.content = config_layout
                config_layout_container.visible = True
                config_layout_container.update()
        else:
            # Ocultar vista de configuración
            if config_layout_container:
                config_layout_container.visible = False
                config_layout_container.update()
                
            if not main_layout_container:
                # Primera inicialización: Instanciamos los paneles una sola vez
                left_panel_ref = create_client_panel(app_state, handle_action)
                top_bar_ref = create_top_bar(app_state, handle_action)
                central_area_ref = create_central_zone(app_state, handle_action)
                right_panel_ref = create_right_panel(app_state, handle_action)
                
                middle_column = ft.Column([top_bar_ref, central_area_ref], expand=True)
                
                row_layout = ft.Row(
                    controls=[left_panel_ref, middle_column, right_panel_ref],
                    expand=True,
                    spacing=15 
                )
                main_layout_container = ft.Container(content=row_layout, expand=True)
                page.add(main_layout_container)
            else:
                # Actualización en caliente: Modificamos las propiedades de los controles estables
                main_layout_container.visible = True
                
                new_left = create_client_panel(app_state, handle_action)
                new_top = create_top_bar(app_state, handle_action)
                new_central = create_central_zone(app_state, handle_action)
                new_right = create_right_panel(app_state, handle_action)
                
                # Inyectamos el nuevo contenido de forma inteligente para preservar scroll
                left_panel_ref.content = update_control_tree(left_panel_ref.content, new_left.content)
                top_bar_ref.controls = new_top.controls
                central_area_ref.content = update_control_tree(central_area_ref.content, new_central.content)
                right_panel_ref.content = update_control_tree(right_panel_ref.content, new_right.content)
                right_panel_ref.visible = new_right.visible
                right_panel_ref.width = new_right.width
                right_panel_ref.height = new_right.height
                
                left_panel_ref.visible = new_left.visible
                left_panel_ref.width = new_left.width
                left_panel_ref.height = new_left.height
                
                # Copy properties explícitamente para las raíces
                copy_visual_props(right_panel_ref, new_right)
                copy_visual_props(left_panel_ref, new_left)
                
                # Actualizamos localmente cada panel de forma atómica y ultra-fluida
                left_panel_ref.update()
                top_bar_ref.update()
                central_area_ref.update()
                right_panel_ref.update()
                main_layout_container.update()
                
        page.update()

    # Inicializamos el estado central pasando el callback de render y la referencia de la página
    init_state(render_ui, page)

if __name__ == "__main__":
    # assets_dir apunta a database/img_uploads/ para que ft.Image con rutas
    # relativas (ej. "/archivo.jpg") funcione tanto en desktop como en web.
    ft.app(target=main, assets_dir="database/img_uploads")


