import json
import urllib.request
import urllib.error
import threading
from datetime import datetime

# --- ESTADO GLOBAL ---
app_state = {
    "selected_client": None,       
    "central_view": "catalogo",    
    "selected_products": [],
    "clients_cache": [],
    "catalog_cache": [],
    "stock_cache": [],
    "images_cache": {},
    "facturas_cache": [],
    "deliveries_cache": [],
    "trabajos_cache": [],
    "envios_cache": [],
    "facturas_work_cache": [],
    "api_config": {
        "api_url": "http://localhost:8000",
        "api_token": ""
    },
    "facturas_filter_text": "",
    "facturas_filter_period": "Hoy",
    "clients_filter_text": "",
    "trabajos_filter_area": "Todos",
    "trabajos_filter_tipo": "Todos",
    "trabajos_filter_status": "Todos",
    "trabajos_active_tab": 0,
    "entrega_activa": True,
    "direccion_entrega": "",
    "is_fast_invoice": False,
    "monto_pagado": 0.0,
    "nota_pago": "",
}

_page_ref = None

def _api_get(endpoint):
    url = app_state["api_config"]["api_url"] + endpoint
    token = app_state["api_config"]["api_token"]
    if not token: return []
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"API GET error {endpoint}: {e}")
        return []

def _api_post(endpoint, payload):
    url = app_state["api_config"]["api_url"] + endpoint
    token = app_state["api_config"]["api_token"]
    if not token: return None
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"API POST error {endpoint}: {e}")
        return None

def init_state(render_cb, page):
    global _page_ref
    _page_ref = page
    
    # 1. Login
    try:
        url = app_state["api_config"]["api_url"] + "/api/v1/auth/login"
        data = b"username=pichardo&password=admin123"
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                resp_data = json.loads(response.read().decode())
                app_state["api_config"]["api_token"] = resp_data.get("access_token")
                print("✅ Login API exitoso.")
    except Exception as e:
        print(f"⚠️ Error Login API: {e}")

    # 2. Fetch Initial Data (Conexión temporal para pruebas)
    # Solo intentamos cargar si hay token
    if app_state["api_config"]["api_token"]:
        # El backend usa /api/v1/sync/pull para bajar todo de golpe
        print("Obteniendo datos iniciales del backend...")
        sync_data = _api_get("/api/v1/sync/pull")
        if isinstance(sync_data, dict):
            app_state["clients_cache"] = sync_data.get("clientes", [])
            app_state["facturas_cache"] = sync_data.get("facturas", [])
            app_state["catalog_cache"] = sync_data.get("catalogo", [])
            app_state["stock_cache"] = sync_data.get("stock", [])
            app_state["trabajos_cache"] = sync_data.get("items", [])
            app_state["envios_cache"] = sync_data.get("envios", [])
            print("✅ Datos cargados correctamente.")
    
    if render_cb:
        render_cb()

def handle_action(action_type, payload=None):
    print(f"-> Action Dispatch: {action_type} | Payload: {payload}")
    
    # Conexión genérica / mock de acciones para pruebas temporales
    if action_type == "save_client":
        resp = _api_post("/api/v1/clientes", payload)
        if resp:
            payload["id"] = resp.get("id")
            app_state["clients_cache"].append(payload)
            
    elif action_type == "process_invoice":
        resp = _api_post("/api/v1/facturas", payload)
        if resp:
            app_state["facturas_cache"].append(resp)
            app_state["selected_products"] = []
            app_state["central_view"] = "invoice_view"
    
    # Forzamos re-render para la UI Flet
    if _page_ref:
        _page_ref.update()

def save_transient_state():
    pass

# --- MOCKS de Base de Datos y Core ---
def check_expired_warranties(): pass
def sync_cola_trabajos(): pass
def insert_image(*args, **kwargs): return 1
def get_all_facturas(): return app_state["facturas_cache"]
def get_all_images(): return {}
def load_config(): return {}
def generate_invoice_pdf(*args, **kwargs): pass
def generate_invoice_image(*args, **kwargs): pass
def share_file_to_whatsapp(*args, **kwargs): pass

def obtener_hora(): return datetime.now()
def obtener_hora_str(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
