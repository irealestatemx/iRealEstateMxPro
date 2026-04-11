import os
import io
import re
import json
import uuid
import time
import hmac
import shutil
import asyncio
import hashlib
import secrets
import subprocess
from pathlib import Path
from typing import List, Optional, Dict
from collections import defaultdict

from fastapi import FastAPI, Request, Form, File, UploadFile, Depends
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse, RedirectResponse
from starlette.responses import PlainTextResponse, Response as StarletteResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import OpenAI
from dotenv import load_dotenv
from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import httpx

load_dotenv()

from database import (
    database, init_db, close_db,
    save_property, get_all_properties, get_property_by_id, search_properties,
    update_property, toggle_property, count_properties,
    save_desarrollo, get_all_desarrollos, get_desarrollo_by_id,
    search_desarrollos, update_desarrollo,
    authenticate_user, get_user_by_email, get_user_by_id, get_all_users, create_user,
    update_user, delete_user, delete_user_permanent, seed_admin_user, get_users_by_rol,
    get_properties_by_user,
    get_user_by_prefijo, get_all_referidos,
    create_prospecto, get_all_prospectos, get_prospecto_by_id,
    update_prospecto, count_prospectos, delete_prospecto,
    get_prospecto_by_telefono, agregar_historial_prospecto,
    create_cita_chatbot, get_citas_chatbot, update_cita_chatbot, check_disponibilidad_citas,
    save_documento, get_documentos_by_propiedad, update_documento_estado,
    get_properties_by_vendedor, get_properties_by_comprador, get_properties_by_desarrollo,
    get_propiedades_seguimiento, set_tipo_compra,
    guardar_seguimiento, get_ultimo_seguimiento_por_propiedad,
    crear_notificacion, get_notificaciones, marcar_notificacion_leida,
    contar_notificaciones_no_leidas, get_propiedades_con_docs_pendientes,
    get_site_config, set_site_config, get_all_site_config,
    # REstateFlow
    crear_sprint, get_sprint_activo, get_sprint_by_id, cerrar_sprint, get_sprints_historial,
    agregar_sprint_item, mover_sprint_item, get_sprint_items, eliminar_sprint_item,
    guardar_standup, get_standup_hoy, get_standups_sprint,
    registrar_bloqueo, resolver_bloqueo, get_bloqueos_activos,
    get_kpis_agente, get_kpis_referido, get_kpis_todos_agentes, get_kpis_todos_referidos,
    get_sprint_review_data,
)

# ─── Sesiones con cookie firmada ───
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    print("[SEGURIDAD] ⚠ SECRET_KEY no configurada en .env — generando una temporal")
    SECRET_KEY = secrets.token_hex(32)
serializer = URLSafeTimedSerializer(SECRET_KEY)
SESSION_MAX_AGE = 86400 * 7  # 7 dias


def get_session_user_id(request: Request) -> Optional[int]:
    """Lee el user_id de la cookie de sesion."""
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        user_id = serializer.loads(token, max_age=SESSION_MAX_AGE)
        return user_id
    except (BadSignature, SignatureExpired):
        return None


async def require_auth(request: Request):
    """Dependencia que redirige a login si no hay sesion."""
    user_id = get_session_user_id(request)
    if not user_id:
        return None
    return await get_user_by_id(user_id)

app = FastAPI(title="iRealEstateMxPro")


# ═══════════════════════════════════════════════════════════
# SEGURIDAD: Headers HTTP, Rate Limiting, CSRF
# ═══════════════════════════════════════════════════════════

# ─── 1. Headers de seguridad HTTP ───
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://maps.googleapis.com https://www.googletagmanager.com https://www.google-analytics.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data: blob: https: http:; "
            "connect-src 'self' https://maps.googleapis.com https://www.google-analytics.com; "
            "frame-src 'self' https://www.google.com https://maps.google.com; "
            "object-src 'none'; "
            "base-uri 'self'"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)


# ─── 2. Rate Limiting ───
_rate_limit_store: Dict[str, list] = defaultdict(list)
RATE_LIMITS = {
    "/login": (5, 300),           # 5 intentos cada 5 min
    "/forgot-password": (3, 600), # 3 intentos cada 10 min
    "/reset-password": (5, 600),  # 5 intentos cada 10 min
    "/api/whatsapp/debounce": (60, 60),  # 60 req/min
    "/api/prospectos/registrar": (30, 60),
}

def _check_rate_limit(ip: str, path: str) -> bool:
    """Retorna True si el request está dentro del límite. False si excede."""
    key = f"{ip}:{path}"
    # Buscar la ruta más específica que aplique
    limit_config = None
    for route, config in RATE_LIMITS.items():
        if path == route or path.startswith(route):
            limit_config = config
            break
    if not limit_config:
        return True
    max_requests, window = limit_config
    now = time.time()
    # Limpiar requests viejos
    _rate_limit_store[key] = [t for t in _rate_limit_store[key] if now - t < window]
    if len(_rate_limit_store[key]) >= max_requests:
        return False
    _rate_limit_store[key].append(now)
    return True

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST":
            ip = request.client.host if request.client else "unknown"
            forwarded = request.headers.get("x-forwarded-for", "")
            if forwarded:
                ip = forwarded.split(",")[0].strip()
            if not _check_rate_limit(ip, request.url.path):
                return JSONResponse(
                    {"error": "Demasiados intentos. Intenta de nuevo más tarde."},
                    status_code=429
                )
        return await call_next(request)

app.add_middleware(RateLimitMiddleware)


# ─── 3. CSRF Protection ───
CSRF_SECRET = os.getenv("CSRF_SECRET", SECRET_KEY)
CSRF_EXEMPT_PATHS = {
    "/api/whatsapp/debounce",
    "/api/prospectos/registrar",
    "/api/citas/disponibilidad",
    "/api/citas/registrar",
    "/api/whatsapp/pause",
    "/api/whatsapp/unpause",
    "/api/whatsapp/status",
    "/api/whatsapp/deactivate",
    "/api/kommo/webhook",
    "/webhook/n8n",
}

def generate_csrf_token(session_id: str) -> str:
    """Genera un token CSRF basado en el session_id."""
    msg = f"{session_id}:{CSRF_SECRET}".encode()
    return hmac.new(CSRF_SECRET.encode(), msg, hashlib.sha256).hexdigest()[:32]

def verify_csrf_token(session_id: str, token: str) -> bool:
    """Verifica que el token CSRF sea válido."""
    expected = generate_csrf_token(session_id)
    return hmac.compare_digest(expected, token)


# ─── 4. Validación MIME de uploads ───
MIME_WHITELIST = {
    ".jpg": ["image/jpeg"],
    ".jpeg": ["image/jpeg"],
    ".png": ["image/png"],
    ".webp": ["image/webp"],
    ".pdf": ["application/pdf"],
    ".doc": ["application/msword"],
    ".docx": ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
}


@app.on_event("startup")
async def startup():
    await init_db()
    # Cargar desarrollos iniciales si la tabla esta vacia
    try:
        devs = await get_all_desarrollos(active_only=False)
        if not devs:
            from seed_desarrollos import DESARROLLOS_INICIALES
            for dev in DESARROLLOS_INICIALES:
                await save_desarrollo(dev)
            print(f"[SEED] Cargados {len(DESARROLLOS_INICIALES)} desarrollos iniciales")
    except Exception as e:
        print(f"[SEED] Error cargando desarrollos: {e}")
    # Crear admin si no existe
    try:
        await seed_admin_user()
    except Exception as e:
        print(f"[SEED] Error creando admin: {e}")


@app.on_event("shutdown")
async def shutdown():
    await close_db()

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_DIR = BASE_DIR / "static" / "videos"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_PROJECT_DIR = BASE_DIR / "video"
AUDIO_DIR = BASE_DIR / "static" / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# Tracking de renderizados de video en progreso
video_jobs: Dict[str, dict] = {}

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Hacer csrf_token disponible en todos los templates
def _get_csrf_for_request(request: Request) -> str:
    token = request.cookies.get("session", "anonymous")
    return generate_csrf_token(token)

templates.env.globals["csrf_token"] = ""  # placeholder, se setea por request

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ─── Utilidades ───

def sanitize_html(text: str) -> str:
    """Escapa HTML peligroso pero permite saltos de línea como <br>."""
    if not text:
        return ""
    import html
    escaped = html.escape(str(text))
    return escaped.replace("\n", "<br>")

# Registrar filtro seguro en Jinja2
templates.env.filters["safe_nl2br"] = sanitize_html


def format_price(price: float) -> str:
    return f"${price:,.0f} MXN"


def build_property_summary(data: dict) -> str:
    amenidades = data.get("amenidades", [])
    amenidades_str = ", ".join(amenidades) if amenidades else "ninguna especificada"

    caracteristicas = []
    if data.get("recamaras"):
        caracteristicas.append(f"{data['recamaras']} recamaras")
    if data.get("banos"):
        caracteristicas.append(f"{data['banos']} banos")
    if data.get("metros_construidos"):
        caracteristicas.append(f"{data['metros_construidos']} m2 construidos")
    if data.get("metros_terreno"):
        caracteristicas.append(f"{data['metros_terreno']} m2 de terreno")
    if data.get("estacionamientos"):
        caracteristicas.append(f"{data['estacionamientos']} cajon(es) de estacionamiento")

    return f"""
Tipo de propiedad: {data['tipo_propiedad']}
Operacion: {data['operacion']}
Ubicacion: {data['direccion']}, {data['ciudad']}, {data['estado']}
Precio: {format_price(float(data['precio']))}
Caracteristicas: {', '.join(caracteristicas) if caracteristicas else 'No especificadas'}
Amenidades: {amenidades_str}
Notas del agente: {data.get('descripcion_agente', '')}
""".strip()


# ─── Generacion con IA ───

def generate_professional_description(summary: str) -> str:
    prompt = f"""Eres un experto en marketing inmobiliario de Mexico, especializado en el mercado de Guanajuato y Leon.
Con base en los siguientes datos de la propiedad, redacta una descripcion profesional, atractiva y persuasiva de 150 a 200 palabras.
El tono debe ser formal-moderno, resaltar los puntos fuertes de la propiedad y motivar al comprador/arrendatario potencial a contactar al agente.
Escribe directamente la descripcion, sin titulos ni encabezados.

Datos de la propiedad:
{summary}

Descripcion profesional:"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


def generate_instagram_copy(summary: str, tipo: str, operacion: str, ciudad: str) -> str:
    ciudad_lower = ciudad.lower().replace(" ", "")
    operacion_tag = "EnVenta" if operacion == "Venta" else "EnRenta"
    tipo_tag = tipo.replace(" ", "")

    prompt = f"""Eres un experto en redes sociales para el sector inmobiliario en Mexico.
Con base en los siguientes datos de propiedad, crea un copy atractivo para Instagram.

Estructura requerida:
1. Texto principal: 2-3 oraciones impactantes, maximo 280 caracteres, con emoji(s) al inicio, llamada a la accion al final (ej: "Agenda tu visita hoy!")
2. Salto de linea
3. Bloque de hashtags: exactamente 20 hashtags relevantes al mercado inmobiliario mexicano, la ciudad ({ciudad}) y el tipo de operacion.

Hashtags sugeridos a incluir (puedes agregar mas relevantes):
#BienesRaicesMexico #Inmobiliaria #InmobiliariaLeon #InmobiliariaGuanajuato #{ciudad_lower} #Guanajuato #{tipo_tag}{operacion_tag} #PropiedadesLeon #Mexico #CasasMexico #InversionInmobiliaria #PropiedadesMexico #RealtorMexico #AgentInmobiliario #ViveLeon

Datos de la propiedad:
{summary}

Instagram copy:"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=350,
        temperature=0.8,
    )
    return response.choices[0].message.content.strip()


# ─── Generación de guión para video ───

SCENE_NAMES = ["fachada", "sala", "cocina", "recamara", "bano", "cierre"]
SCENE_LABELS = {
    "fachada": "Fachada",
    "sala": "Sala / Estancia",
    "cocina": "Cocina",
    "recamara": "Recámara Principal",
    "bano": "Baño / Espacios",
    "cierre": "Cierre",
}


def generate_video_script(summary: str, video_tipo: str, voice_tones: list, voice_context: str) -> dict:
    """Genera un guión por escenas para el video con OpenAI."""
    tones_str = ", ".join(voice_tones) if voice_tones else "profesional"

    if video_tipo == "reel":
        duration_hint = "Cada escena debe tener 1-2 oraciones cortas (máximo 15 palabras por escena). Total: 15-25 segundos de narración."
    else:
        duration_hint = "Cada escena debe tener 2-3 oraciones descriptivas (máximo 30 palabras por escena). Total: 45-60 segundos de narración."

    context_extra = f"\nContexto adicional del agente: {voice_context}" if voice_context else ""

    prompt = f"""Eres un guionista de videos inmobiliarios en México. Genera un guión para un video de propiedad.

Tono: {tones_str}
{duration_hint}
{context_extra}

Datos de la propiedad:
{summary}

Genera EXACTAMENTE 6 escenas en formato JSON. Cada escena es un objeto con "scene" y "narration":
1. fachada - Primera impresión de la propiedad desde afuera
2. sala - Descripción de la sala/estancia principal
3. cocina - Descripción de la cocina y equipamiento
4. recamara - Descripción de la recámara principal
5. bano - Descripción de baños u otros espacios destacados
6. cierre - Llamada a la acción: urgencia, invitación a agendar cita

Responde SOLO con el JSON array, sin markdown:
[{{"scene":"fachada","narration":"texto..."}}, ...]"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.7,
        )
        raw = response.choices[0].message.content.strip()
        # Limpiar posible markdown
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        scenes = json.loads(raw)
        result = {}
        for s in scenes:
            result[s["scene"]] = s["narration"]
        return result
    except Exception as e:
        print(f"[SCRIPT] Error generando guión: {e}")
        return {
            "fachada": "Descubre esta increíble propiedad.",
            "sala": "Amplios espacios llenos de luz natural.",
            "cocina": "Cocina moderna con acabados de primera.",
            "recamara": "Recámara principal con espacio generoso.",
            "bano": "Baños elegantes con detalles de calidad.",
            "cierre": "No dejes pasar esta oportunidad. Agenda tu visita hoy.",
        }


def generate_tts_audio(text: str, voice: str = "nova", output_path: str = "") -> str:
    """Genera audio de voz con OpenAI TTS. Retorna path del archivo MP3."""
    if not output_path:
        output_path = str(AUDIO_DIR / f"tts_{uuid.uuid4().hex[:8]}.mp3")

    try:
        response = client.audio.speech.create(
            model="tts-1-hd",
            voice=voice,
            input=text,
            speed=0.95,
        )
        response.stream_to_file(output_path)
        print(f"[TTS] Audio generado: {output_path} ({len(text)} chars, voz={voice})")
        return output_path
    except Exception as e:
        print(f"[TTS] Error: {e}")
        return ""


def get_tts_voice(gender: str) -> str:
    """Retorna la voz de OpenAI TTS segun el genero. Todas leen español correctamente."""
    if gender == "masculine":
        return "alloy"   # Voz masculina natural, buen español
    return "nova"        # Voz femenina calida, buen español


# ─── Generacion de PDF ───

class PropertyPDF(FPDF):
    """PDF personalizado para fichas de propiedades inmobiliarias."""

    NAVY = (26, 60, 94)
    GOLD = (201, 162, 39)
    WHITE = (255, 255, 255)
    GRAY_LIGHT = (241, 243, 245)
    GRAY_TEXT = (108, 117, 125)
    DARK = (52, 58, 64)

    def header(self):
        # Barra superior azul marino
        self.set_fill_color(*self.NAVY)
        self.rect(0, 0, 210, 28, "F")
        # Logo / nombre
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*self.WHITE)
        self.set_xy(12, 6)
        self.cell(0, 8, "iRealEstateMxPro", ln=False)
        # Subtitulo
        self.set_font("Helvetica", "", 9)
        self.set_text_color(180, 200, 220)
        self.set_xy(12, 15)
        self.cell(0, 8, "Ficha de propiedad", ln=False)
        # Linea dorada decorativa
        self.set_fill_color(*self.GOLD)
        self.rect(0, 28, 210, 2, "F")
        self.set_y(35)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*self.GRAY_TEXT)
        self.cell(0, 10, f"iRealEstateMxPro  |  Pagina {self.page_no()}", align="C")

    def _safe(self, text: str) -> str:
        """Limpia caracteres que latin-1 no soporta."""
        if not text:
            return ""
        replacements = {
            "\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'",
            "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u00b2": "2",
            "\u2022": "-", "\u00b7": "-",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text.encode("latin-1", errors="replace").decode("latin-1")

    def section_title(self, title: str):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*self.NAVY)
        self.cell(0, 8, self._safe(title), ln=True)
        self.set_fill_color(*self.GOLD)
        self.rect(self.get_x(), self.get_y(), 40, 0.8, "F")
        self.ln(3)

    def gray_box_start(self):
        self._box_y = self.get_y()

    def gray_box_end(self):
        h = self.get_y() - self._box_y
        self.set_fill_color(*self.GRAY_LIGHT)
        # Dibuja el fondo detras (truco: lo dibujamos y luego avanzamos)
        page = self.page
        self.page = page
        self.rect(10, self._box_y - 2, 190, h + 4, "F")


def url_to_filepath(url: str) -> Path:
    """Convierte una URL como /static/uploads/uuid/file.jpg a una ruta de archivo."""
    relative = url.lstrip("/")
    return BASE_DIR / relative


def generate_property_pdf(data: dict) -> bytes:
    pdf = PropertyPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)

    s = pdf._safe  # shortcut

    portada_url = data.get("foto_portada_url")
    fotos_extra = data.get("fotos_extra_urls", [])
    if isinstance(fotos_extra, str):
        import json as _j
        try:
            fotos_extra = _j.loads(fotos_extra)
        except Exception:
            fotos_extra = []

    amenidades = data.get("amenidades", [])
    if isinstance(amenidades, str):
        import json as _j
        try:
            amenidades = _j.loads(amenidades)
        except Exception:
            amenidades = []

    # ══════════════════════════════════════
    # PAGINA 1 — Portada hero con foto grande
    # ══════════════════════════════════════
    pdf.add_page()

    # Determinar qué imagen usar como hero (panorámica > portada)
    hero_path = data.get("hero_pdf_path")
    if not hero_path and portada_url:
        p = url_to_filepath(portada_url)
        if p.exists():
            hero_path = str(p)

    hero_w, hero_h = 190, 120  # mm en el PDF

    if hero_path and Path(hero_path).exists():
        try:
            # Recortar al ratio correcto (190:120 ≈ 1.58:1) para evitar estiramiento
            img = _open_image(hero_path, "RGB")
            target_ratio = hero_w / hero_h  # ~1.583
            img_w, img_h = img.size
            img_ratio = img_w / img_h

            if img_ratio > target_ratio:
                # Imagen más ancha: recortar lados
                new_w = int(img_h * target_ratio)
                offset = (img_w - new_w) // 2
                img = img.crop((offset, 0, offset + new_w, img_h))
            elif img_ratio < target_ratio:
                # Imagen más alta: recortar arriba/abajo
                new_h = int(img_w / target_ratio)
                offset = (img_h - new_h) // 2
                img = img.crop((0, offset, img_w, offset + new_h))

            # Guardar versión recortada en temporal
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            img.save(tmp.name, "JPEG", quality=92)
            pdf.image(tmp.name, x=10, w=hero_w, h=hero_h)
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
        except Exception:
            pdf.set_fill_color(220, 220, 220)
            pdf.rect(10, pdf.get_y(), hero_w, hero_h, "F")
        pdf.ln(124)
    else:
        pdf.ln(8)

    # Badge operacion
    operacion = data.get("operacion", "Venta")
    badge_text = s(f"  {operacion.upper()}  ")
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(192, 57, 43) if "venta" in operacion.lower() else pdf.set_fill_color(26, 60, 94)
    pdf.set_text_color(*PropertyPDF.WHITE)
    badge_w = pdf.get_string_width(badge_text) + 6
    pdf.cell(badge_w, 6, badge_text, fill=True)
    pdf.ln(10)

    # Precio grande
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_text_color(*PropertyPDF.NAVY)
    pdf.cell(0, 14, s(data.get("precio_formateado", "")), ln=True)

    # Ubicacion
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*PropertyPDF.GRAY_TEXT)
    ubicacion = f"{data.get('direccion', '')}, {data.get('ciudad', '')}, {data.get('estado', '')}"
    pdf.cell(0, 7, s(ubicacion), ln=True)
    pdf.ln(6)

    # ── Linea dorada separadora ──
    pdf.set_fill_color(*PropertyPDF.GOLD)
    pdf.rect(10, pdf.get_y(), 190, 0.8, "F")
    pdf.ln(6)

    # ── Caracteristicas en grid elegante ──
    specs = []
    if data.get("recamaras"):
        specs.append(("Recamaras", str(data["recamaras"])))
    if data.get("banos"):
        specs.append(("Banos", str(data["banos"])))
    if data.get("metros_construidos"):
        specs.append(("m2 Construidos", str(data["metros_construidos"])))
    if data.get("metros_terreno"):
        specs.append(("m2 Terreno", str(data["metros_terreno"])))
    if data.get("estacionamientos"):
        specs.append(("Estacionamientos", str(data["estacionamientos"])))

    if specs:
        col_count = min(len(specs), 5)
        col_w = 190 / col_count
        row_y = pdf.get_y()

        # Fondo gris claro
        pdf.set_fill_color(*PropertyPDF.GRAY_LIGHT)
        pdf.rect(10, row_y, 190, 22, "F")

        # Lineas verticales separadoras
        pdf.set_draw_color(220, 220, 220)
        for i in range(1, col_count):
            x_line = 10 + col_w * i
            pdf.line(x_line, row_y + 3, x_line, row_y + 19)

        # Valores
        pdf.set_xy(10, row_y + 2)
        for label, value in specs:
            pdf.set_font("Helvetica", "B", 16)
            pdf.set_text_color(*PropertyPDF.NAVY)
            pdf.cell(col_w, 10, s(value), align="C")
        pdf.ln()
        # Labels
        pdf.set_x(10)
        for label, value in specs:
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(*PropertyPDF.GRAY_TEXT)
            pdf.cell(col_w, 6, s(label), align="C")
        pdf.set_y(row_y + 26)

    # ══════════════════════════════════════
    # PAGINA 2 — Descripcion
    # ══════════════════════════════════════
    descripcion = data.get("descripcion_profesional", "")
    if descripcion:
        if pdf.get_y() > 220:
            pdf.add_page()

        pdf.section_title("Descripcion")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*PropertyPDF.DARK)
        pdf.multi_cell(190, 5.5, s(descripcion))
        pdf.ln(8)

    # ── Amenidades ──
    if amenidades:
        if pdf.get_y() > 240:
            pdf.add_page()

        pdf.section_title("Amenidades")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*PropertyPDF.DARK)

        x = 10
        y = pdf.get_y()
        for a in amenidades:
            if not isinstance(a, str):
                a = str(a)
            tag_text = s(f"  {a}  ")
            tag_w = pdf.get_string_width(tag_text) + 4
            if x + tag_w > 200:
                x = 10
                y += 9
                pdf.set_y(y)
            pdf.set_xy(x, y)
            pdf.set_fill_color(*PropertyPDF.GRAY_LIGHT)
            pdf.set_draw_color(200, 200, 200)
            pdf.cell(tag_w, 7, tag_text, border=1, fill=True, align="C")
            x += tag_w + 3
        pdf.ln(14)

    # ══════════════════════════════════════
    # GALERIA — Todas las fotos en una pagina
    # ══════════════════════════════════════
    all_photo_urls = []
    if portada_url:
        all_photo_urls.append(portada_url)
    all_photo_urls.extend(fotos_extra)

    if all_photo_urls:
        pdf.add_page()
        pdf.section_title(f"Galeria de fotos ({len(all_photo_urls)})")

        # Grid de 2 columnas
        col_w = 92
        col_h = 68
        gap_x = 6
        gap_y = 6
        x_start = 10
        y_start = pdf.get_y()
        col = 0
        row_top = y_start

        for i, url in enumerate(all_photo_urls):
            fpath = url_to_filepath(url)
            if not fpath.exists():
                continue
            x = x_start + col * (col_w + gap_x)
            y = row_top

            # Verificar espacio en pagina
            if y + col_h > 265:
                pdf.add_page()
                pdf.section_title("Galeria (continuacion)")
                row_top = pdf.get_y()
                y = row_top
                col = 0
                x = x_start

            try:
                pdf.image(str(fpath), x=x, y=y, w=col_w, h=col_h)
            except Exception:
                pass

            col += 1
            if col >= 2:
                col = 0
                row_top += col_h + gap_y

        if col == 1:
            row_top += col_h + gap_y
        pdf.set_y(row_top)

    # ══════════════════════════════════════
    # AGENTE DE CONTACTO
    # ══════════════════════════════════════
    if pdf.get_y() > 240:
        pdf.add_page()

    pdf.ln(4)
    pdf.section_title("Agente de contacto")

    # Tarjeta de contacto con fondo
    pdf.set_fill_color(*PropertyPDF.GRAY_LIGHT)
    box_y = pdf.get_y()
    pdf.rect(10, box_y, 190, 24, "F")

    # Linea dorada izquierda
    pdf.set_fill_color(*PropertyPDF.GOLD)
    pdf.rect(10, box_y, 2, 24, "F")

    # Avatar circular
    pdf.set_fill_color(*PropertyPDF.NAVY)
    pdf.rect(16, box_y + 4, 16, 16, "F")
    nombre = data.get("agente_nombre", "")
    initial = s(nombre[0].upper()) if nombre else "A"
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*PropertyPDF.WHITE)
    pdf.set_xy(16, box_y + 8)
    pdf.cell(16, 8, initial, align="C")

    # Datos
    pdf.set_xy(36, box_y + 4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*PropertyPDF.NAVY)
    pdf.cell(80, 6, s(nombre))

    pdf.set_xy(36, box_y + 10)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*PropertyPDF.GRAY_TEXT)
    tel = data.get("agente_telefono", "")
    email = data.get("agente_email", "")
    pdf.cell(80, 5, s(f"Tel: {tel}"))

    pdf.set_xy(36, box_y + 16)
    pdf.cell(80, 5, s(f"Email: {email}"))

    pdf.ln(30)

    return pdf.output()


# ─── Generacion de imagen Instagram ───


def _open_image(path, mode="RGBA"):
    """Abre una imagen corrigiendo la orientación EXIF (evita fotos acostadas)."""
    from PIL import ImageOps
    img = Image.open(path)
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    return img.convert(mode)


def _find_font(bold: bool = False) -> str:
    """Busca una fuente TrueType disponible en el sistema."""
    candidates_bold = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    candidates_regular = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    candidates = candidates_bold if bold else candidates_regular
    for path in candidates:
        if Path(path).exists():
            return path
    return ""


def generate_instagram_image(data: dict) -> bytes:
    """Genera imagen cuadrada 1080x1080 para Instagram."""
    SIZE = 1080
    NAVY = (26, 60, 94)
    GOLD = (201, 162, 39)
    WHITE = (255, 255, 255)
    WHITE_90 = (255, 255, 255, 230)
    WHITE_60 = (255, 255, 255, 153)

    # ── Cargar fuentes ──
    font_bold_path = _find_font(bold=True)
    font_regular_path = _find_font(bold=False)

    def load_font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
        path = font_bold_path if bold else font_regular_path
        if path:
            return ImageFont.truetype(path, size)
        return ImageFont.load_default()

    font_badge = load_font(True, 32)
    font_price = load_font(True, 72)
    font_location = load_font(False, 34)
    font_specs = load_font(True, 30)
    font_specs_label = load_font(False, 24)
    font_brand = load_font(True, 36)
    font_brand_sub = load_font(False, 20)

    # ── Fondo: foto de portada ──
    portada_url = data.get("foto_portada_url")
    if portada_url:
        portada_path = url_to_filepath(portada_url)
        if portada_path.exists():
            bg = _open_image(portada_path, "RGBA")
        else:
            bg = Image.new("RGBA", (SIZE, SIZE), NAVY)
    else:
        bg = Image.new("RGBA", (SIZE, SIZE), NAVY)

    # Recortar a cuadrado (crop centrado)
    w, h = bg.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    bg = bg.crop((left, top, left + side, top + side))
    bg = bg.resize((SIZE, SIZE), Image.LANCZOS)

    # ── Gradiente oscuro ──
    gradient = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw_grad = ImageDraw.Draw(gradient)
    # Gradiente superior (sutil)
    for y in range(300):
        alpha = int(180 * (1 - y / 300))
        draw_grad.line([(0, y), (SIZE, y)], fill=(0, 0, 0, alpha))
    # Gradiente inferior (fuerte, para que se lea el texto)
    for y in range(SIZE):
        if y > SIZE - 600:
            progress = (y - (SIZE - 600)) / 600
            alpha = int(220 * progress)
            draw_grad.line([(0, y), (SIZE, y)], fill=(0, 0, 0, alpha))

    bg = Image.alpha_composite(bg, gradient)

    # ── Overlay de dibujo ──
    overlay = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # ── Linea dorada superior decorativa ──
    draw.rectangle([0, 0, SIZE, 6], fill=GOLD)

    # ── Badge "EN VENTA" / "EN RENTA" (arriba izquierda) ──
    operacion = data.get("operacion", "Venta")
    badge_text = f"  EN {operacion.upper()}  "
    badge_bbox = font_badge.getbbox(badge_text)
    badge_w = badge_bbox[2] - badge_bbox[0] + 32
    badge_h = badge_bbox[3] - badge_bbox[1] + 20
    badge_x, badge_y = 50, 45

    # Fondo dorado del badge con esquinas
    draw.rounded_rectangle(
        [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
        radius=8, fill=GOLD
    )
    draw.text((badge_x + 16, badge_y + 8), badge_text, fill=NAVY, font=font_badge)

    # ── Logo iRealEstateMx (arriba derecha) ──
    logo_path = BASE_DIR / "static" / "img" / "logo-header.png"
    if logo_path.exists():
        logo_img = _open_image(logo_path, "RGBA")
        # Escalar logo a altura ~50px manteniendo proporciones
        logo_h = 50
        logo_ratio = logo_img.width / logo_img.height
        logo_w = int(logo_h * logo_ratio)
        logo_img = logo_img.resize((logo_w, logo_h), Image.LANCZOS)
        logo_x = SIZE - logo_w - 50
        logo_y = 40
        overlay.paste(logo_img, (logo_x, logo_y), logo_img)

    # ── Zona inferior: datos de la propiedad ──
    y_cursor = SIZE - 340

    # Linea dorada decorativa
    draw.rectangle([50, y_cursor, SIZE - 50, y_cursor + 3], fill=GOLD)
    y_cursor += 25

    # Precio
    precio = data.get("precio_formateado", "")
    draw.text((50, y_cursor), precio, fill=WHITE, font=font_price)
    y_cursor += 90

    # Ubicacion
    ubicacion = f"{data.get('direccion', '')}, {data.get('ciudad', '')}, {data.get('estado', '')}"
    # Truncar si es muy largo
    if len(ubicacion) > 50:
        ubicacion = ubicacion[:47] + "..."
    draw.text((50, y_cursor), ubicacion, fill=WHITE_60, font=font_location)
    y_cursor += 55

    # ── Specs row con separadores ──
    specs_parts = []
    if data.get("recamaras"):
        specs_parts.append(f"{data['recamaras']} Rec")
    if data.get("banos"):
        specs_parts.append(f"{data['banos']} Banos")
    if data.get("metros_construidos"):
        specs_parts.append(f"{data['metros_construidos']} m2")
    if data.get("metros_terreno"):
        specs_parts.append(f"{data['metros_terreno']} m2 Ter")
    if data.get("estacionamientos"):
        specs_parts.append(f"{data['estacionamientos']} Est")

    if specs_parts:
        # Dibujar cada spec con separador dorado
        x_spec = 50
        for i, part in enumerate(specs_parts):
            # Valor
            draw.text((x_spec, y_cursor), part, fill=WHITE, font=font_specs)
            spec_bbox = font_specs.getbbox(part)
            spec_w = spec_bbox[2] - spec_bbox[0]
            x_spec += spec_w + 20
            # Separador
            if i < len(specs_parts) - 1:
                draw.rectangle([x_spec, y_cursor + 4, x_spec + 3, y_cursor + 32], fill=GOLD)
                x_spec += 23

    y_cursor += 60

    # ── Linea dorada inferior ──
    draw.rectangle([50, y_cursor, SIZE - 50, y_cursor + 2], fill=GOLD)
    y_cursor += 15

    # ── Logo completo inferior ──
    logo_full_path = BASE_DIR / "static" / "img" / "logo-full.png"
    if logo_full_path.exists():
        logo_full = _open_image(logo_full_path, "RGBA")
        # Escalar a altura ~60px
        lf_h = 60
        lf_ratio = logo_full.width / logo_full.height
        lf_w = int(lf_h * lf_ratio)
        logo_full = logo_full.resize((lf_w, lf_h), Image.LANCZOS)
        overlay.paste(logo_full, (50, y_cursor - 5), logo_full)
    else:
        tagline = "BIENES RAICES  |  EXCLUSIVO"
        draw.text((50, y_cursor), tagline, fill=(*GOLD, 200), font=font_brand_sub)

    # Componer
    final = Image.alpha_composite(bg, overlay).convert("RGB")

    # Exportar a bytes
    buf = io.BytesIO()
    final.save(buf, format="JPEG", quality=95, optimize=True)
    buf.seek(0)
    return buf.getvalue()


def generate_instagram_story(data: dict) -> bytes:
    """Genera imagen vertical 1080x1920 para Instagram Story."""
    W, H = 1080, 1920
    NAVY = (26, 60, 94)
    GOLD = (201, 162, 39)
    WHITE = (255, 255, 255)
    RED = (192, 57, 43)

    font_bold_path = _find_font(bold=True)
    font_regular_path = _find_font(bold=False)
    def lf(bold, size):
        p = font_bold_path if bold else font_regular_path
        return ImageFont.truetype(p, size) if p else ImageFont.load_default()

    # Fondo con foto de portada
    portada_url = data.get("foto_portada_url")
    if portada_url:
        portada_path = url_to_filepath(portada_url)
        if portada_path.exists():
            bg = _open_image(portada_path, "RGBA")
        else:
            bg = Image.new("RGBA", (W, H), NAVY)
    else:
        bg = Image.new("RGBA", (W, H), NAVY)

    # Crop a 9:16 centrado
    bw, bh = bg.size
    target_r = W / H
    current_r = bw / bh
    if current_r > target_r:
        new_w = int(bh * target_r)
        left = (bw - new_w) // 2
        bg = bg.crop((left, 0, left + new_w, bh))
    else:
        new_h = int(bw / target_r)
        top = (bh - new_h) // 2
        bg = bg.crop((0, top, bw, top + new_h))
    bg = bg.resize((W, H), Image.LANCZOS)

    # Gradiente oscuro
    gradient = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dg = ImageDraw.Draw(gradient)
    for y in range(400):
        alpha = int(200 * (1 - y / 400))
        dg.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    for y in range(H):
        if y > H - 800:
            p = (y - (H - 800)) / 800
            dg.line([(0, y), (W, y)], fill=(0, 0, 0, int(230 * p)))
    bg = Image.alpha_composite(bg, gradient)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Barra dorada superior
    draw.rectangle([0, 0, W, 8], fill=GOLD)

    # Badge operación
    operacion = data.get("operacion", "Venta")
    badge_text = f"  EN {operacion.upper()}  "
    f_badge = lf(True, 36)
    bb = f_badge.getbbox(badge_text)
    bw2 = bb[2] - bb[0] + 36
    bh2 = bb[3] - bb[1] + 22
    draw.rounded_rectangle([60, 70, 60 + bw2, 70 + bh2], radius=8, fill=RED)
    draw.text((60 + 18, 70 + 8), badge_text, fill=WHITE, font=f_badge)

    # Logo arriba derecha
    logo_path = BASE_DIR / "static" / "img" / "logo-header.png"
    if logo_path.exists():
        logo = _open_image(logo_path, "RGBA")
        lh = 55
        lr = logo.width / logo.height
        logo = logo.resize((int(lh * lr), lh), Image.LANCZOS)
        overlay.paste(logo, (W - logo.width - 60, 65), logo)

    # Zona inferior: datos
    y = H - 650
    draw.rectangle([60, y, W - 60, y + 4], fill=GOLD)
    y += 30

    # Tipo de propiedad
    f_tipo = lf(True, 30)
    tipo = data.get("tipo_propiedad", "")
    draw.text((60, y), tipo.upper(), fill=GOLD, font=f_tipo)
    y += 50

    # Precio grande
    f_price = lf(True, 82)
    precio = data.get("precio_formateado", "")
    draw.text((60, y), precio, fill=WHITE, font=f_price)
    y += 110

    # Ubicación
    f_loc = lf(False, 34)
    ubicacion = f"{data.get('direccion', '')}, {data.get('ciudad', '')}"
    if len(ubicacion) > 45:
        ubicacion = ubicacion[:42] + "..."
    draw.text((60, y), ubicacion, fill=(255, 255, 255, 180), font=f_loc)
    y += 60

    # Specs
    f_spec = lf(True, 32)
    specs = []
    if data.get("recamaras"): specs.append(f"{data['recamaras']} Rec")
    if data.get("banos"): specs.append(f"{data['banos']} Baños")
    if data.get("metros_construidos"): specs.append(f"{data['metros_construidos']} m²")
    if data.get("metros_terreno"): specs.append(f"{data['metros_terreno']} m² Ter")
    if data.get("estacionamientos"): specs.append(f"{data['estacionamientos']} Est")
    if specs:
        x = 60
        for i, s in enumerate(specs):
            draw.text((x, y), s, fill=WHITE, font=f_spec)
            sw = f_spec.getbbox(s)[2] - f_spec.getbbox(s)[0]
            x += sw + 20
            if i < len(specs) - 1:
                draw.rectangle([x, y + 4, x + 3, y + 32], fill=GOLD)
                x += 23
    y += 70

    # Línea dorada
    draw.rectangle([60, y, W - 60, y + 3], fill=GOLD)
    y += 25

    # Agente
    f_agent = lf(True, 28)
    f_phone = lf(False, 26)
    agente = data.get("agente_nombre", "")
    telefono = data.get("agente_telefono", "")
    draw.text((60, y), agente, fill=WHITE, font=f_agent)
    y += 40
    draw.text((60, y), telefono, fill=GOLD, font=f_phone)
    y += 50

    # Swipe up hint
    f_swipe = lf(True, 24)
    swipe_text = "DESLIZA PARA MÁS INFO"
    sw = f_swipe.getbbox(swipe_text)[2] - f_swipe.getbbox(swipe_text)[0]
    draw.text(((W - sw) // 2, H - 100), swipe_text, fill=GOLD, font=f_swipe)
    # Flecha
    arrow_x = W // 2
    draw.polygon([(arrow_x - 12, H - 55), (arrow_x + 12, H - 55), (arrow_x, H - 40)], fill=GOLD)

    # Barra dorada inferior
    draw.rectangle([0, H - 8, W, H], fill=GOLD)

    final = Image.alpha_composite(bg, overlay).convert("RGB")
    buf = io.BytesIO()
    final.save(buf, format="JPEG", quality=95, optimize=True)
    buf.seek(0)
    return buf.getvalue()


def generate_instagram_carousel(data: dict) -> list:
    """Genera carrusel de 5-7 slides para Instagram (1080x1080 cada uno). Retorna lista de bytes."""
    SIZE = 1080
    NAVY = (26, 60, 94)
    NAVY_DARK = (13, 31, 51)
    GOLD = (201, 162, 39)
    WHITE = (255, 255, 255)
    RED = (192, 57, 43)

    font_bold_path = _find_font(bold=True)
    font_regular_path = _find_font(bold=False)
    def lf(bold, size):
        p = font_bold_path if bold else font_regular_path
        return ImageFont.truetype(p, size) if p else ImageFont.load_default()

    slides = []
    portada_url = data.get("foto_portada_url")
    fotos_extra = data.get("fotos_extra_urls", [])
    all_fotos = []
    if portada_url:
        all_fotos.append(portada_url)
    all_fotos.extend(fotos_extra)

    operacion = data.get("operacion", "Venta")
    precio = data.get("precio_formateado", "")
    tipo = data.get("tipo_propiedad", "")
    ubicacion = f"{data.get('direccion', '')}, {data.get('ciudad', '')}"
    if len(ubicacion) > 40:
        ubicacion = ubicacion[:37] + "..."

    specs = []
    if data.get("recamaras"): specs.append(("Recámaras", data["recamaras"]))
    if data.get("banos"): specs.append(("Baños", data["banos"]))
    if data.get("metros_construidos"): specs.append(("m² Const.", data["metros_construidos"]))
    if data.get("metros_terreno"): specs.append(("m² Terreno", data["metros_terreno"]))
    if data.get("estacionamientos"): specs.append(("Estac.", data["estacionamientos"]))

    amenidades = data.get("amenidades", [])
    agente = data.get("agente_nombre", "")
    telefono = data.get("agente_telefono", "")
    email = data.get("agente_email", "")
    descripcion = data.get("descripcion_profesional", "")

    def _load_bg(url):
        if url:
            fpath = url_to_filepath(url)
            if fpath.exists():
                img = _open_image(fpath, "RGBA")
                w, h = img.size
                side = min(w, h)
                left = (w - side) // 2
                top = (h - side) // 2
                img = img.crop((left, top, left + side, top + side))
                return img.resize((SIZE, SIZE), Image.LANCZOS)
        return Image.new("RGBA", (SIZE, SIZE), NAVY)

    def _add_gradient(img, top_a=150, bot_a=220):
        g = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        d = ImageDraw.Draw(g)
        for y in range(300):
            d.line([(0, y), (SIZE, y)], fill=(0, 0, 0, int(top_a * (1 - y / 300))))
        for y in range(SIZE):
            if y > SIZE - 450:
                p = (y - (SIZE - 450)) / 450
                d.line([(0, y), (SIZE, y)], fill=(0, 0, 0, int(bot_a * p)))
        return Image.alpha_composite(img, g)

    def _to_bytes(img):
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=95, optimize=True)
        buf.seek(0)
        return buf.getvalue()

    # ── SLIDE 1: Portada (foto + precio + badge) ──
    bg1 = _add_gradient(_load_bg(all_fotos[0] if all_fotos else None))
    o1 = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d1 = ImageDraw.Draw(o1)
    d1.rectangle([0, 0, SIZE, 8], fill=GOLD)
    # Badge
    f_badge = lf(True, 34)
    bt = f"  EN {operacion.upper()}  "
    bb = f_badge.getbbox(bt)
    d1.rounded_rectangle([50, 50, 50 + bb[2] - bb[0] + 40, 50 + bb[3] - bb[1] + 24], radius=8, fill=RED)
    d1.text((50 + 20, 50 + 10), bt, fill=WHITE, font=f_badge)
    # Logo
    logo_path = BASE_DIR / "static" / "img" / "logo-header.png"
    if logo_path.exists():
        logo = _open_image(logo_path, "RGBA")
        logo = logo.resize((int(50 * logo.width / logo.height), 50), Image.LANCZOS)
        o1.paste(logo, (SIZE - logo.width - 50, 45), logo)
    # Precio
    y = SIZE - 280
    d1.rectangle([50, y, SIZE - 50, y + 4], fill=GOLD)
    y += 25
    d1.text((50, y), precio, fill=WHITE, font=lf(True, 72))
    y += 95
    d1.text((50, y), ubicacion, fill=(255, 255, 255, 180), font=lf(False, 30))
    y += 50
    d1.text((50, y), "DESLIZA →", fill=GOLD, font=lf(True, 28))
    d1.rectangle([0, SIZE - 8, SIZE, SIZE], fill=GOLD)
    slides.append(_to_bytes(Image.alpha_composite(bg1, o1)))

    # ── SLIDE 2: Especificaciones ──
    bg2 = Image.new("RGBA", (SIZE, SIZE), NAVY_DARK)
    o2 = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(o2)
    d2.rectangle([0, 0, SIZE, 8], fill=GOLD)
    d2.text((50, 50), tipo.upper(), fill=GOLD, font=lf(True, 28))
    d2.text((50, 100), "ESPECIFICACIONES", fill=WHITE, font=lf(True, 40))
    d2.rectangle([50, 160, 200, 164], fill=GOLD)

    if specs:
        y2 = 210
        for label, value in specs:
            # Valor grande
            d2.text((50, y2), str(value), fill=GOLD, font=lf(True, 72))
            vw = lf(True, 72).getbbox(str(value))[2]
            d2.text((50 + vw + 15, y2 + 30), label, fill=(255, 255, 255, 180), font=lf(False, 30))
            y2 += 110
            d2.rectangle([50, y2 - 15, SIZE - 50, y2 - 13], fill=(255, 255, 255, 30))

    d2.rectangle([0, SIZE - 8, SIZE, SIZE], fill=GOLD)
    slides.append(_to_bytes(Image.alpha_composite(bg2, o2)))

    # ── SLIDES 3-5: Fotos extras con datos ──
    for idx in range(1, min(len(all_fotos), 4)):
        bg_n = _add_gradient(_load_bg(all_fotos[idx]), top_a=100, bot_a=180)
        on = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        dn = ImageDraw.Draw(on)
        dn.rectangle([0, 0, SIZE, 6], fill=GOLD)
        # Número de slide
        dn.text((50, 50), f"{idx + 1}/{min(len(all_fotos) + 2, 7)}", fill=GOLD, font=lf(True, 24))
        # Precio abajo
        dn.rectangle([50, SIZE - 130, SIZE - 50, SIZE - 127], fill=GOLD)
        dn.text((50, SIZE - 110), precio, fill=WHITE, font=lf(True, 48))
        dn.rectangle([0, SIZE - 6, SIZE, SIZE], fill=GOLD)
        slides.append(_to_bytes(Image.alpha_composite(bg_n, on)))

    # ── SLIDE: Amenidades (si hay) ──
    if amenidades:
        bg_am = Image.new("RGBA", (SIZE, SIZE), NAVY_DARK)
        oam = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        dam = ImageDraw.Draw(oam)
        dam.rectangle([0, 0, SIZE, 8], fill=GOLD)
        dam.text((50, 50), "AMENIDADES", fill=GOLD, font=lf(True, 40))
        dam.rectangle([50, 110, 200, 114], fill=GOLD)
        ya = 150
        f_am = lf(False, 30)
        for i, am in enumerate(amenidades[:12]):
            col = 0 if i % 2 == 0 else 1
            row_y = ya + (i // 2) * 65
            x_a = 70 + col * 480
            dam.ellipse([x_a - 20, row_y + 8, x_a - 6, row_y + 22], fill=GOLD)
            dam.text((x_a, row_y), am, fill=WHITE, font=f_am)
        dam.rectangle([0, SIZE - 8, SIZE, SIZE], fill=GOLD)
        slides.append(_to_bytes(Image.alpha_composite(bg_am, oam)))

    # ── SLIDE FINAL: Contacto ──
    bg_c = Image.new("RGBA", (SIZE, SIZE), NAVY)
    oc = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    dc = ImageDraw.Draw(oc)
    dc.rectangle([0, 0, SIZE, 8], fill=GOLD)
    dc.rectangle([0, SIZE - 8, SIZE, SIZE], fill=GOLD)

    # Logo centrado
    if logo_path.exists():
        logo_c = _open_image(logo_path, "RGBA")
        lch = 70
        logo_c = logo_c.resize((int(lch * logo_c.width / logo_c.height), lch), Image.LANCZOS)
        oc.paste(logo_c, ((SIZE - logo_c.width) // 2, 200), logo_c)

    yc = 340
    dc.rectangle([(SIZE - 250) // 2, yc, (SIZE + 250) // 2, yc + 3], fill=GOLD)
    yc += 30
    dc.text(((SIZE - lf(True, 24).getbbox("AGENDA TU VISITA")[2]) // 2, yc), "AGENDA TU VISITA", fill=GOLD, font=lf(True, 24))
    yc += 60

    # Nombre agente
    f_name = lf(True, 44)
    nw = f_name.getbbox(agente)[2] if agente else 0
    dc.text(((SIZE - nw) // 2, yc), agente, fill=WHITE, font=f_name)
    yc += 70

    # Teléfono
    f_ph = lf(True, 36)
    pw = f_ph.getbbox(telefono)[2] if telefono else 0
    dc.text(((SIZE - pw) // 2, yc), telefono, fill=GOLD, font=f_ph)
    yc += 60

    # Email
    f_em = lf(False, 26)
    ew = f_em.getbbox(email)[2] if email else 0
    dc.text(((SIZE - ew) // 2, yc), email, fill=(255, 255, 255, 150), font=f_em)
    yc += 80

    # CTA
    cta = "¡No dejes pasar esta oportunidad!"
    f_cta = lf(True, 28)
    cw = f_cta.getbbox(cta)[2]
    # Rectángulo rojo CTA
    dc.rounded_rectangle(
        [(SIZE - cw - 60) // 2, yc, (SIZE + cw + 60) // 2, yc + 58],
        radius=10, fill=RED,
    )
    dc.text(((SIZE - cw) // 2, yc + 14), cta, fill=WHITE, font=f_cta)

    slides.append(_to_bytes(Image.alpha_composite(bg_c, oc)))

    return slides


# ─── Rutas ───

# ─── Autenticacion ───

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user_id = get_session_user_id(request)
    if user_id:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    user = await authenticate_user(email, password)
    if not user:
        return templates.TemplateResponse(request=request, name="login.html", context={"error": "Email o contraseña incorrectos"})
    token = serializer.dumps(user["id"])
    # Referidos van directo a su dashboard de prospectos
    if user["rol"] == "referido":
        redirect_url = "/mis-prospectos"
    elif user["rol"] == "vendedor":
        redirect_url = "/mis-documentos"
    elif user["rol"] == "comprador":
        redirect_url = "/portal-comprador"
    else:
        redirect_url = "/"
    response = RedirectResponse(redirect_url, status_code=302)
    response.set_cookie("session", token, max_age=SESSION_MAX_AGE, httponly=True, samesite="lax", secure=True)
    return response


# ─── Recuperación de contraseña ───

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "iRealEstateMxPro")
N8N_WEBHOOK_NOTIFICACIONES = os.getenv("N8N_WEBHOOK_NOTIFICACIONES", "")
WAHA_API_URL = os.getenv("WAHA_API_URL", "https://wa.irealestatemx.cloud")
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "")
WAHA_SESSION = os.getenv("WAHA_SESSION", "default")


# ─── Mensajes de notificación por tipo ─────────────────────────────

NOTIF_MENSAJES = {
    "documento_subido": {
        "asunto": "Nuevo documento subido",
        "cuerpo": "Se ha subido el documento '{tipo_documento}' para la propiedad en {direccion}. Subido por: {cliente_nombre}.",
        "whatsapp": "Se subió el documento *{tipo_documento}* para la propiedad en _{direccion}_. Subido por: {cliente_nombre}.",
    },
    "documento_rechazado": {
        "asunto": "Documento rechazado — Acción requerida",
        "cuerpo": "Tu documento '{tipo_documento}' fue rechazado. Motivo: {notas}. Por favor sube una versión corregida.",
        "whatsapp": "Tu documento *{tipo_documento}* fue rechazado. Motivo: _{notas}_. Por favor sube una versión corregida.",
    },
    "documentos_completos": {
        "asunto": "Documentos completos — Listo para avanzar",
        "cuerpo": "Todos los documentos obligatorios han sido subidos para la propiedad en {direccion}. {vendedor_nombre} completó su expediente.",
        "whatsapp": "Todos los documentos obligatorios de *{vendedor_nombre}* están completos para la propiedad en _{direccion}_. Listo para avanzar al cierre.",
    },
    "cierre_fecha_notaria": {
        "asunto": "Fecha de escrituración programada",
        "cuerpo": "Se ha programado la fecha de escrituración para la propiedad en {direccion}.\n\n📅 Fecha: {fecha_escrituracion}\n🏛️ Notaría: {notaria_nombre}\n📍 Dirección notaría: {notaria_direccion}\n💰 Forma de pago: {forma_pago}\n💵 Monto total: ${monto_total}\n\n{desglose_gastos}\n\nPor favor confirma tu asistencia con tu agente.",
        "whatsapp": "📋 *FECHA DE ESCRITURACIÓN*\n\nPropiedad: _{direccion}_\n\n📅 *Fecha:* {fecha_escrituracion}\n🏛️ *Notaría:* {notaria_nombre}\n📍 *Dirección:* {notaria_direccion}\n💰 *Forma de pago:* {forma_pago}\n💵 *Monto total:* ${monto_total}\n\n{desglose_gastos}\n\n✅ Por favor confirma tu asistencia con tu agente.",
    },
    "cierre_gastos_vendedor": {
        "asunto": "Desglose de gastos de cierre — Vendedor",
        "cuerpo": "Se han calculado los gastos de cierre para la propiedad en {direccion}.\n\n{desglose_gastos}\n\n💰 Total a tu cargo: ${total_gastos}\n\nSi tienes dudas sobre algún concepto, contacta a tu agente.",
        "whatsapp": "💰 *GASTOS DE CIERRE — VENDEDOR*\n\nPropiedad: _{direccion}_\n\n{desglose_gastos}\n\n🔸 *Total a tu cargo: ${total_gastos}*\n\nSi tienes dudas, contacta a tu agente.",
    },
    "cierre_gastos_comprador": {
        "asunto": "Desglose de gastos de cierre — Comprador",
        "cuerpo": "Se han calculado los gastos de cierre para la propiedad en {direccion}.\n\n{desglose_gastos}\n\n💰 Total a tu cargo: ${total_gastos}\n\nSi tienes dudas sobre algún concepto, contacta a tu agente.",
        "whatsapp": "💰 *GASTOS DE CIERRE — COMPRADOR*\n\nPropiedad: _{direccion}_\n\n{desglose_gastos}\n\n🔸 *Total a tu cargo: ${total_gastos}*\n\nSi tienes dudas, contacta a tu agente.",
    },
    "lead_vendedor": {
        "asunto": "Nuevo lead de propietario — {nombre}",
        "cuerpo": "Nuevo propietario interesado en {operacion} su propiedad:\n\n👤 {nombre}\n📱 {telefono}\n📧 {email}\n🏠 {tipo_propiedad} en {ciudad}\n💬 {mensaje}",
        "whatsapp": "🏠 *Nuevo lead de propietario*\n\n👤 *{nombre}*\n📱 {telefono}\n📧 {email}\n🔑 {operacion} — {tipo_propiedad}\n📍 {ciudad}\n💬 {mensaje}\n\n👉 https://irealestatemx.com/admin/prospectos",
    },
}


def _construir_desglose_gastos(gastos_dict: dict, labels_list: list, modo: str = "whatsapp") -> str:
    """Construye texto de desglose de gastos para notificaciones.
    modo='whatsapp' usa formato con asteriscos, modo='email' usa texto plano."""
    lineas = []
    for item in labels_list:
        clave = item["clave"]
        valor = gastos_dict.get(clave)
        if valor and str(valor).strip():
            try:
                monto = float(str(valor).replace(",", ""))
                if monto > 0:
                    if modo == "whatsapp":
                        lineas.append(f"  • {item['label']}: *${monto:,.2f}*")
                    else:
                        lineas.append(f"  • {item['label']}: ${monto:,.2f}")
            except (ValueError, TypeError):
                pass
    return "\n".join(lineas) if lineas else "Sin gastos registrados aún."


def _generar_mensajes_cierre_fecha(prop: dict, datos: dict, cierre_data: dict) -> dict:
    """Genera mensajes predeterminados de fecha de escrituración para que el agente envíe por WhatsApp."""
    direccion = prop.get("direccion", "Sin dirección")
    gastos = cierre_data.get("gastos", {})
    mensajes = {}

    vendedor_id = prop.get("vendedor_id")
    if vendedor_id:
        desglose = _construir_desglose_gastos(gastos.get("vendedor", {}), GASTOS_VENDEDOR, "whatsapp")
        mensajes["vendedor"] = {
            "user_id": vendedor_id,
            "mensaje": (
                f"Hola, le informamos que se ha programado la fecha de escrituración "
                f"para la propiedad en *{direccion}*.\n\n"
                f"📅 *Fecha:* {datos.get('fecha_escrituracion', 'Por definir')}\n"
                f"🏛️ *Notaría:* {datos.get('notaria_nombre', 'Por definir')}\n"
                f"📍 *Dirección:* {datos.get('notaria_direccion', 'Por definir')}\n"
                f"💰 *Forma de pago:* {datos.get('forma_pago', 'Por definir')}\n"
                f"💵 *Monto total:* ${datos.get('monto_total', 'Por definir')}\n\n"
                f"📝 *Tus gastos como vendedor:*\n{desglose}\n\n"
                f"Por favor confirma tu asistencia. Quedo al pendiente."
            ),
        }

    comprador_id = prop.get("comprador_id")
    if comprador_id:
        desglose = _construir_desglose_gastos(gastos.get("comprador", {}), GASTOS_COMPRADOR, "whatsapp")
        mensajes["comprador"] = {
            "user_id": comprador_id,
            "mensaje": (
                f"Hola, le informamos que se ha programado la fecha de escrituración "
                f"para la propiedad en *{direccion}*.\n\n"
                f"📅 *Fecha:* {datos.get('fecha_escrituracion', 'Por definir')}\n"
                f"🏛️ *Notaría:* {datos.get('notaria_nombre', 'Por definir')}\n"
                f"📍 *Dirección:* {datos.get('notaria_direccion', 'Por definir')}\n"
                f"💰 *Forma de pago:* {datos.get('forma_pago', 'Por definir')}\n"
                f"💵 *Monto total:* ${datos.get('monto_total', 'Por definir')}\n\n"
                f"📝 *Tus gastos como comprador:*\n{desglose}\n\n"
                f"Por favor confirma tu asistencia. Quedo al pendiente."
            ),
        }
    return mensajes


def _generar_mensajes_gastos(prop: dict, gastos: dict) -> dict:
    """Genera mensajes predeterminados de gastos para que el agente envíe por WhatsApp."""
    direccion = prop.get("direccion", "Sin dirección")
    mensajes = {}

    vendedor_id = prop.get("vendedor_id")
    total_vend = gastos.get("total_vendedor", 0)
    if vendedor_id and total_vend and float(total_vend) > 0:
        desglose = _construir_desglose_gastos(gastos.get("vendedor", {}), GASTOS_VENDEDOR, "whatsapp")
        mensajes["vendedor"] = {
            "user_id": vendedor_id,
            "mensaje": (
                f"Hola, le comparto el desglose de gastos de cierre para la "
                f"propiedad en *{direccion}*.\n\n"
                f"📝 *Gastos a tu cargo como vendedor:*\n{desglose}\n\n"
                f"🔸 *Total: ${float(total_vend):,.2f}*\n\n"
                f"Si tienes alguna duda sobre algún concepto, quedo al pendiente."
            ),
        }

    comprador_id = prop.get("comprador_id")
    total_comp = gastos.get("total_comprador", 0)
    if comprador_id and total_comp and float(total_comp) > 0:
        desglose = _construir_desglose_gastos(gastos.get("comprador", {}), GASTOS_COMPRADOR, "whatsapp")
        mensajes["comprador"] = {
            "user_id": comprador_id,
            "mensaje": (
                f"Hola, le comparto el desglose de gastos de cierre para la "
                f"propiedad en *{direccion}*.\n\n"
                f"📝 *Gastos a tu cargo como comprador:*\n{desglose}\n\n"
                f"🔸 *Total: ${float(total_comp):,.2f}*\n\n"
                f"Si tienes alguna duda sobre algún concepto, quedo al pendiente."
            ),
        }
    return mensajes


async def _enviar_emails_cierre_fecha(prop: dict, datos: dict):
    """Envía emails automáticos de fecha de escrituración (no WhatsApp)."""
    import asyncio
    direccion = prop.get("direccion", "Sin dirección")
    cierre_data = prop.get("cierre_data") or {}
    gastos = cierre_data.get("gastos", {})
    plantilla = NOTIF_MENSAJES["cierre_fecha_notaria"]

    for rol, user_id_key, gastos_key, labels in [
        ("vendedor", "vendedor_id", "vendedor", GASTOS_VENDEDOR),
        ("comprador", "comprador_id", "comprador", GASTOS_COMPRADOR),
    ]:
        uid = prop.get(user_id_key)
        if not uid:
            continue
        user = await get_user_by_id(uid)
        if not user:
            continue
        desglose = _construir_desglose_gastos(gastos.get(gastos_key, {}), labels, "email")
        meta = {
            "direccion": direccion,
            "fecha_escrituracion": datos.get("fecha_escrituracion", "Por definir"),
            "notaria_nombre": datos.get("notaria_nombre", "Por definir"),
            "notaria_direccion": datos.get("notaria_direccion", "Por definir"),
            "forma_pago": datos.get("forma_pago", "Por definir"),
            "monto_total": datos.get("monto_total", "Por definir"),
            "desglose_gastos": f"Tus gastos como {rol}:\n{desglose}",
        }
        cuerpo = plantilla["cuerpo"]
        try:
            cuerpo = cuerpo.format(**meta)
        except KeyError:
            pass
        asyncio.create_task(enviar_email_notificacion(user["email"], user["nombre"], plantilla["asunto"], cuerpo))


async def _enviar_emails_gastos(prop: dict, gastos: dict):
    """Envía emails automáticos de gastos de cierre (no WhatsApp)."""
    import asyncio
    direccion = prop.get("direccion", "Sin dirección")

    for rol, user_id_key, gastos_key, labels, tipo in [
        ("vendedor", "vendedor_id", "vendedor", GASTOS_VENDEDOR, "cierre_gastos_vendedor"),
        ("comprador", "comprador_id", "comprador", GASTOS_COMPRADOR, "cierre_gastos_comprador"),
    ]:
        uid = prop.get(user_id_key)
        total = gastos.get(f"total_{rol}", 0)
        if not uid or not total or float(total) <= 0:
            continue
        user = await get_user_by_id(uid)
        if not user:
            continue
        desglose = _construir_desglose_gastos(gastos.get(gastos_key, {}), labels, "email")
        plantilla = NOTIF_MENSAJES[tipo]
        meta = {
            "direccion": direccion,
            "desglose_gastos": desglose,
            "total_gastos": f"{float(total):,.2f}",
        }
        cuerpo = plantilla["cuerpo"]
        try:
            cuerpo = cuerpo.format(**meta)
        except KeyError:
            pass
        asyncio.create_task(enviar_email_notificacion(user["email"], user["nombre"], plantilla["asunto"], cuerpo))


async def enviar_email_notificacion(to_email: str, to_name: str, asunto: str, cuerpo: str):
    """Envía un email de notificación usando SMTP (reutiliza config existente)."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"[EMAIL-NOTIF] SMTP no configurado. Asunto: {asunto}")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = to_email
    msg["Subject"] = f"{asunto} — iRealEstateMxPro"

    html = f"""
    <div style="font-family:'Inter',Arial,sans-serif;max-width:500px;margin:0 auto;padding:40px 20px;">
      <div style="text-align:center;margin-bottom:30px;">
        <h1 style="color:#1a3c5e;font-size:22px;margin:0;">iRealEstateMxPro</h1>
      </div>
      <div style="background:#fff;border-radius:12px;padding:32px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
        <h2 style="color:#1a3c5e;font-size:18px;margin-top:0;">Hola {to_name},</h2>
        <p style="color:#4a5568;font-size:14px;line-height:1.6;">{cuerpo}</p>
        <div style="text-align:center;margin:28px 0;">
          <a href="{APP_URL}"
             style="background:linear-gradient(135deg,#c9a227,#d4af37);color:#1a3c5e;
                    padding:14px 32px;border-radius:10px;text-decoration:none;
                    font-weight:700;font-size:15px;display:inline-block;">
            Ir a la plataforma
          </a>
        </div>
      </div>
      <p style="text-align:center;color:#a0aec0;font-size:11px;margin-top:20px;">
        iRealEstateMxPro &copy; 2026
      </p>
    </div>
    """
    msg.attach(MIMEText(html, "html"))

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, to_email, msg.as_string())
        server.quit()
        print(f"[EMAIL-NOTIF] Enviado a {to_email}: {asunto}")
        return True
    except Exception as e:
        print(f"[EMAIL-NOTIF] Error: {e}")
        return False


def _formatear_telefono_mx(telefono: str) -> str:
    """Formatea teléfono mexicano para WAHA: 521XXXXXXXXXX@c.us"""
    tel = "".join(c for c in str(telefono) if c.isdigit())
    # Si ya tiene código de país 52
    if tel.startswith("52") and len(tel) >= 12:
        return f"{tel}@c.us"
    # Si tiene 10 dígitos (número mexicano sin código)
    if len(tel) == 10:
        return f"52{tel}@c.us"
    # Si tiene 1+10 dígitos (con 1 de larga distancia viejo)
    if len(tel) == 11 and tel.startswith("1"):
        return f"52{tel[1:]}@c.us"
    # Fallback: asumir que es válido
    return f"{tel}@c.us"


async def enviar_whatsapp_waha(tipo: str, destinatario: dict, metadata: dict):
    """Envía WhatsApp directo vía WAHA (WhatsApp HTTP API)."""
    import httpx

    if not WAHA_API_URL or not WAHA_API_KEY:
        print(f"[WAHA] No configurado. Tipo: {tipo}")
        return False

    # Construir mensaje desde plantilla
    plantilla = NOTIF_MENSAJES.get(tipo, {})
    mensaje = plantilla.get("whatsapp", "")
    if mensaje:
        try:
            mensaje = mensaje.format(**metadata)
        except KeyError as e:
            print(f"[WAHA] Error formateando mensaje {tipo}: {e}")

    if not mensaje:
        print(f"[WAHA] Sin mensaje para tipo: {tipo}")
        return False

    telefono = destinatario.get("telefono", "")
    if not telefono:
        print(f"[WAHA] Usuario {destinatario.get('nombre', '')} sin teléfono. Tipo: {tipo}")
        return False

    chat_id = _formatear_telefono_mx(telefono)

    payload = {
        "chatId": chat_id,
        "text": mensaje,
        "session": WAHA_SESSION,
    }

    headers = {
        "X-Api-Key": WAHA_API_KEY,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{WAHA_API_URL}/api/sendText",
                json=payload,
                headers=headers,
            )
            if resp.status_code < 400:
                print(f"[WAHA] ✓ Enviado a {chat_id} ({destinatario.get('nombre', '')}). Tipo: {tipo}")
                return True
            else:
                print(f"[WAHA] Error {resp.status_code}: {resp.text[:200]}")
                return False
    except Exception as e:
        print(f"[WAHA] Error conexión: {e}")
        return False


# Alias para compatibilidad con código existente
enviar_whatsapp_n8n = enviar_whatsapp_waha


async def disparar_notificaciones(tipo: str, user_id: int, propiedad_id: int, metadata: dict):
    """Envía email + WhatsApp al usuario. Se llama después de crear_notificacion()."""
    user = await get_user_by_id(user_id)
    if not user:
        return

    prop = await get_property_by_id(propiedad_id)
    direccion = prop.get("direccion", "") if prop else ""
    meta_con_dir = {**metadata, "direccion": direccion}

    plantilla = NOTIF_MENSAJES.get(tipo, {})
    asunto = plantilla.get("asunto", "Notificación")
    cuerpo = plantilla.get("cuerpo", "")
    if cuerpo:
        try:
            cuerpo = cuerpo.format(**meta_con_dir)
        except KeyError:
            pass

    # Email automático (en background para no bloquear la respuesta)
    import asyncio
    asyncio.create_task(enviar_email_notificacion(user["email"], user["nombre"], asunto, cuerpo))

    # WhatsApp: ya no se envía automático, el agente lo manda desde el dashboard
APP_URL = os.getenv("APP_URL", "https://irealestatemx.com")


def _send_reset_email(to_email: str, to_name: str, reset_link: str):
    """Envía email de recuperación de contraseña."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"[EMAIL] SMTP no configurado. Link de reset: {reset_link}")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = to_email
    msg["Subject"] = "Recupera tu contraseña — iRealEstateMxPro"

    html = f"""
    <div style="font-family:'Inter',Arial,sans-serif;max-width:500px;margin:0 auto;padding:40px 20px;">
      <div style="text-align:center;margin-bottom:30px;">
        <h1 style="color:#1a3c5e;font-size:22px;margin:0;">iRealEstateMxPro</h1>
      </div>
      <div style="background:#fff;border-radius:12px;padding:32px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
        <h2 style="color:#1a3c5e;font-size:18px;margin-top:0;">Hola {to_name},</h2>
        <p style="color:#4a5568;font-size:14px;line-height:1.6;">
          Recibimos una solicitud para restablecer tu contraseña. Haz clic en el botón de abajo para crear una nueva.
        </p>
        <div style="text-align:center;margin:28px 0;">
          <a href="{reset_link}"
             style="background:linear-gradient(135deg,#c9a227,#d4af37);color:#1a3c5e;
                    padding:14px 32px;border-radius:10px;text-decoration:none;
                    font-weight:700;font-size:15px;display:inline-block;">
            Restablecer contraseña
          </a>
        </div>
        <p style="color:#7a8a9e;font-size:12px;line-height:1.5;">
          Este enlace expira en <strong>1 hora</strong>. Si no solicitaste este cambio, ignora este correo.
        </p>
        <hr style="border:none;border-top:1px solid #e2e8f0;margin:20px 0;" />
        <p style="color:#a0aec0;font-size:11px;">
          Si el botón no funciona, copia y pega este enlace en tu navegador:<br />
          <a href="{reset_link}" style="color:#c9a227;word-break:break-all;">{reset_link}</a>
        </p>
      </div>
      <p style="text-align:center;color:#a0aec0;font-size:11px;margin-top:20px;">
        iRealEstateMxPro &copy; 2026
      </p>
    </div>
    """

    msg.attach(MIMEText(html, "html"))

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, to_email, msg.as_string())
        server.quit()
        print(f"[EMAIL] Enviado reset a {to_email}")
        return True
    except Exception as e:
        print(f"[EMAIL] Error: {e}")
        return False


@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse(request=request, name="forgot_password.html", context={"message": None, "error": None})


@app.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password_submit(request: Request, email: str = Form(...)):
    user = await get_user_by_email(email)
    if user:
        # Generar token con el ID del usuario (expira en 1 hora)
        reset_token = serializer.dumps(user["id"], salt="password-reset")
        reset_link = f"{APP_URL}/reset-password?token={reset_token}"
        _send_reset_email(user["email"], user["nombre"], reset_link)

    # Siempre mostrar el mismo mensaje (no revelar si el email existe o no)
    return templates.TemplateResponse(request=request, name="forgot_password.html", context={
        "message": "Si el email existe en nuestro sistema, recibirás un correo con instrucciones para restablecer tu contraseña.",
        "error": None,
    })


@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    token = request.query_params.get("token", "")
    if not token:
        return RedirectResponse("/login", status_code=302)
    # Validar que el token sea válido (sin expirar aún)
    try:
        user_id = serializer.loads(token, salt="password-reset", max_age=3600)
    except (BadSignature, SignatureExpired):
        return templates.TemplateResponse(request=request, name="reset_password.html", context={
            "error": "El enlace ha expirado o no es válido. Solicita uno nuevo.",
            "token": "",
            "success": False,
        })
    return templates.TemplateResponse(request=request, name="reset_password.html", context={
        "error": None,
        "token": token,
        "success": False,
    })


@app.post("/reset-password", response_class=HTMLResponse)
async def reset_password_submit(request: Request, token: str = Form(...), password: str = Form(...), password2: str = Form(...)):
    # Validar token
    try:
        user_id = serializer.loads(token, salt="password-reset", max_age=3600)
    except (BadSignature, SignatureExpired):
        return templates.TemplateResponse(request=request, name="reset_password.html", context={
            "error": "El enlace ha expirado o no es válido. Solicita uno nuevo.",
            "token": "",
            "success": False,
        })

    # Validar contraseñas
    if password != password2:
        return templates.TemplateResponse(request=request, name="reset_password.html", context={
            "error": "Las contraseñas no coinciden.",
            "token": token,
            "success": False,
        })

    if len(password) < 6:
        return templates.TemplateResponse(request=request, name="reset_password.html", context={
            "error": "La contraseña debe tener al menos 6 caracteres.",
            "token": token,
            "success": False,
        })

    # Actualizar contraseña
    await update_user(user_id, {"password": password})
    return templates.TemplateResponse(request=request, name="reset_password.html", context={
        "error": None,
        "token": "",
        "success": True,
    })


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("session")
    return response


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = await require_auth(request)
    if not user:
        # Visitante no autenticado → web pública
        props = await get_all_properties(active_only=True, limit=12, offset=0, publicada_web=True)
        desarrollos_list = list(DESARROLLOS_DATA.values())
        c = await load_public_config()
        return templates.TemplateResponse(request=request, name="public_home.html", context={
            "propiedades": props,
            "desarrollos": desarrollos_list,
            "desarrollos_dict": DESARROLLOS_DATA,
            "c": c,
        })
    # Vendedor/comprador no pueden subir propiedades — redirigir a su flujo
    if user["rol"] == "vendedor":
        return RedirectResponse("/mis-documentos", status_code=302)
    if user["rol"] == "comprador":
        return RedirectResponse("/portal-comprador", status_code=302)
    if user["rol"] == "referido":
        return RedirectResponse("/mis-prospectos", status_code=302)
    return templates.TemplateResponse(request=request, name="wizard.html", context={
        "user": user,
        "desarrollos_dict": DESARROLLOS_DATA,
    })


# ─── Panel de Usuarios (solo admin) ───

@app.get("/admin/usuarios", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    users = await get_all_users()
    # Credenciales del usuario recién creado (si las hay en el query string)
    params = request.query_params
    context = {"user": user, "users": users}
    if params.get("created") == "1":
        context.update({
            "created": True,
            "c_nombre": params.get("c_nombre", ""),
            "c_email": params.get("c_email", ""),
            "c_password": params.get("c_password", ""),
            "c_rol": params.get("c_rol", ""),
            "c_prefijo": params.get("c_prefijo", ""),
        })
    return templates.TemplateResponse(request=request, name="admin_users.html", context=context)


@app.post("/admin/usuarios/crear")
async def admin_create_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    nombre: str = Form(...),
    rol: str = Form("agente"),
    prefijo_whatsapp: str = Form(""),
    telefono: str = Form(""),
):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    error_msg = ""
    try:
        user_id = await create_user(email, password, nombre, rol)
        updates = {}
        if prefijo_whatsapp.strip():
            updates["prefijo_whatsapp"] = prefijo_whatsapp.strip().upper()
        if telefono.strip():
            updates["telefono"] = telefono.strip()
        if updates:
            await update_user(user_id, updates)
        # Redirigir sin exponer contraseña en URL
        from urllib.parse import urlencode
        params = urlencode({
            "created": "1",
            "c_nombre": nombre,
            "c_email": email,
            "c_rol": rol,
            "c_prefijo": prefijo_whatsapp.strip().upper(),
        })
        return RedirectResponse(f"/admin/usuarios?{params}", status_code=302)
    except Exception as e:
        print(f"[AUTH] Error creando usuario: {e}")
    return RedirectResponse("/admin/usuarios", status_code=302)


@app.get("/admin/usuarios/{user_id}/editar", response_class=HTMLResponse)
async def admin_edit_user_page(request: Request, user_id: int):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    target = await get_user_by_id(user_id)
    if not target:
        return RedirectResponse("/admin/usuarios", status_code=302)
    all_users = await get_all_users()
    return templates.TemplateResponse(request=request, name="admin_users.html", context={
        "user": user,
        "users": all_users,
        "edit_user": target,
    })


@app.post("/admin/usuarios/{user_id}/editar")
async def admin_edit_user_submit(
    request: Request,
    user_id: int,
    nombre: str = Form(...),
    email: str = Form(...),
    rol: str = Form("agente"),
    prefijo_whatsapp: str = Form(""),
    telefono: str = Form(""),
    password: str = Form(""),
):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    target = await get_user_by_id(user_id)
    if not target:
        return RedirectResponse("/admin/usuarios", status_code=302)

    updates = {
        "nombre": nombre,
        "email": email,
        "rol": rol,
        "prefijo_whatsapp": prefijo_whatsapp.strip().upper() or None,
        "telefono": telefono.strip() or None,
    }
    if password.strip():
        updates["password"] = password.strip()

    try:
        await update_user(user_id, updates)
    except Exception as e:
        print(f"[ADMIN] Error editando usuario {user_id}: {e}")

    return RedirectResponse("/admin/usuarios", status_code=302)


@app.post("/admin/usuarios/{user_id}/toggle")
async def admin_toggle_user(request: Request, user_id: int):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    target = await get_user_by_id(user_id)
    if target and target["id"] != user["id"]:
        await update_user(user_id, {"activo": not target["activo"]})
    return RedirectResponse("/admin/usuarios", status_code=302)


@app.post("/admin/usuarios/{user_id}/eliminar")
async def admin_delete_user(request: Request, user_id: int):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    target = await get_user_by_id(user_id)
    if target and target["id"] != user["id"]:
        await delete_user_permanent(user_id)
    return RedirectResponse("/admin/usuarios", status_code=302)


# ─── Dashboard de Propiedades ───

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, agente: Optional[str] = None):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    # Convertir agente a int (puede venir vacio)
    agente_id = int(agente) if agente and agente.isdigit() else None

    # Admin ve todas, agente solo las suyas
    if user["rol"] == "admin":
        if agente_id:
            props = await get_properties_by_user(agente_id)
        else:
            props = await get_all_properties(active_only=False, limit=100, include_vendidas=True)
        all_users = await get_all_users()
        agents = [u for u in all_users if u["rol"] in ("agente", "admin")]
    else:
        props = await get_properties_by_user(user["id"])
        agents = []

    # Serializar campos especiales
    for p in props:
        for k, v in p.items():
            if hasattr(v, 'isoformat'):
                p[k] = v.isoformat()
            elif not isinstance(v, (int, float, str, bool, list, dict, type(None))):
                p[k] = str(v)

    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "user": user,
        "propiedades": props,
        "agents": agents,
        "selected_agent": agente_id,
    })


@app.get("/dashboard/editar/{prop_id}", response_class=HTMLResponse)
async def edit_property_page(request: Request, prop_id: int):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    prop = await get_property_by_id(prop_id)
    if not prop:
        return RedirectResponse("/dashboard", status_code=302)

    # Solo el dueño o admin puede editar
    if user["rol"] != "admin" and prop.get("user_id") != user["id"]:
        return RedirectResponse("/dashboard", status_code=302)

    vendedores = await get_users_by_rol("vendedor")
    compradores = await get_users_by_rol("comprador")
    # Admin/agente también pueden asignarse como vendedor o comprador
    agentes_admins = await get_users_by_rol("agente") + await get_users_by_rol("admin")

    return templates.TemplateResponse(request=request, name="edit_property.html", context={
        "user": user,
        "prop": prop,
        "vendedores": vendedores + agentes_admins,
        "compradores": compradores + agentes_admins,
        "desarrollos_dict": DESARROLLOS_DATA,
    })


@app.post("/dashboard/editar/{prop_id}")
async def edit_property_submit(
    request: Request,
    prop_id: int,
    tipo_propiedad: str = Form(""),
    operacion: str = Form(""),
    direccion: str = Form(""),
    ciudad: str = Form(""),
    estado: str = Form(""),
    precio_formateado: str = Form(""),
    recamaras: Optional[str] = Form(None),
    banos: Optional[str] = Form(None),
    metros_construidos: Optional[str] = Form(None),
    metros_terreno: Optional[str] = Form(None),
    estacionamientos: Optional[str] = Form(None),
    agente_nombre: str = Form(""),
    agente_telefono: str = Form(""),
    agente_email: str = Form(""),
    desarrollo_slug: Optional[str] = Form(None),
):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    prop = await get_property_by_id(prop_id)
    if not prop:
        return RedirectResponse("/dashboard", status_code=302)
    if user["rol"] != "admin" and prop.get("user_id") != user["id"]:
        return RedirectResponse("/dashboard", status_code=302)

    updates = {
        "tipo_propiedad": tipo_propiedad,
        "operacion": operacion,
        "direccion": direccion,
        "ciudad": ciudad,
        "estado": estado,
        "precio_formateado": precio_formateado,
        "recamaras": recamaras,
        "banos": banos,
        "metros_construidos": metros_construidos,
        "metros_terreno": metros_terreno,
        "estacionamientos": estacionamientos,
        "agente_nombre": agente_nombre,
        "agente_telefono": agente_telefono,
        "agente_email": agente_email,
        "desarrollo_slug": desarrollo_slug or None,
    }
    # Si cambian operación a "Vendida", marcar como vendida
    if operacion == "Vendida":
        from datetime import datetime as _dt
        updates["vendida"] = True
        if not prop.get("fecha_venta"):
            updates["fecha_venta"] = _dt.now()
    elif prop.get("vendida") and operacion != "Vendida":
        # Si cambian de Vendida a otra operación, desmarcar
        updates["vendida"] = False

    await update_property(prop_id, updates)
    return RedirectResponse("/dashboard", status_code=302)


# ─── Gestión de fotos de propiedad ───

@app.post("/dashboard/editar/{prop_id}/fotos")
async def edit_property_photos(request: Request, prop_id: int):
    """Maneja agregar, eliminar, reordenar fotos y cambiar portada."""
    user = await require_auth(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    prop = await get_property_by_id(prop_id)
    if not prop:
        return JSONResponse({"error": "Propiedad no encontrada"}, status_code=404)
    if user["rol"] != "admin" and prop.get("user_id") != user["id"]:
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    form = await request.form()
    action = form.get("action", "")

    if action == "delete":
        # Eliminar una foto
        foto_url = form.get("foto_url", "")
        extras = list(prop.get("fotos_extra_urls") or [])
        updates = {}
        if foto_url == prop.get("foto_portada_url"):
            # Si eliminan la portada, poner la primera extra como portada
            updates["foto_portada_url"] = extras[0] if extras else ""
            if extras:
                extras.pop(0)
            updates["fotos_extra_urls"] = json.dumps(extras)
        elif foto_url in extras:
            extras.remove(foto_url)
            updates["fotos_extra_urls"] = json.dumps(extras)
        if updates:
            await update_property(prop_id, updates)
        # Eliminar archivo físico
        try:
            file_path = BASE_DIR / foto_url.lstrip("/")
            if file_path.exists():
                file_path.unlink()
        except Exception:
            pass
        return RedirectResponse(f"/dashboard/editar/{prop_id}", status_code=302)

    elif action == "set_cover":
        # Cambiar foto de portada
        foto_url = form.get("foto_url", "")
        extras = list(prop.get("fotos_extra_urls") or [])
        old_cover = prop.get("foto_portada_url", "")
        if foto_url in extras:
            extras.remove(foto_url)
            if old_cover:
                extras.insert(0, old_cover)
            await update_property(prop_id, {
                "foto_portada_url": foto_url,
                "fotos_extra_urls": json.dumps(extras),
            })
        return RedirectResponse(f"/dashboard/editar/{prop_id}", status_code=302)

    elif action == "upload":
        # Subir nuevas fotos
        files = form.getlist("nuevas_fotos")
        if not files:
            return RedirectResponse(f"/dashboard/editar/{prop_id}", status_code=302)

        session_id = prop.get("session_id", uuid.uuid4().hex)
        photo_dir = UPLOAD_DIR / session_id
        photo_dir.mkdir(parents=True, exist_ok=True)

        extras = list(prop.get("fotos_extra_urls") or [])
        current_cover = prop.get("foto_portada_url", "")

        for f in files:
            if not hasattr(f, 'filename') or not f.filename:
                continue
            ext = Path(f.filename).suffix.lower()
            if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
                continue
            # Validar MIME
            if f.content_type and f.content_type not in ["image/jpeg", "image/png", "image/webp"]:
                continue
            fname = f"{uuid.uuid4().hex[:8]}{ext}"
            dest = photo_dir / fname
            content = await f.read()
            if len(content) > 10 * 1024 * 1024:  # 10MB max por foto
                continue
            with open(dest, "wb") as buf:
                buf.write(content)
            url = f"/static/uploads/{session_id}/{fname}"
            if not current_cover:
                current_cover = url
            else:
                extras.append(url)

        updates = {"fotos_extra_urls": json.dumps(extras)}
        if current_cover != prop.get("foto_portada_url"):
            updates["foto_portada_url"] = current_cover
        await update_property(prop_id, updates)
        return RedirectResponse(f"/dashboard/editar/{prop_id}", status_code=302)

    elif action == "reorder":
        # Reordenar fotos (recibe JSON con el nuevo orden)
        order_json = form.get("order", "[]")
        try:
            new_order = json.loads(order_json)
        except json.JSONDecodeError:
            new_order = []
        if new_order:
            await update_property(prop_id, {
                "foto_portada_url": new_order[0],
                "fotos_extra_urls": json.dumps(new_order[1:]),
            })
        return RedirectResponse(f"/dashboard/editar/{prop_id}", status_code=302)

    return RedirectResponse(f"/dashboard/editar/{prop_id}", status_code=302)


@app.post("/dashboard/editar/{prop_id}/asignar")
async def asignar_vendedor_comprador(
    request: Request,
    prop_id: int,
    vendedor_id: Optional[str] = Form(None),
    comprador_id: Optional[str] = Form(None),
):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    prop = await get_property_by_id(prop_id)
    if not prop:
        return RedirectResponse("/dashboard", status_code=302)

    # Seguridad: solo el dueño de la propiedad o admin
    if user["rol"] != "admin" and prop.get("user_id") != user["id"]:
        return RedirectResponse("/dashboard", status_code=302)

    updates = {}
    if vendedor_id is not None:
        updates["vendedor_id"] = int(vendedor_id) if vendedor_id else None
    if comprador_id is not None:
        updates["comprador_id"] = int(comprador_id) if comprador_id else None

    if updates:
        await update_property(prop_id, updates)

    return RedirectResponse(f"/dashboard/editar/{prop_id}", status_code=302)


@app.post("/dashboard/asignarme/{prop_id}/{rol}")
async def asignarme_propiedad(request: Request, prop_id: int, rol: str):
    """Quick self-assign: agente/admin se asigna como vendedor o comprador."""
    user = await require_auth(request)
    if not user or user["rol"] not in ("admin", "agente"):
        return RedirectResponse("/login", status_code=302)
    if rol not in ("vendedor", "comprador"):
        return RedirectResponse("/dashboard", status_code=302)

    prop = await get_property_by_id(prop_id)
    if not prop:
        return RedirectResponse("/dashboard", status_code=302)
    # Solo el dueño o admin
    if user["rol"] != "admin" and prop.get("user_id") != user["id"]:
        return RedirectResponse("/dashboard", status_code=302)

    field = "vendedor_id" if rol == "vendedor" else "comprador_id"
    await update_property(prop_id, {field: user["id"]})
    return RedirectResponse("/dashboard", status_code=302)


@app.post("/dashboard/toggle/{prop_id}")
async def dashboard_toggle(request: Request, prop_id: int):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    prop = await get_property_by_id(prop_id)
    if not prop:
        return RedirectResponse("/dashboard", status_code=302)
    if user["rol"] != "admin" and prop.get("user_id") != user["id"]:
        return RedirectResponse("/dashboard", status_code=302)
    await toggle_property(prop_id, not prop["activa"])
    return RedirectResponse("/dashboard", status_code=302)


@app.post("/dashboard/toggle-web/{prop_id}")
async def dashboard_toggle_web(request: Request, prop_id: int):
    """Toggle publicada_web para mostrar/ocultar en la web pública."""
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    prop = await get_property_by_id(prop_id)
    if not prop:
        return RedirectResponse("/dashboard", status_code=302)
    if user["rol"] != "admin" and prop.get("user_id") != user["id"]:
        return RedirectResponse("/dashboard", status_code=302)
    await update_property(prop_id, {"publicada_web": not prop.get("publicada_web", False)})
    return RedirectResponse("/dashboard", status_code=302)


@app.post("/dashboard/eliminar/{prop_id}")
async def dashboard_delete(request: Request, prop_id: int):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    prop = await get_property_by_id(prop_id)
    if not prop:
        return RedirectResponse("/dashboard", status_code=302)
    if user["rol"] != "admin" and prop.get("user_id") != user["id"]:
        return RedirectResponse("/dashboard", status_code=302)
    # Eliminar permanentemente
    from database import database as db
    await db.execute("DELETE FROM propiedades WHERE id = :id", values={"id": prop_id})
    return RedirectResponse("/dashboard", status_code=302)


# ─── Documentos ───

VALID_DOC_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".doc", ".docx"}
VALID_CATEGORIAS = {"vendedor", "comprador", "agente", "notaria"}

@app.post("/api/documentos/subir")
async def subir_documento(
    request: Request,
    propiedad_id: int = Form(...),
    tipo_documento: str = Form(...),
    categoria: str = Form(...),
    archivo: UploadFile = File(...),
    notas: Optional[str] = Form(None),
):
    user = await require_auth(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)

    # Validar que la propiedad existe
    prop = await get_property_by_id(propiedad_id)
    if not prop:
        return JSONResponse({"error": "Propiedad no encontrada"}, status_code=404)

    # Validar permisos: dueño, vendedor asignado, agente, o admin
    rol = user["rol"]
    es_dueño = prop.get("user_id") == user["id"]
    es_vendedor_asignado = prop.get("vendedor_id") == user["id"]
    es_comprador_asignado = prop.get("comprador_id") == user["id"]
    if rol not in ("admin", "agente") and not es_dueño and not es_vendedor_asignado and not es_comprador_asignado:
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    # Validar categoría
    if categoria not in VALID_CATEGORIAS:
        return JSONResponse({"error": f"Categoría inválida. Opciones: {', '.join(VALID_CATEGORIAS)}"}, status_code=400)

    # Validar que la categoría coincida con el rol del usuario
    if rol == "vendedor" and categoria != "vendedor":
        return JSONResponse({"error": "Solo puedes subir documentos de categoría 'vendedor'"}, status_code=403)
    if rol == "comprador" and categoria != "comprador":
        return JSONResponse({"error": "Solo puedes subir documentos de categoría 'comprador'"}, status_code=403)

    # Validar extensión del archivo
    ext = Path(archivo.filename).suffix.lower()
    if ext not in VALID_DOC_EXTENSIONS:
        return JSONResponse({"error": f"Tipo de archivo no permitido. Permitidos: {', '.join(VALID_DOC_EXTENSIONS)}"}, status_code=400)

    # Validar MIME type real del archivo
    if ext in MIME_WHITELIST and archivo.content_type not in MIME_WHITELIST[ext]:
        return JSONResponse({"error": f"El contenido del archivo no coincide con su extensión ({ext})"}, status_code=400)

    # Limitar tamaño (20MB máximo)
    contents = await archivo.read()
    if len(contents) > 20 * 1024 * 1024:
        return JSONResponse({"error": "Archivo demasiado grande. Máximo 20MB"}, status_code=400)
    await archivo.seek(0)

    # Guardar archivo (reutiliza UPLOAD_DIR + session_id de la propiedad)
    doc_dir = UPLOAD_DIR / prop["session_id"] / "documentos"
    doc_dir.mkdir(parents=True, exist_ok=True)

    safe_tipo = re.sub(r"[^a-zA-Z0-9_-]", "_", tipo_documento.lower())
    filename = f"{safe_tipo}_{uuid.uuid4().hex[:8]}{ext}"
    dest = doc_dir / filename

    with open(dest, "wb") as buffer:
        shutil.copyfileobj(archivo.file, buffer)

    archivo_url = f"/static/uploads/{prop['session_id']}/documentos/{filename}"

    # Guardar registro en BD
    doc_id = await save_documento({
        "propiedad_id": propiedad_id,
        "subido_por": user["id"],
        "tipo_documento": tipo_documento,
        "categoria": categoria,
        "archivo_url": archivo_url,
        "notas": notas or "",
    })

    # ── Trigger: notificar al agente/admin que se subió un documento ──
    agente_id = prop.get("user_id")
    meta_subido = {
        "tipo_documento": tipo_documento,
        "categoria": categoria,
        "cliente_nombre": user.get("nombre", ""),
        "cliente_id": user["id"],
    }
    if agente_id and agente_id != user["id"]:
        await crear_notificacion(
            tipo="documento_subido",
            user_id=agente_id,
            propiedad_id=propiedad_id,
            metadata=meta_subido,
        )
        await disparar_notificaciones("documento_subido", agente_id, propiedad_id, meta_subido)

    # ── Trigger: verificar si todos los obligatorios están completos ──
    docs = await get_documentos_by_propiedad(propiedad_id)
    docs_vendedor = {d["tipo_documento"]: d for d in docs if d.get("categoria") == "vendedor"}
    obligatorios_completos = all(
        d["tipo"] in docs_vendedor for d in DOCS_VENDEDOR if d["obligatorio"]
    )
    if obligatorios_completos and agente_id:
        meta_completos = {
            "mensaje": "Todos los documentos obligatorios del vendedor han sido subidos. Propiedad lista para avanzar al cierre.",
            "vendedor_nombre": user.get("nombre", ""),
        }
        await crear_notificacion(
            tipo="documentos_completos",
            user_id=agente_id,
            propiedad_id=propiedad_id,
            metadata=meta_completos,
        )
        await disparar_notificaciones("documentos_completos", agente_id, propiedad_id, meta_completos)

    return JSONResponse({
        "ok": True,
        "documento_id": doc_id,
        "archivo_url": archivo_url,
    })


@app.get("/api/documentos/{propiedad_id}")
async def listar_documentos(request: Request, propiedad_id: int):
    user = await require_auth(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)

    prop = await get_property_by_id(propiedad_id)
    if not prop:
        return JSONResponse({"error": "Propiedad no encontrada"}, status_code=404)

    if user["rol"] != "admin" and prop.get("user_id") != user["id"]:
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    docs = await get_documentos_by_propiedad(propiedad_id)
    return JSONResponse({"ok": True, "documentos": docs})


@app.post("/api/documentos/{doc_id}/estado")
async def cambiar_estado_documento(
    request: Request,
    doc_id: int,
    estado: str = Form(...),
    notas: str = Form(""),
):
    user = await require_auth(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)

    # Solo agente o admin puede cambiar estado
    if user["rol"] not in ("admin", "agente"):
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    if estado not in ("pendiente", "aprobado", "rechazado"):
        return JSONResponse({"error": "Estado inválido"}, status_code=400)

    result = await update_documento_estado(doc_id, estado, notas)
    if not result:
        return JSONResponse({"error": "Documento no encontrado"}, status_code=404)

    # ── Trigger: si se rechazó, notificar al vendedor/comprador ──
    mensaje_wa = None
    if estado == "rechazado":
        prop = await get_property_by_id(result["propiedad_id"])
        destinatario_id = None
        if result.get("categoria") == "comprador" and prop:
            destinatario_id = prop.get("comprador_id")
        if not destinatario_id and prop:
            destinatario_id = prop.get("vendedor_id")
        if not destinatario_id:
            destinatario_id = result.get("subido_por")
        if destinatario_id:
            meta_rechazado = {
                "tipo_documento": result["tipo_documento"],
                "notas": notas,
                "revisado_por": user.get("nombre", ""),
            }
            await crear_notificacion(
                tipo="documento_rechazado",
                user_id=destinatario_id,
                propiedad_id=result["propiedad_id"],
                metadata=meta_rechazado,
            )
            # Email automático
            destinatario = await get_user_by_id(destinatario_id)
            if destinatario:
                direccion = prop.get("direccion", "") if prop else ""
                plantilla = NOTIF_MENSAJES.get("documento_rechazado", {})
                cuerpo = plantilla.get("cuerpo", "")
                try:
                    cuerpo = cuerpo.format(**{**meta_rechazado, "direccion": direccion})
                except KeyError:
                    pass
                import asyncio
                asyncio.create_task(enviar_email_notificacion(
                    destinatario["email"], destinatario["nombre"],
                    plantilla.get("asunto", "Documento rechazado"), cuerpo
                ))
                # Generar mensaje WA para que el agente lo envíe
                telefono = destinatario.get("telefono", "")
                msg_wa = plantilla.get("whatsapp", "")
                try:
                    msg_wa = msg_wa.format(**{**meta_rechazado, "direccion": direccion})
                except KeyError:
                    pass
                if telefono:
                    tel_limpio = "".join(c for c in str(telefono) if c.isdigit())
                    if len(tel_limpio) == 10:
                        tel_limpio = "52" + tel_limpio
                    mensaje_wa = {
                        "telefono": tel_limpio,
                        "nombre": destinatario.get("nombre", ""),
                        "mensaje": msg_wa,
                    }

    return JSONResponse({"ok": True, "estado": estado, "mensaje_wa": mensaje_wa})


# ── Notificaciones API ──

@app.get("/api/notificaciones")
async def api_notificaciones(request: Request):
    user = await require_auth(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    notifs = await get_notificaciones(user["id"], solo_no_leidas=False, limit=50)
    count = await contar_notificaciones_no_leidas(user["id"])
    return JSONResponse({"ok": True, "notificaciones": notifs, "no_leidas": count})


@app.post("/api/notificaciones/{notif_id}/leer")
async def api_marcar_leida(request: Request, notif_id: int):
    user = await require_auth(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    await marcar_notificacion_leida(notif_id)
    return JSONResponse({"ok": True})


@app.get("/api/docs-pendientes")
async def api_docs_pendientes(request: Request):
    """Reporte de propiedades con documentos incompletos. Solo agente/admin."""
    user = await require_auth(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    if user["rol"] not in ("admin", "agente"):
        return JSONResponse({"error": "Sin permisos"}, status_code=403)
    resumen = await get_propiedades_con_docs_pendientes()
    return JSONResponse({"ok": True, "propiedades": resumen})


ESTADO_ORDEN = {
    "atorado": 0, "esperando_notaria": 1, "en_cierre": 2, "listo_para_cerrar": 3,
    "en_proceso_inscripcion": 4, "casi_listo": 5, "en_proceso": 6, "sin_iniciar": 7, "completo": 8,
}
PRIORIDAD_ORDEN = {"alta": 0, "alta_cierre": 1, "media": 2, "normal": 3, "baja": 4, "ninguna": 5}

CHECKLIST_CIERRE = [
    {"clave": "docs_vendedor", "label": "Documentos del vendedor completos", "fase": 1},
    {"clave": "docs_comprador", "label": "Documentos del comprador completos", "fase": 1},
    {"clave": "promesa_compraventa", "label": "Firma de promesa de compraventa", "fase": 2},
    {"clave": "forma_pago", "label": "Forma de pago definida (contado / crédito / transferencia)", "fase": 2},
    {"clave": "enganche_recibido", "label": "Enganche recibido", "fase": 2},
    {"clave": "notaria_seleccionada", "label": "Notaría seleccionada", "fase": 3},
    {"clave": "fecha_notaria", "label": "Fecha tentativa de escrituración", "fase": 3},
    {"clave": "gastos_calculados", "label": "Gastos de cierre calculados", "fase": 3},
    {"clave": "avaluo_realizado", "label": "Avalúo realizado (si aplica crédito)", "fase": 4},
    {"clave": "credito_autorizado", "label": "Crédito autorizado (si aplica)", "fase": 4},
    {"clave": "predial_al_corriente", "label": "Predial al corriente", "fase": 5},
    {"clave": "libre_gravamen", "label": "Certificado de libertad de gravamen", "fase": 5},
    {"clave": "firma_escrituras", "label": "Firma de escrituras", "fase": 6},
    {"clave": "entrega_llaves", "label": "Entrega de llaves", "fase": 6},
]

FASES_CIERRE = {
    1: "Documentación",
    2: "Promesa y pago",
    3: "Notaría y gastos",
    4: "Crédito y avalúo",
    5: "Certificados",
    6: "Escrituración y entrega",
}

GASTOS_VENDEDOR = [
    {"clave": "isr", "label": "ISR (Impuesto Sobre la Renta)", "porcentaje_sugerido": None},
    {"clave": "cancelacion_hipoteca", "label": "Cancelación de hipoteca", "porcentaje_sugerido": None},
    {"clave": "predial", "label": "Predial al corriente", "porcentaje_sugerido": None},
    {"clave": "comision_agente", "label": "Comisión del agente", "porcentaje_sugerido": 4.0},
    {"clave": "plusvalia", "label": "Plusvalía (si aplica)", "porcentaje_sugerido": None},
    {"clave": "otros_vendedor", "label": "Otros gastos vendedor", "porcentaje_sugerido": None},
]

GASTOS_COMPRADOR = [
    {"clave": "isai", "label": "ISAI (Impuesto adquisición inmuebles)", "porcentaje_sugerido": 2.0},
    {"clave": "honorarios_notariales", "label": "Honorarios notariales", "porcentaje_sugerido": None},
    {"clave": "registro_publico", "label": "Registro público de la propiedad", "porcentaje_sugerido": None},
    {"clave": "avaluo", "label": "Avalúo", "porcentaje_sugerido": None},
    {"clave": "gastos_credito", "label": "Gastos de crédito (apertura, seguro)", "solo_credito": True},
    {"clave": "certificado_libertad", "label": "Certificado de libertad de gravamen", "porcentaje_sugerido": None},
    {"clave": "otros_comprador", "label": "Otros gastos comprador", "porcentaje_sugerido": None},
]


def _dias_desde(fecha):
    """Calcula días transcurridos desde una fecha. Retorna None si no hay fecha."""
    if not fecha:
        return None
    from datetime import datetime, timezone
    if isinstance(fecha, str):
        try:
            fecha = datetime.fromisoformat(fecha)
        except (ValueError, TypeError):
            return None
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - fecha).days


def calcular_estado_propiedad(docs_subidos, docs_rechazados, total_obligatorios, cierre_data=None):
    """Calcula el estado de avance de una propiedad incluyendo estados de cierre."""
    if docs_rechazados > 0:
        return "atorado"
    if docs_subidos == 0:
        return "sin_iniciar"
    porcentaje = round(docs_subidos / total_obligatorios * 100) if total_obligatorios > 0 else 0

    # Si hay datos de cierre, evaluar estados avanzados
    if cierre_data and isinstance(cierre_data, dict):
        items = cierre_data.get("items", {})
        datos = cierre_data.get("datos", {})
        tipo_compra = (datos.get("forma_pago") or "").lower()
        es_credito = any(x in tipo_compra for x in ("crédito", "credito", "infonavit", "isseg", "bancario", "mixto"))

        # Contar items completados por fase
        fase_completa = {}
        for item in CHECKLIST_CIERRE:
            f = item["fase"]
            if f not in fase_completa:
                fase_completa[f] = {"total": 0, "done": 0}
            # Saltar crédito si no aplica
            if not es_credito and item["clave"] in ("avaluo_realizado", "credito_autorizado"):
                continue
            fase_completa[f]["total"] += 1
            if items.get(item["clave"]):
                fase_completa[f]["done"] += 1

        def fase_ok(n):
            f = fase_completa.get(n, {})
            return f.get("total", 0) > 0 and f["done"] >= f["total"]

        # Estado: esperando_notaria — fases 1-5 completas, falta escritura
        if fase_ok(1) and fase_ok(2) and fase_ok(3) and fase_ok(5):
            if es_credito and not fase_ok(4):
                pass  # falta crédito, no puede estar esperando notaría
            else:
                return "esperando_notaria"

        # Estado: en_proceso_inscripcion — crédito en trámite (fase 2 ok, fase 4 parcial)
        if es_credito and fase_ok(2) and not fase_ok(4):
            f4 = fase_completa.get(4, {})
            if f4.get("done", 0) > 0:
                return "en_proceso_inscripcion"

        # Estado: en_cierre — fase 2 completa (promesa + pago)
        if fase_ok(2):
            return "en_cierre"

    # Estados de documentación
    if porcentaje >= 100:
        return "completo"
    if porcentaje >= 90 and docs_rechazados == 0:
        return "listo_para_cerrar"
    if porcentaje > 80:
        return "casi_listo"
    return "en_proceso"


def calcular_prioridad(estado):
    """Calcula la prioridad de contacto basada en el estado."""
    prioridades = {
        "atorado": "alta",
        "esperando_notaria": "alta_cierre",
        "listo_para_cerrar": "alta_cierre",
        "en_cierre": "alta_cierre",
        "en_proceso_inscripcion": "media",
        "casi_listo": "media",
        "en_proceso": "normal",
        "sin_iniciar": "baja",
    }
    return prioridades.get(estado, "ninguna")


def generar_mensaje_seguimiento(estado, nombre, propiedad):
    """Genera mensaje de WhatsApp sugerido según el estado del proceso."""
    nombre = nombre or "cliente"
    propiedad = propiedad or "tu propiedad"
    mensajes = {
        "atorado": f"Hola {nombre}, vi que uno de tus documentos necesita una corrección para avanzar con {propiedad}. ¿Te puedo ayudar a revisarlo? 👍",
        "esperando_notaria": f"Hola {nombre}, ya todo está listo para {propiedad}. Solo estamos esperando la fecha de escrituración en notaría. Te confirmo en cuanto tengamos el día exacto 🏛️✅",
        "en_cierre": f"Hola {nombre}, ya firmamos promesa y estamos avanzando con el cierre de {propiedad}. Vamos muy bien, te mantengo informado de los siguientes pasos 📋🚀",
        "en_proceso_inscripcion": f"Hola {nombre}, tu crédito está en proceso de autorización para {propiedad}. Estamos dando seguimiento con el banco, te aviso de cualquier novedad 🏦",
        "listo_para_cerrar": f"Hola {nombre}, ya tenemos todo listo para avanzar con la firma de {propiedad}. Estamos en etapa final, solo falta coordinar firma de promesa y fecha en notaría. ¿Te parece si lo agendamos esta semana? 🚀",
        "casi_listo": f"Hola {nombre}, ya casi terminamos tu proceso para {propiedad}. Solo falta un paso para avanzar con tu cierre 🙌",
        "en_proceso": f"Hola {nombre}, ¿cómo vas con tus documentos para {propiedad}? Te ayudo a avanzar para asegurar tu proceso 👍",
        "sin_iniciar": f"Hola {nombre}, te recuerdo que necesitamos tus documentos para iniciar el proceso de {propiedad}. ¿Cuándo puedes enviarlos? 📄",
    }
    return mensajes.get(estado, "")


def generar_mensaje_comprador(nombre, tipo_compra, porcentaje, dias_sin_actividad):
    """Genera mensaje de seguimiento para comprador basado en su avance."""
    nombre = nombre or "cliente"
    tipo = tipo_compra or "tu crédito"

    if porcentaje >= 100:
        msg = (
            f"Hola {nombre}, ya tenemos todo listo para avanzar con la firma de tu propiedad. "
            f"¿Te parece si coordinamos fecha para notaría esta semana?"
        )
    elif porcentaje > 80:
        msg = (
            f"Hola {nombre}, estamos muy cerca de finalizar tu proceso. "
            f"Solo faltan algunos detalles para poder avanzar a la siguiente etapa. "
            f"¿Te parece si lo vemos hoy?"
        )
    elif porcentaje >= 30:
        msg = (
            f"Hola {nombre}, vas muy bien con tu proceso. "
            f"Estamos avanzando correctamente, solo faltan algunos documentos para continuar. "
            f"¿Te parece si lo revisamos hoy?"
        )
    else:
        msg = (
            f"Hola {nombre}, estoy dando seguimiento a tu proceso de compra. "
            f"Para poder avanzar necesitamos completar tus documentos. "
            f"¿Te apoyo con alguno?"
        )

    if dias_sin_actividad > 3:
        msg += " Noté que no hemos tenido avances recientes, no quiero que pierdas esta oportunidad."

    return msg


def generar_mensaje_recuperar(nombre):
    """Genera mensaje agresivo para recuperar cliente atorado."""
    nombre = nombre or "cliente"
    return (
        f"Hola {nombre}, no quiero que pierdas esta oportunidad. "
        f"Tu proceso está detenido y podemos retomarlo de inmediato. "
        f"¿Te apoyo para avanzar hoy?"
    )


@app.get("/api/mensaje-seguimiento/{comprador_id}")
async def mensaje_seguimiento_comprador(request: Request, comprador_id: int, modo: str = "seguimiento"):
    user = await require_auth(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    if user["rol"] not in ("admin", "agente"):
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    comprador = await get_user_by_id(comprador_id)
    if not comprador or comprador["rol"] != "comprador":
        return JSONResponse({"error": "Comprador no encontrado"}, status_code=404)

    props = await get_properties_by_comprador(comprador_id)
    if not props:
        return JSONResponse({"mensaje": f"Hola {comprador['nombre']}, estoy dando seguimiento a tu proceso de compra. ¿Cómo vas?"})

    # Tomar la primera propiedad asignada
    prop = props[0]

    # Seguridad: solo el agente dueño de la propiedad o admin
    if user["rol"] != "admin" and prop.get("user_id") != user["id"]:
        return JSONResponse({"error": "Sin permisos sobre esta propiedad"}, status_code=403)

    # Calcular avance
    tipo_compra = prop.get("tipo_compra", "")
    checklist = get_docs_comprador(tipo_compra) if tipo_compra else []
    total_oblig = sum(1 for d in checklist if d["obligatorio"])

    docs = await get_documentos_by_propiedad(prop["id"])
    docs_comprador = {d["tipo_documento"]: d for d in docs if d.get("categoria") == "comprador"}
    subidos_oblig = sum(1 for d in checklist if d["obligatorio"] and d["tipo"] in docs_comprador)
    porcentaje = round(subidos_oblig / total_oblig * 100) if total_oblig > 0 else 0

    # Calcular días sin actividad
    from datetime import datetime, timezone
    docs_comprador_list = [d for d in docs if d.get("categoria") == "comprador"]
    if docs_comprador_list:
        fechas = []
        for d in docs_comprador_list:
            ca = d.get("created_at")
            if ca:
                if isinstance(ca, str):
                    try:
                        ca = datetime.fromisoformat(ca)
                    except (ValueError, TypeError):
                        continue
                if ca.tzinfo is None:
                    ca = ca.replace(tzinfo=timezone.utc)
                fechas.append(ca)
        if fechas:
            ultima = max(fechas)
            ahora = datetime.now(timezone.utc)
            dias_sin_actividad = (ahora - ultima).days
        else:
            dias_sin_actividad = 999
    else:
        dias_sin_actividad = 999

    if modo == "recuperar":
        mensaje = generar_mensaje_recuperar(comprador["nombre"])
    else:
        mensaje = generar_mensaje_comprador(
            nombre=comprador["nombre"],
            tipo_compra=tipo_compra,
            porcentaje=porcentaje,
            dias_sin_actividad=dias_sin_actividad,
        )

    return JSONResponse({
        "mensaje": mensaje,
        "comprador": comprador["nombre"],
        "comprador_id": comprador_id,
        "propiedad_id": prop["id"],
        "tipo_compra": tipo_compra or "Sin seleccionar",
        "porcentaje": porcentaje,
        "dias_sin_actividad": dias_sin_actividad if dias_sin_actividad < 999 else None,
        "modo": modo,
    })


@app.post("/api/mensaje-seguimiento/registrar")
async def registrar_seguimiento(request: Request):
    user = await require_auth(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    if user["rol"] not in ("admin", "agente"):
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    body = await request.json()
    comprador_id = body.get("comprador_id")
    propiedad_id = body.get("propiedad_id")
    mensaje = body.get("mensaje", "")
    modo = body.get("modo", "seguimiento")

    if not comprador_id or not propiedad_id or not mensaje:
        return JSONResponse({"error": "Datos incompletos"}, status_code=400)

    await guardar_seguimiento(comprador_id, propiedad_id, user["id"], mensaje, modo)
    return JSONResponse({"ok": True})


@app.get("/api/generar-cierre/{propiedad_id}")
async def generar_cierre(propiedad_id: int, request: Request):
    """Genera el checklist de cierre para una propiedad lista para cerrar."""
    user = await require_auth(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    if user["rol"] not in ("admin", "agente"):
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    prop = await get_property_by_id(propiedad_id)
    if not prop:
        return JSONResponse({"error": "Propiedad no encontrada"}, status_code=404)

    # Verificar propiedad del agente
    if user["rol"] == "agente" and prop.get("user_id") != user["id"]:
        return JSONResponse({"error": "Sin permisos sobre esta propiedad"}, status_code=403)

    # Datos del vendedor y comprador
    vendedor = await get_user_by_id(prop["vendedor_id"]) if prop.get("vendedor_id") else None
    comprador = await get_user_by_id(prop["comprador_id"]) if prop.get("comprador_id") else None

    # Auto-evaluar items de fase 1 (docs completos)
    cierre_data = prop.get("cierre_data") or {}
    items_estado = cierre_data.get("items", {})

    # Contar docs reales de la propiedad
    all_docs = await get_documentos_by_propiedad(propiedad_id)
    docs_vendedor = [d for d in all_docs if d.get("rol_documento", "vendedor") == "vendedor"]
    docs_comprador_list = [d for d in all_docs if d.get("rol_documento") == "comprador"]

    # Verificar docs vendedor
    total_vend = sum(1 for d in DOCS_VENDEDOR_LIST if d["obligatorio"])
    docs_vend_subidos = sum(1 for d in docs_vendedor if d.get("estado") != "rechazado")
    rech_vend = sum(1 for d in docs_vendedor if d.get("estado") == "rechazado")
    if docs_vend_subidos >= total_vend and rech_vend == 0:
        items_estado.setdefault("docs_vendedor", True)

    # Verificar docs comprador (se evaluará manualmente por el agente)
    tipo_compra = prop.get("tipo_compra") or ""

    # Datos de cierre guardados por el agente
    datos_cierre = cierre_data.get("datos", {})

    # Auto-marcar items según datos capturados
    if datos_cierre.get("promesa_fecha") and datos_cierre.get("promesa_monto"):
        items_estado.setdefault("promesa_compraventa", True)
    if datos_cierre.get("forma_pago"):
        items_estado.setdefault("forma_pago", True)
    if datos_cierre.get("enganche_monto"):
        items_estado.setdefault("enganche_recibido", True)
    if datos_cierre.get("notaria_nombre"):
        items_estado.setdefault("notaria_seleccionada", True)
    if datos_cierre.get("fecha_escrituracion"):
        items_estado.setdefault("fecha_notaria", True)

    # Determinar qué items aplican según tipo de compra
    checklist = []
    completados = 0
    for item in CHECKLIST_CIERRE:
        clave = item["clave"]
        # Saltar items de crédito si es contado
        if tipo_compra.lower() in ("contado", "transferencia"):
            if clave in ("avaluo_realizado", "credito_autorizado"):
                continue
        estado_item = items_estado.get(clave, False)
        if estado_item:
            completados += 1
        checklist.append({
            "clave": clave,
            "label": item["label"],
            "fase": item["fase"],
            "fase_nombre": FASES_CIERRE.get(item["fase"], ""),
            "completado": estado_item,
        })

    total_items = len(checklist)
    pct_cierre = round(completados / total_items * 100) if total_items > 0 else 0

    nombre_prop = f"{prop.get('tipo_propiedad', 'Propiedad')} en {prop.get('ciudad', '')}"

    # Mensaje de cierre para WhatsApp
    nombre_cliente = (comprador or {}).get("nombre") or (vendedor or {}).get("nombre") or "cliente"
    if pct_cierre >= 80:
        msg_cierre = (
            f"Hola {nombre_cliente}, estamos en la recta final del cierre de {nombre_prop}. "
            f"Solo faltan {total_items - completados} paso(s) para completar la operación. "
            f"¿Podemos agendar la firma esta semana? 🏠✅"
        )
    elif pct_cierre >= 50:
        msg_cierre = (
            f"Hola {nombre_cliente}, vamos avanzando muy bien con el cierre de {nombre_prop}. "
            f"Llevamos {completados} de {total_items} pasos completados. "
            f"Te comparto lo que sigue para agilizar el proceso. 📋"
        )
    else:
        msg_cierre = (
            f"Hola {nombre_cliente}, ya estamos listos para iniciar el proceso de cierre de {nombre_prop}. "
            f"Te paso el checklist de pasos que necesitamos cubrir para llegar a la firma. 📝🚀"
        )

    # Enriquecer mensaje con datos de cierre si están disponibles
    extras = []
    if datos_cierre.get("fecha_escrituracion"):
        extras.append(f"📅 Fecha tentativa de escrituración: {datos_cierre['fecha_escrituracion']}")
    if datos_cierre.get("notaria_nombre"):
        extras.append(f"🏛️ Notaría: {datos_cierre['notaria_nombre']}")
    if datos_cierre.get("forma_pago"):
        extras.append(f"💳 Forma de pago: {datos_cierre['forma_pago']}")
    if datos_cierre.get("monto_total"):
        extras.append(f"💰 Monto total: ${datos_cierre['monto_total']}")
    if extras:
        msg_cierre += "\n\n" + "\n".join(extras)

    return JSONResponse({
        "propiedad_id": propiedad_id,
        "propiedad": nombre_prop,
        "vendedor": vendedor["nombre"] if vendedor else None,
        "comprador": comprador["nombre"] if comprador else None,
        "tipo_compra": tipo_compra,
        "precio_formateado": prop.get("precio_formateado") or "",
        "checklist": checklist,
        "completados": completados,
        "total": total_items,
        "porcentaje_cierre": pct_cierre,
        "mensaje_cierre": msg_cierre,
        "datos": datos_cierre,
        "gastos": cierre_data.get("gastos", {}),
        "gastos_vendedor_template": GASTOS_VENDEDOR,
        "gastos_comprador_template": GASTOS_COMPRADOR,
    })


@app.post("/api/generar-cierre/{propiedad_id}/actualizar")
async def actualizar_cierre(propiedad_id: int, request: Request):
    """Actualiza el estado de un item del checklist de cierre."""
    user = await require_auth(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    if user["rol"] not in ("admin", "agente"):
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    prop = await get_property_by_id(propiedad_id)
    if not prop:
        return JSONResponse({"error": "Propiedad no encontrada"}, status_code=404)
    if user["rol"] == "agente" and prop.get("user_id") != user["id"]:
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    body = await request.json()
    clave = body.get("clave", "")
    completado = body.get("completado", False)

    # Validar que la clave existe
    claves_validas = {item["clave"] for item in CHECKLIST_CIERRE}
    if clave not in claves_validas:
        return JSONResponse({"error": "Item no válido"}, status_code=400)

    # Actualizar cierre_data en la propiedad
    cierre_data = prop.get("cierre_data") or {}
    items = cierre_data.get("items", {})
    items[clave] = completado
    cierre_data["items"] = items
    from datetime import datetime
    cierre_data["updated_at"] = str(datetime.now())

    await update_property(propiedad_id, {"cierre_data": cierre_data})
    return JSONResponse({"ok": True, "clave": clave, "completado": completado})


@app.post("/api/generar-cierre/{propiedad_id}/datos")
async def guardar_datos_cierre(propiedad_id: int, request: Request):
    """Guarda los datos del cierre: promesa, notaría, forma de pago, fecha."""
    user = await require_auth(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    if user["rol"] not in ("admin", "agente"):
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    prop = await get_property_by_id(propiedad_id)
    if not prop:
        return JSONResponse({"error": "Propiedad no encontrada"}, status_code=404)
    if user["rol"] == "agente" and prop.get("user_id") != user["id"]:
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    body = await request.json()

    # Campos permitidos para datos de cierre
    campos_permitidos = {
        "promesa_fecha", "promesa_monto", "promesa_notas",
        "forma_pago", "banco", "enganche_monto", "monto_total",
        "notaria_nombre", "notaria_direccion", "notaria_contacto",
        "fecha_escrituracion", "notas_cierre",
    }

    cierre_data = prop.get("cierre_data") or {}
    datos = cierre_data.get("datos", {})

    # Actualizar solo campos permitidos
    for campo, valor in body.items():
        if campo in campos_permitidos:
            datos[campo] = valor

    cierre_data["datos"] = datos
    from datetime import datetime
    cierre_data["datos_updated_at"] = str(datetime.now())

    # Auto-marcar checklist items según datos guardados
    items = cierre_data.get("items", {})
    if datos.get("promesa_fecha") and datos.get("promesa_monto"):
        items["promesa_compraventa"] = True
    if datos.get("forma_pago"):
        items["forma_pago"] = True
    if datos.get("enganche_monto"):
        items["enganche_recibido"] = True
    if datos.get("notaria_nombre"):
        items["notaria_seleccionada"] = True
    if datos.get("fecha_escrituracion"):
        items["fecha_notaria"] = True
    cierre_data["items"] = items

    await update_property(propiedad_id, {"cierre_data": cierre_data})

    # Generar mensajes predeterminados si se guardó fecha de escrituración
    mensajes_wa = {}
    if datos.get("fecha_escrituracion") and body.get("fecha_escrituracion"):
        mensajes_wa = _generar_mensajes_cierre_fecha(prop, datos, cierre_data)

    # Email automático (no requiere intervención del agente)
    if datos.get("fecha_escrituracion") and body.get("fecha_escrituracion"):
        import asyncio
        prop_actualizada = await get_property_by_id(propiedad_id)
        if prop_actualizada:
            prop_actualizada["cierre_data"] = cierre_data
            asyncio.create_task(_enviar_emails_cierre_fecha(prop_actualizada, datos))

    return JSONResponse({"ok": True, "datos": datos, "mensajes_wa": mensajes_wa})


@app.post("/api/generar-cierre/{propiedad_id}/gastos")
async def guardar_gastos_cierre(propiedad_id: int, request: Request):
    """Guarda los gastos de cierre desglosados por vendedor y comprador."""
    user = await require_auth(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    if user["rol"] not in ("admin", "agente"):
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    prop = await get_property_by_id(propiedad_id)
    if not prop:
        return JSONResponse({"error": "Propiedad no encontrada"}, status_code=404)
    if user["rol"] == "agente" and prop.get("user_id") != user["id"]:
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    body = await request.json()
    # body = {"vendedor": {"isr": "50000", ...}, "comprador": {"isai": "70000", ...}}

    cierre_data = prop.get("cierre_data") or {}
    gastos = cierre_data.get("gastos", {})

    # Validar claves permitidas
    claves_vend = {g["clave"] for g in GASTOS_VENDEDOR}
    claves_comp = {g["clave"] for g in GASTOS_COMPRADOR}

    if "vendedor" in body and isinstance(body["vendedor"], dict):
        gv = gastos.get("vendedor", {})
        for k, v in body["vendedor"].items():
            if k in claves_vend:
                gv[k] = v
        gastos["vendedor"] = gv

    if "comprador" in body and isinstance(body["comprador"], dict):
        gc = gastos.get("comprador", {})
        for k, v in body["comprador"].items():
            if k in claves_comp:
                gc[k] = v
        gastos["comprador"] = gc

    # Calcular totales
    total_vend = sum(float(v) for v in gastos.get("vendedor", {}).values() if v and str(v).replace(",", "").replace(".", "").isdigit())
    total_comp = sum(float(v) for v in gastos.get("comprador", {}).values() if v and str(v).replace(",", "").replace(".", "").isdigit())
    gastos["total_vendedor"] = round(total_vend, 2)
    gastos["total_comprador"] = round(total_comp, 2)
    gastos["total_general"] = round(total_vend + total_comp, 2)

    cierre_data["gastos"] = gastos

    # Auto-marcar checklist item
    items = cierre_data.get("items", {})
    if total_vend > 0 or total_comp > 0:
        items["gastos_calculados"] = True
    cierre_data["items"] = items

    from datetime import datetime
    cierre_data["gastos_updated_at"] = str(datetime.now())
    await update_property(propiedad_id, {"cierre_data": cierre_data})

    # Generar mensajes predeterminados para vendedor/comprador
    mensajes_wa = _generar_mensajes_gastos(prop, gastos)

    # Email automático
    import asyncio
    asyncio.create_task(_enviar_emails_gastos(prop, gastos))

    return JSONResponse({"ok": True, "gastos": gastos, "mensajes_wa": mensajes_wa})


# ── Plantillas de mensajes predeterminados ──
PLANTILLAS_WA = {
    "doc_recibido": "Hola *{nombre}*, le informamos que recibimos tu documento *{tipo_documento}* para la propiedad en _{direccion}_. Lo revisaremos a la brevedad.",
    "doc_rechazado": "Hola *{nombre}*, tu documento *{tipo_documento}* fue rechazado.\n\n📋 *Motivo:* _{motivo}_\n\nPor favor sube una versión corregida lo antes posible.",
    "docs_completos": "Hola *{nombre}*, tu expediente de documentos está *completo* para la propiedad en _{direccion}_. Procederemos con los siguientes pasos del cierre.",
    "bienvenida_vendedor": "Hola *{nombre}*, soy {agente_nombre} tu asesor inmobiliario. Ya tenemos tu propiedad en _{direccion}_ registrada. Necesitamos que subas tus documentos en el portal:\n\n🔗 {portal_url}\n\nQuedo al pendiente.",
    "bienvenida_comprador": "Hola *{nombre}*, soy {agente_nombre} tu asesor inmobiliario. Ya estás registrado como comprador para la propiedad en _{direccion}_. Te comparto el acceso al portal:\n\n🔗 {portal_url}\n\nQuedo al pendiente.",
    "seguimiento_general": "Hola *{nombre}*, ¿cómo va todo? Le doy seguimiento sobre la propiedad en _{direccion}_. ¿Tiene alguna duda o necesita algo?",
}


@app.get("/api/mensaje-wa/{tipo}/{propiedad_id}")
async def generar_mensaje_wa(tipo: str, propiedad_id: int, request: Request, destinatario: str = "vendedor"):
    """Genera un mensaje predeterminado de WhatsApp para que el agente lo envíe."""
    user = await require_auth(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    if user["rol"] not in ("admin", "agente"):
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    prop = await get_property_by_id(propiedad_id)
    if not prop:
        return JSONResponse({"error": "Propiedad no encontrada"}, status_code=404)

    direccion = prop.get("direccion", "Sin dirección")
    cierre_data = prop.get("cierre_data") or {}
    datos = cierre_data.get("datos", {})
    gastos = cierre_data.get("gastos", {})

    # Determinar destinatario
    dest_id = prop.get("vendedor_id") if destinatario == "vendedor" else prop.get("comprador_id")
    dest_user = await get_user_by_id(dest_id) if dest_id else None
    nombre_dest = dest_user["nombre"] if dest_user else "Cliente"
    telefono = dest_user.get("telefono", "") if dest_user else ""

    tel_limpio = ""
    if telefono:
        tel_limpio = "".join(c for c in str(telefono) if c.isdigit())
        if len(tel_limpio) == 10:
            tel_limpio = "52" + tel_limpio

    # Construir mensaje según tipo
    plantilla = PLANTILLAS_WA.get(tipo, "")
    meta = {
        "nombre": nombre_dest,
        "direccion": direccion,
        "agente_nombre": user.get("nombre", ""),
        "portal_url": f"{APP_URL}/portal",
        "tipo_documento": request.query_params.get("tipo_documento", ""),
        "motivo": request.query_params.get("motivo", ""),
    }

    # Tipos especiales de cierre
    if tipo == "cierre_fecha":
        desglose = _construir_desglose_gastos(
            gastos.get(destinatario, {}),
            GASTOS_VENDEDOR if destinatario == "vendedor" else GASTOS_COMPRADOR,
            "whatsapp"
        )
        mensaje = (
            f"Hola *{nombre_dest}*, le informamos que se ha programado la fecha de escrituración "
            f"para la propiedad en *{direccion}*.\n\n"
            f"📅 *Fecha:* {datos.get('fecha_escrituracion', 'Por definir')}\n"
            f"🏛️ *Notaría:* {datos.get('notaria_nombre', 'Por definir')}\n"
            f"📍 *Dirección:* {datos.get('notaria_direccion', 'Por definir')}\n"
            f"💰 *Forma de pago:* {datos.get('forma_pago', 'Por definir')}\n"
            f"💵 *Monto total:* ${datos.get('monto_total', 'Por definir')}\n\n"
            f"📝 *Tus gastos como {destinatario}:*\n{desglose}\n\n"
            f"Por favor confirma tu asistencia. Quedo al pendiente."
        )
    elif tipo == "cierre_gastos":
        total = gastos.get(f"total_{destinatario}", 0)
        desglose = _construir_desglose_gastos(
            gastos.get(destinatario, {}),
            GASTOS_VENDEDOR if destinatario == "vendedor" else GASTOS_COMPRADOR,
            "whatsapp"
        )
        mensaje = (
            f"Hola *{nombre_dest}*, le comparto el desglose de gastos de cierre para la "
            f"propiedad en *{direccion}*.\n\n"
            f"📝 *Gastos a tu cargo como {destinatario}:*\n{desglose}\n\n"
            f"🔸 *Total: ${float(total):,.2f}*\n\n"
            f"Si tienes alguna duda, quedo al pendiente."
        )
    else:
        try:
            mensaje = plantilla.format(**meta)
        except KeyError:
            mensaje = plantilla

    return JSONResponse({
        "ok": True,
        "mensaje": mensaje,
        "telefono": tel_limpio,
        "nombre": nombre_dest,
        "wa_link": f"https://wa.me/{tel_limpio}?text={mensaje}" if tel_limpio else "",
    })


@app.get("/api/gastos-cierre/{propiedad_id}")
async def ver_gastos_cierre(propiedad_id: int, request: Request):
    """Retorna gastos de cierre para visualización en portales (vendedor/comprador)."""
    user = await require_auth(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)

    prop = await get_property_by_id(propiedad_id)
    if not prop:
        return JSONResponse({"error": "Propiedad no encontrada"}, status_code=404)

    # Permisos: admin, agente, vendedor asignado, comprador asignado
    rol = user["rol"]
    es_vendedor = prop.get("vendedor_id") == user["id"]
    es_comprador = prop.get("comprador_id") == user["id"]
    es_agente = rol in ("admin", "agente")
    if not es_agente and not es_vendedor and not es_comprador:
        return JSONResponse({"error": "Sin permisos"}, status_code=403)

    cierre_data = prop.get("cierre_data") or {}
    gastos = cierre_data.get("gastos", {})

    # Filtrar: vendedor solo ve sus gastos, comprador solo los suyos
    resultado = {"propiedad_id": propiedad_id}
    if es_agente:
        resultado["vendedor"] = gastos.get("vendedor", {})
        resultado["comprador"] = gastos.get("comprador", {})
        resultado["total_vendedor"] = gastos.get("total_vendedor", 0)
        resultado["total_comprador"] = gastos.get("total_comprador", 0)
        resultado["total_general"] = gastos.get("total_general", 0)
        resultado["template_vendedor"] = GASTOS_VENDEDOR
        resultado["template_comprador"] = GASTOS_COMPRADOR
    elif es_vendedor:
        resultado["mis_gastos"] = gastos.get("vendedor", {})
        resultado["total"] = gastos.get("total_vendedor", 0)
        resultado["template"] = GASTOS_VENDEDOR
    elif es_comprador:
        resultado["mis_gastos"] = gastos.get("comprador", {})
        resultado["total"] = gastos.get("total_comprador", 0)
        resultado["template"] = GASTOS_COMPRADOR

    return JSONResponse(resultado)


@app.get("/dashboard-asesor", response_class=HTMLResponse)
async def dashboard_asesor(request: Request):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user["rol"] not in ("admin", "agente"):
        return RedirectResponse("/dashboard", status_code=302)

    # Admin ve todo, agente solo las suyas
    agente_id = None if user["rol"] == "admin" else user["id"]
    props_raw = await get_propiedades_seguimiento(agente_id=agente_id)

    total_obligatorios = sum(1 for d in DOCS_VENDEDOR_LIST if d["obligatorio"])

    # Obtener últimos seguimientos de compradores
    prop_ids = [p["id"] for p in props_raw]
    seguimientos = await get_ultimo_seguimiento_por_propiedad(prop_ids)

    propiedades = []
    contadores = {
        "sin_iniciar": 0, "en_proceso": 0, "casi_listo": 0, "atorado": 0,
        "listo_para_cerrar": 0, "en_cierre": 0, "en_proceso_inscripcion": 0,
        "esperando_notaria": 0, "completo": 0,
    }

    for p in props_raw:
        subidos = p["docs_subidos"] or 0
        rechazados = p["docs_rechazados"] or 0
        porcentaje = round(subidos / total_obligatorios * 100) if total_obligatorios > 0 else 0
        if porcentaje > 100:
            porcentaje = 100

        # Parsear cierre_data si viene como string
        cierre_raw = p.get("cierre_data") or {}
        if isinstance(cierre_raw, str):
            import json as _json
            try:
                cierre_raw = _json.loads(cierre_raw)
            except (ValueError, TypeError):
                cierre_raw = {}

        estado = calcular_estado_propiedad(subidos, rechazados, total_obligatorios, cierre_raw)
        contadores[estado] = contadores.get(estado, 0) + 1

        prioridad = calcular_prioridad(estado)
        nombre_prop = f"{p['tipo_propiedad'] or 'Propiedad'} en {p['ciudad'] or ''}"
        mensaje = generar_mensaje_seguimiento(estado, p["vendedor_nombre"], nombre_prop)

        # Motivo para tareas de hoy
        motivos = {
            "atorado": f"{rechazados} documento(s) rechazado(s)",
            "esperando_notaria": "Esperando fecha de escrituración",
            "en_cierre": "En proceso de cierre",
            "en_proceso_inscripcion": "Crédito en trámite",
            "listo_para_cerrar": "Momento ideal para cerrar",
            "casi_listo": "Listo para cerrar pronto",
            "en_proceso": f"Faltan {total_obligatorios - subidos} documentos",
            "sin_iniciar": "No ha subido documentos",
        }
        motivo = motivos.get(estado, "")

        propiedades.append({
            "id": p["id"],
            "tipo_propiedad": p["tipo_propiedad"] or "Propiedad",
            "operacion": p["operacion"] or "",
            "direccion": p["direccion"] or "",
            "ciudad": p["ciudad"] or "",
            "precio_formateado": p["precio_formateado"] or "",
            "foto_portada_url": p["foto_portada_url"],
            "vendedor_nombre": p["vendedor_nombre"] or "Sin asignar",
            "vendedor_email": p.get("vendedor_email", ""),
            "docs_subidos": subidos,
            "docs_total": len(DOCS_VENDEDOR_LIST),
            "docs_rechazados": rechazados,
            "docs_pendientes": p["docs_pendientes"] or 0,
            "porcentaje": porcentaje,
            "estado": estado,
            "prioridad": prioridad,
            "motivo": motivo,
            "mensaje_sugerido": mensaje,
            "ultimo_movimiento": str(p["ultimo_movimiento"])[:16] if p["ultimo_movimiento"] else "Sin actividad",
            "dias_inactivo": _dias_desde(p["ultimo_movimiento"]),
            "comprador_id": p.get("comprador_id"),
            "comprador_nombre": p.get("comprador_nombre") or "",
            "tipo_compra": p.get("tipo_compra") or "",
        })

        # Agregar datos de seguimiento del comprador
        seg = seguimientos.get(p["id"])
        if seg:
            from datetime import datetime, timezone
            seg_fecha = seg["created_at"]
            if isinstance(seg_fecha, str):
                try:
                    seg_fecha = datetime.fromisoformat(seg_fecha)
                except (ValueError, TypeError):
                    seg_fecha = None
            if seg_fecha:
                if seg_fecha.tzinfo is None:
                    seg_fecha = seg_fecha.replace(tzinfo=timezone.utc)
                dias_desde = (datetime.now(timezone.utc) - seg_fecha).days
            else:
                dias_desde = None
            propiedades[-1]["ultimo_mensaje"] = seg["mensaje"]
            propiedades[-1]["dias_desde_contacto"] = dias_desde
            propiedades[-1]["seg_modo"] = seg.get("modo", "seguimiento")
        else:
            propiedades[-1]["ultimo_mensaje"] = None
            propiedades[-1]["dias_desde_contacto"] = None
            propiedades[-1]["seg_modo"] = None

    # Ordenar: prioridad (alta→baja), luego último movimiento ASC (más olvidados primero)
    propiedades.sort(key=lambda x: (
        PRIORIDAD_ORDEN.get(x["prioridad"], 99),
        x["ultimo_movimiento"] if x["ultimo_movimiento"] != "Sin actividad" else "0000",
    ))

    # Tareas de hoy: prioridad alta, alta_cierre y media
    tareas_hoy = [p for p in propiedades if p["prioridad"] in ("alta", "alta_cierre", "media")]

    # Listos para cerrar (sección prioritaria)
    estados_cierre = {"listo_para_cerrar", "en_cierre", "en_proceso_inscripcion", "esperando_notaria"}
    listos_cierre = [p for p in propiedades if p["estado"] in estados_cierre]

    notif_count = await contar_notificaciones_no_leidas(user["id"])

    return templates.TemplateResponse(request=request, name="dashboard_asesor.html", context={
        "user": user,
        "propiedades": propiedades,
        "listos_cierre": listos_cierre,
        "tareas_hoy": tareas_hoy,
        "contadores": contadores,
        "total_propiedades": len(propiedades),
        "notif_count": notif_count,
    })


DOCS_VENDEDOR_LIST = DOCS_VENDEDOR = [
    {"tipo": "INE (Identificación oficial)", "obligatorio": True},
    {"tipo": "CURP", "obligatorio": True},
    {"tipo": "Constancia de situación fiscal", "obligatorio": True},
    {"tipo": "Acta de nacimiento", "obligatorio": True},
    {"tipo": "Escrituras", "obligatorio": True},
    {"tipo": "Estado de cuenta", "obligatorio": True},
    {"tipo": "Comprobante de servicios", "obligatorio": True},
    {"tipo": "Predial", "obligatorio": True},
    {"tipo": "Acta de matrimonio/divorcio", "obligatorio": False},
    {"tipo": "Poder notarial", "obligatorio": False},
    {"tipo": "Planos", "obligatorio": False},
]

DOCS_AGENTE = [
    {"tipo": "libertad_gravamen", "nombre": "Libertad de gravamen", "obligatorio": True},
    {"tipo": "contrato_comision", "nombre": "Contrato de comisión firmado", "obligatorio": True},
    {"tipo": "alta_propiedad", "nombre": "Alta de la propiedad", "obligatorio": True},
    {"tipo": "factibilidades", "nombre": "Factibilidades (agua/luz - terreno)", "obligatorio": False},
    {"tipo": "alineamiento_numero", "nombre": "Alineamiento y número oficial", "obligatorio": False},
    {"tipo": "cuotas_cooperacion", "nombre": "Cuotas de obras de cooperación", "obligatorio": True},
    {"tipo": "avaluo_fiscal", "nombre": "Avalúo fiscal", "obligatorio": True},
    {"tipo": "avaluo_comercial", "nombre": "Avalúo comercial", "obligatorio": False},
]


@app.get("/mis-documentos", response_class=HTMLResponse)
async def mis_documentos_sin_id(request: Request):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    # Buscar propiedades asignadas al vendedor
    props = await get_properties_by_vendedor(user["id"])

    if len(props) == 1:
        return RedirectResponse(f"/mis-documentos/{props[0]['id']}", status_code=302)
    elif len(props) > 1:
        # Múltiples propiedades: mostrar lista para elegir
        return templates.TemplateResponse(request=request, name="documentos_vendedor.html", context={
            "user": user,
            "propiedad": None,
            "propiedades": props,
            "checklist": [],
            "docs_subidos": {},
            "progreso": None,
        })

    # Sin propiedad asignada → flujo de selección
    return RedirectResponse("/seleccionar-propiedad", status_code=302)


@app.get("/mis-documentos/{propiedad_id}", response_class=HTMLResponse)
async def mis_documentos_vendedor(request: Request, propiedad_id: int):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    prop = await get_property_by_id(propiedad_id)
    if not prop:
        return RedirectResponse("/dashboard", status_code=302)

    # Permisos: admin, agente, o vendedor asignado
    rol = user["rol"]
    es_vendedor_asignado = prop.get("vendedor_id") == user["id"]
    es_dueño = prop.get("user_id") == user["id"]
    if rol not in ("admin", "agente") and not es_vendedor_asignado and not es_dueño:
        return RedirectResponse("/mis-documentos", status_code=302)

    docs = await get_documentos_by_propiedad(propiedad_id)

    # Mapear documentos subidos por categoría y tipo
    docs_vendedor = {}
    docs_agente = {}
    for d in docs:
        cat = d.get("categoria", "")
        if cat == "vendedor":
            docs_vendedor[d["tipo_documento"]] = d
        elif cat == "agente":
            docs_agente[d["tipo_documento"]] = d

    # Progreso vendedor
    total_oblig_v = sum(1 for d in DOCS_VENDEDOR if d["obligatorio"])
    subidos_oblig_v = sum(1 for d in DOCS_VENDEDOR if d["obligatorio"] and d["tipo"] in docs_vendedor)
    progreso_vendedor = {
        "subidos": len(docs_vendedor),
        "total": len(DOCS_VENDEDOR),
        "obligatorios_subidos": subidos_oblig_v,
        "obligatorios_total": total_oblig_v,
        "porcentaje": round(subidos_oblig_v / total_oblig_v * 100) if total_oblig_v > 0 else 0,
    }

    # Progreso agente
    total_oblig_a = sum(1 for d in DOCS_AGENTE if d["obligatorio"])
    subidos_oblig_a = sum(1 for d in DOCS_AGENTE if d["obligatorio"] and d["tipo"] in docs_agente)
    progreso_agente = {
        "subidos": len(docs_agente),
        "total": len(DOCS_AGENTE),
        "obligatorios_subidos": subidos_oblig_a,
        "obligatorios_total": total_oblig_a,
        "porcentaje": round(subidos_oblig_a / total_oblig_a * 100) if total_oblig_a > 0 else 0,
    }

    return templates.TemplateResponse(request=request, name="documentos_vendedor.html", context={
        "user": user,
        "propiedad": prop,
        "propiedades": [],
        "checklist": DOCS_VENDEDOR,
        "docs_subidos": docs_vendedor,
        "progreso": progreso_vendedor,
        "checklist_agente": DOCS_AGENTE,
        "docs_agente": docs_agente,
        "progreso_agente": progreso_agente,
    })


# ─── Dashboard de Referidos ───

@app.get("/mis-prospectos", response_class=HTMLResponse)
async def dashboard_referido(request: Request):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user["rol"] == "referido":
        prospectos = await get_all_prospectos(referido_id=user["id"])
        counts = await count_prospectos(referido_id=user["id"])
    elif user["rol"] == "admin":
        prospectos = await get_all_prospectos()
        counts = await count_prospectos()
    else:
        return RedirectResponse("/dashboard", status_code=302)

    # Serializar fechas
    for p in prospectos:
        for k, v in p.items():
            if hasattr(v, 'isoformat'):
                p[k] = v.isoformat()
            elif not isinstance(v, (int, float, str, bool, list, dict, type(None))):
                p[k] = str(v)

    return templates.TemplateResponse(request=request, name="dashboard_referido.html", context={
        "user": user,
        "prospectos": prospectos,
        "counts": counts,
    })


# ─── Admin: Gestion de Prospectos ───

@app.get("/admin/prospectos", response_class=HTMLResponse)
async def admin_prospectos_page(
    request: Request,
    referido: Optional[str] = None,
    estado: Optional[str] = None,
    fuente: Optional[str] = None,
    buscar: Optional[str] = None,
):
    user = await require_auth(request)
    if not user or user["rol"] not in ("admin", "agente"):
        return RedirectResponse("/login", status_code=302)
    referido_id = int(referido) if referido and referido.isdigit() else None
    prospectos = await get_all_prospectos(referido_id=referido_id)

    # Filtrar por estado
    if estado:
        prospectos = [p for p in prospectos if p.get("estado") == estado]
    # Filtrar por fuente
    if fuente:
        if fuente == "referido":
            prospectos = [p for p in prospectos if p.get("referido_id")]
        elif fuente == "manual":
            prospectos = [p for p in prospectos if not p.get("referido_id") and p.get("fuente") != "chatbot"]
        else:
            prospectos = [p for p in prospectos if p.get("fuente") == fuente]
    # Filtrar por búsqueda
    if buscar:
        q = buscar.lower()
        prospectos = [p for p in prospectos
                      if q in (p.get("nombre_cliente") or "").lower()
                      or q in (p.get("telefono_cliente") or "").lower()
                      or q in (p.get("desarrollo_interes") or "").lower()]

    counts = await count_prospectos()
    referidos = await get_all_referidos()
    citas = await get_citas_chatbot(limit=100)

    # Serializar para template
    for items in [prospectos, citas]:
        for p in items:
            for k, v in p.items():
                if hasattr(v, 'isoformat'):
                    p[k] = v.isoformat()
                elif not isinstance(v, (int, float, str, bool, list, dict, type(None))):
                    p[k] = str(v)

    return templates.TemplateResponse(request=request, name="admin_prospectos.html", context={
        "user": user,
        "prospectos": prospectos,
        "citas": citas,
        "counts": counts,
        "referidos": referidos,
        "selected_referido": referido_id,
        "selected_estado": estado or "",
        "selected_fuente": fuente or "",
        "buscar": buscar or "",
    })


@app.get("/api/prospectos/{prospecto_id}")
async def api_get_prospecto(request: Request, prospecto_id: int):
    """API para obtener detalle de un prospecto (usado por el modal JS)."""
    user = await require_auth(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    p = await get_prospecto_by_id(prospecto_id)
    if not p:
        return JSONResponse({"error": "No encontrado"}, status_code=404)
    # Serializar
    for k, v in p.items():
        if hasattr(v, 'isoformat'):
            p[k] = v.isoformat()
        elif not isinstance(v, (int, float, str, bool, list, dict, type(None))):
            p[k] = str(v)
    return JSONResponse({"prospecto": p})


@app.post("/admin/citas/{cita_id}/estado")
async def admin_update_cita_estado(request: Request, cita_id: int, estado: str = Form(...)):
    """Actualizar estado de una cita del chatbot."""
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    await update_cita_chatbot(cita_id, {"estado": estado})
    return RedirectResponse("/admin/prospectos", status_code=302)


@app.post("/admin/prospectos/{prospecto_id}/estado")
async def admin_update_prospecto_estado(
    request: Request,
    prospecto_id: int,
    estado: str = Form(...),
    notas: str = Form(""),
):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    updates = {"estado": estado}
    if notas:
        updates["notas"] = notas
    await update_prospecto(prospecto_id, updates)
    return RedirectResponse("/admin/prospectos", status_code=302)


@app.post("/mis-prospectos/{prospecto_id}/estado")
async def referido_update_prospecto_estado(
    request: Request,
    prospecto_id: int,
    estado: str = Form(...),
):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    # Verificar que el prospecto pertenece al referido
    prospecto = await get_prospecto_by_id(prospecto_id)
    if not prospecto or prospecto["referido_id"] != user["id"]:
        return RedirectResponse("/mis-prospectos", status_code=302)
    estados_validos = ["nuevo", "contactado", "cita_agendada", "cita_asistio", "en_negociacion", "venta_cerrada", "perdido"]
    if estado in estados_validos:
        await update_prospecto(prospecto_id, {"estado": estado})
    return RedirectResponse("/mis-prospectos", status_code=302)


@app.post("/admin/prospectos/crear")
async def admin_create_prospecto(
    request: Request,
    nombre_cliente: str = Form(""),
    telefono_cliente: str = Form(""),
    desarrollo_interes: str = Form(""),
    referido_id: str = Form(""),
    notas: str = Form(""),
):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    data = {
        "nombre_cliente": nombre_cliente,
        "telefono_cliente": telefono_cliente,
        "desarrollo_interes": desarrollo_interes,
        "referido_id": int(referido_id) if referido_id and referido_id.isdigit() else None,
        "agente_id": user["id"],
        "notas": notas,
        "estado": "nuevo",
        "fuente": "manual",
    }
    await create_prospecto(data)
    return RedirectResponse("/admin/prospectos", status_code=302)


@app.post("/admin/prospectos/{prospecto_id}/eliminar")
async def admin_delete_prospecto(request: Request, prospecto_id: int):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    await delete_prospecto(prospecto_id)
    return RedirectResponse("/admin/prospectos", status_code=302)


@app.post("/admin/prospectos/bulk")
async def admin_bulk_prospectos(request: Request):
    """Acciones masivas sobre prospectos: eliminar o cambiar estado en grupo."""
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    form = await request.form()
    action = form.get("bulk_action", "")
    ids = form.getlist("selected_ids")

    if not ids or not action:
        return RedirectResponse("/admin/prospectos", status_code=302)

    for pid_str in ids:
        try:
            pid = int(pid_str)
            if action == "eliminar":
                await delete_prospecto(pid)
            elif action.startswith("estado_"):
                nuevo_estado = action.replace("estado_", "")
                await update_prospecto(pid, {"estado": nuevo_estado})
        except (ValueError, Exception) as e:
            print(f"[BULK] Error procesando prospecto {pid_str}: {e}")

    return RedirectResponse("/admin/prospectos", status_code=302)


# ─── API: Debounce de mensajes WhatsApp ───
# Acumula mensajes del mismo numero y espera a que termine de escribir
# Tambien registra prospecto y crea lead en Kommo (una sola vez)

_message_buffer: Dict[str, dict] = {}
_kommo_created: Dict[str, float] = {}  # telefono -> timestamp de ultimo lead creado
_paused_chats: Dict[str, float] = {}  # telefono -> timestamp de cuando se pauso
_active_chats: Dict[str, float] = {}  # telefono -> timestamp de cuando se activo la conversacion
_bot_last_sent: Dict[str, float] = {}  # telefono -> timestamp de cuando el bot envio su ultima respuesta
PAUSE_DURATION = 3600 * 24  # 24 horas de pausa cuando Esteban escribe manualmente
ACTIVE_DURATION = 60 * 30  # 30 minutos de actividad máxima del bot
BOT_ECHO_WINDOW = 90  # segundos para considerar un fromMe como eco del bot (no de Esteban)

# Números bloqueados: el bot NUNCA se activa con estos teléfonos
# (desarrolladores, dueños de fraccionamiento, proveedores, etc.)
# Formato: últimos 10 dígitos del teléfono (sin 52, sin +)
BOT_BLOCKED_PHONES: set = set()
_blocked_phones_raw = os.getenv("BOT_BLOCKED_PHONES", "")
if _blocked_phones_raw:
    BOT_BLOCKED_PHONES = {p.strip()[-10:] for p in _blocked_phones_raw.split(",") if p.strip()}

# Palabras clave que activan el bot (sin importar mayúsculas)
BOT_KEYWORDS = [
    # Desarrollos
    "cárcamos", "carcamos", "fresno", "privada del fresno",
    # Inmobiliarias
    "casa", "departamento", "terreno", "propiedad", "lote",
    "venta", "renta", "comprar", "rentar",
    "inmueble", "residencial", "fraccionamiento",
    "recámara", "recamara", "habitación", "habitacion",
    "precio", "costo", "cuánto", "cuanto", "crédito", "credito",
    "infonavit", "fovissste", "hipoteca",
    "metros", "m2", "m²",
    "ubicación", "ubicacion", "dirección", "direccion", "dónde", "donde",
    "disponible", "disponibilidad",
    "agendar", "cita", "visitar", "visita", "ver la casa",
    "información", "informacion", "info",
    "interesa", "interesado", "interesada",
    "planos", "amenidades",
]

KOMMO_SUBDOMAIN = os.getenv("KOMMO_SUBDOMAIN", "irealestatemxclaude")
KOMMO_ACCESS_TOKEN = os.getenv("KOMMO_ACCESS_TOKEN", "")
KOMMO_PIPELINE_ID = 13489919
KOMMO_STATUS_ID = 103949563


def _has_bot_keyword(text: str) -> bool:
    """Verifica si el mensaje contiene alguna palabra clave que activa el bot.
    Ignora URLs y saludos genéricos para evitar falsos positivos."""
    import re as _re
    # Quitar URLs del texto antes de buscar keywords
    text_sin_urls = _re.sub(r'https?://\S+', '', text)
    text_sin_urls = _re.sub(r'www\.\S+', '', text_sin_urls)

    # Si solo quedó espacio vacío (era solo un enlace), no activar
    if not text_sin_urls.strip():
        return False

    # Saludos genéricos que NO deben activar el bot por sí solos
    text_clean = text_sin_urls.strip().lower()
    text_clean = _re.sub(r'[!¡?¿.,\s]+', ' ', text_clean).strip()
    SALUDOS_GENERICOS = {
        "hola", "hola buen dia", "hola buenos dias", "hola buenas tardes",
        "hola buenas noches", "buen dia", "buenos dias", "buenas tardes",
        "buenas noches", "buenas", "que tal", "hola que tal",
        "hey", "hi", "hello", "como estas", "hola como estas",
        "que onda", "hola que onda", "saludos", "hola saludos",
        "gracias", "muchas gracias", "ok", "okay", "va", "sale",
        "si", "sí", "no", "claro", "perfecto", "listo",
        "hola buen dia como estas", "hola buenas tardes como estas",
    }
    if text_clean in SALUDOS_GENERICOS:
        return False

    text_lower = text_sin_urls.lower()
    for kw in BOT_KEYWORDS:
        if kw in text_lower:
            return True
    # También detectar prefijos de referidos (ej: N-, A-, etc.)
    if re.search(r'[A-Z]\s*-\s', text_sin_urls, re.IGNORECASE):
        return True
    return False


def _is_chat_active(phone: str) -> bool:
    """Verifica si hay una conversación activa del bot con este número."""
    if phone not in _active_chats:
        return False
    elapsed = time.time() - _active_chats[phone]
    if elapsed > ACTIVE_DURATION:
        _active_chats.pop(phone, None)
        return False
    return True


async def _create_kommo_lead(phone: str, name: str):
    """Crea un lead en Kommo si no se creo uno para este telefono en las ultimas 24h."""
    now = time.time()
    last = _kommo_created.get(phone, 0)
    if now - last < 86400:  # 24 horas
        return None

    if not KOMMO_ACCESS_TOKEN:
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://{KOMMO_SUBDOMAIN}.kommo.com/api/v4/leads/complex",
                headers={"Authorization": f"Bearer {KOMMO_ACCESS_TOKEN}"},
                json=[{
                    "name": f"WhatsApp - {name or 'Cliente'}",
                    "pipeline_id": KOMMO_PIPELINE_ID,
                    "status_id": KOMMO_STATUS_ID,
                    "_embedded": {
                        "contacts": [{
                            "first_name": name or "Cliente WhatsApp",
                            "custom_fields_values": [{
                                "field_code": "PHONE",
                                "values": [{"value": f"+{phone}", "enum_code": "WORK"}]
                            }]
                        }]
                    }
                }]
            )
            if resp.status_code in (200, 201):
                _kommo_created[phone] = now
                print(f"[KOMMO] Lead creado para {name} ({phone})")
                return resp.json()
            else:
                print(f"[KOMMO] Error {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[KOMMO] Error: {e}")
    return None


@app.post("/api/whatsapp/pause")
async def whatsapp_pause(request: Request):
    """Pausa el bot para un telefono. Esteban toma el control."""
    body = await request.json()
    phone = body.get("phone", "")
    hours = body.get("hours", 4)
    _paused_chats[phone] = time.time()
    _active_chats.pop(phone, None)  # Desactivar conversación activa
    print(f"[BOT] Pausado para {phone} por {hours}h")
    return JSONResponse({"ok": True, "paused": phone, "hours": hours})


@app.post("/api/whatsapp/resume")
async def whatsapp_resume(request: Request):
    """Reactiva el bot para un telefono."""
    body = await request.json()
    phone = body.get("phone", "")
    _paused_chats.pop(phone, None)
    print(f"[BOT] Reactivado para {phone}")
    return JSONResponse({"ok": True, "resumed": phone})


@app.get("/api/whatsapp/paused")
async def whatsapp_paused_list():
    """Lista todos los chats pausados y activos."""
    now = time.time()
    paused = {k: round((PAUSE_DURATION - (now - v)) / 60) for k, v in _paused_chats.items() if now - v < PAUSE_DURATION}
    active = {k: round((ACTIVE_DURATION - (now - v)) / 60) for k, v in _active_chats.items() if now - v < ACTIVE_DURATION}
    return JSONResponse({"paused": paused, "active_chats": active})


@app.post("/api/chatbot/registrar-cita")
async def chatbot_registrar_cita(request: Request):
    """Registra un prospecto y su cita desde el chatbot de n8n.
    Reemplaza a Kommo: registra en BD, envía email al agente."""
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({"error": f"JSON inválido: {e}"}, status_code=400)

    try:
        telefono = body.get("telefono_cliente", "")
        nombre = body.get("nombre_cliente", "")
        desarrollo = body.get("desarrollo", "")
        es_cita = body.get("es_cita", False)
        fecha = body.get("fecha", "")
        hora = body.get("hora", "")
        hora_fin = body.get("hora_fin", "")
        titulo = body.get("titulo_evento", "")
        mensaje = body.get("mensaje_original", "")

        # 1. Buscar o crear prospecto
        prospecto = await get_prospecto_by_telefono(telefono) if telefono else None

        if prospecto:
            prospecto_id = prospecto["id"]
            updates = {}
            if nombre and not prospecto.get("nombre_cliente"):
                updates["nombre_cliente"] = nombre
            if desarrollo:
                updates["desarrollo_interes"] = desarrollo
            if es_cita:
                updates["estado"] = "cita_agendada"
            if updates:
                await update_prospecto(prospecto_id, updates)
        else:
            prospecto_id = await create_prospecto({
                "nombre_cliente": nombre,
                "telefono_cliente": telefono,
                "desarrollo_interes": desarrollo,
                "mensaje_original": mensaje,
                "estado": "cita_agendada" if es_cita else "nuevo",
                "fuente": "chatbot",
            })

        # 2. Agregar al historial
        from datetime import datetime as dt
        await agregar_historial_prospecto(prospecto_id, {
            "tipo": "cita_agendada" if es_cita else "mensaje_chatbot",
            "mensaje": mensaje,
            "fecha": str(dt.now()),
            "datos": {"desarrollo": desarrollo, "fecha_cita": fecha, "hora": hora},
        })

        # 3. Si es cita, registrarla
        cita_id = None
        if es_cita and fecha:
            cita_id = await create_cita_chatbot({
                "prospecto_id": prospecto_id,
                "titulo": titulo or f"Visita {desarrollo} - {nombre}",
                "desarrollo": desarrollo,
                "fecha": fecha,
                "hora_inicio": hora or None,
                "hora_fin": hora_fin or None,
                "estado": "pendiente",
            })

            # 4. Enviar email al agente
            import asyncio
            admin_email = os.getenv("ADMIN_EMAIL", "")
            admin_name = os.getenv("ADMIN_NAME", "Agente")
            if admin_email:
                cuerpo_email = (
                    f"Se agendó una nueva cita desde el chatbot de WhatsApp.\n\n"
                    f"<b>Cliente:</b> {nombre}\n"
                    f"<b>Teléfono:</b> {telefono}\n"
                    f"<b>Desarrollo:</b> {desarrollo}\n"
                    f"<b>Fecha:</b> {fecha}\n"
                    f"<b>Hora:</b> {hora} - {hora_fin}\n"
                    f"<b>Título:</b> {titulo}\n\n"
                    f"Revisa tu calendario y da seguimiento al prospecto."
                )
                asyncio.create_task(enviar_email_notificacion(
                    admin_email, admin_name,
                    f"Nueva cita: {nombre} - {desarrollo}", cuerpo_email
                ))

        return JSONResponse({
            "ok": True,
            "prospecto_id": prospecto_id,
            "cita_id": cita_id,
            "nombre": nombre,
            "telefono": telefono,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/chatbot/registrar-mensaje")
async def chatbot_registrar_mensaje(request: Request):
    """Registra un mensaje del chatbot (sin cita) — actualiza historial del prospecto."""
    body = await request.json()
    telefono = body.get("telefono_cliente", "")
    nombre = body.get("nombre_cliente", "")
    desarrollo = body.get("desarrollo", "")
    mensaje = body.get("mensaje", "")

    prospecto = await get_prospecto_by_telefono(telefono) if telefono else None

    if prospecto:
        prospecto_id = prospecto["id"]
        updates = {}
        if nombre and not prospecto.get("nombre_cliente"):
            updates["nombre_cliente"] = nombre
        if desarrollo and not prospecto.get("desarrollo_interes"):
            updates["desarrollo_interes"] = desarrollo
        if updates:
            await update_prospecto(prospecto_id, updates)
        from datetime import datetime as dt
        await agregar_historial_prospecto(prospecto_id, {
            "tipo": "mensaje_chatbot",
            "mensaje": mensaje,
            "fecha": str(dt.now()),
            "datos": {"desarrollo": desarrollo},
        })
    else:
        prospecto_id = await create_prospecto({
            "nombre_cliente": nombre,
            "telefono_cliente": telefono,
            "desarrollo_interes": desarrollo,
            "mensaje_original": mensaje,
            "estado": "nuevo",
            "fuente": "chatbot",
        })

    return JSONResponse({"ok": True, "prospecto_id": prospecto_id})


@app.post("/api/whatsapp/deactivate")
async def whatsapp_deactivate(request: Request):
    """Registra que el flujo del bot completó una respuesta.
    Ya NO desactiva la conversación inmediatamente — se mantiene activa
    por ACTIVE_DURATION (2h) para permitir follow-ups del cliente.
    Solo se desactiva si se pasa force=true (para desactivación manual)."""
    body = await request.json()
    phone = body.get("phone", "")
    force = body.get("force", False)

    if force:
        _active_chats.pop(phone, None)
        print(f"[BOT] Conversación FORZADA desactivada para {phone}")
        return JSONResponse({"ok": True, "deactivated": phone})

    # No desactivar — refrescar el timestamp para que siga activa
    if phone in _active_chats:
        _active_chats[phone] = time.time()
        print(f"[BOT] Flujo completado para {phone} — conversación sigue activa (2h)")
    return JSONResponse({"ok": True, "deactivated": ""})


@app.post("/api/whatsapp/debounce")
async def whatsapp_debounce(request: Request):
    """
    Recibe cada mensaje de WhatsApp (tanto del cliente como de Esteban).
    Lógica:
    1. Si fromMe=true → Esteban escribió → pausar bot y desactivar chat
    2. Si el bot está pausado → no procesar
    3. Si NO hay conversación activa → solo activar si hay palabras clave
    4. Si hay conversación activa → acumular mensajes con debounce de 12s
    5. Al final: registrar prospecto + crear lead Kommo (una sola vez)
    """
    body = await request.json()
    phone = body.get("phone", "")
    message = body.get("message", "")
    name = body.get("name", "")
    chat_id = body.get("chatId", "")
    prefijo = body.get("prefijo", "")
    desarrollo = body.get("desarrollo", "")
    from_me = body.get("fromMe", False)

    now = time.time()

    # ─── 0. Verificar si el teléfono está bloqueado ───
    phone_last10 = phone[-10:] if phone else ""
    if phone_last10 in BOT_BLOCKED_PHONES:
        print(f"[BOT] Teléfono {phone} está BLOQUEADO → ignorar")
        return JSONResponse({"process": False, "reason": "blocked_phone"})

    # ─── 1. Si fromMe → ¿es eco del bot o Esteban escribiendo? ───
    if from_me:
        last_bot = _bot_last_sent.get(phone, 0)
        seconds_since_bot = now - last_bot
        if seconds_since_bot < BOT_ECHO_WINDOW:
            # El bot acaba de responder → este fromMe es el eco del bot, ignorar
            print(f"[BOT] Eco del bot en {phone} (hace {seconds_since_bot:.0f}s) → ignorar")
            return JSONResponse({"process": False, "reason": "bot_echo"})
        else:
            # No hay respuesta reciente del bot → Esteban escribió manualmente → pausar
            _paused_chats[phone] = now
            _active_chats.pop(phone, None)
            if phone in _message_buffer:
                _message_buffer.pop(phone, None)
            print(f"[BOT] Esteban escribió en {phone} → bot pausado 4h")
            return JSONResponse({"process": False, "reason": "fromMe_paused"})

    # ─── 2. Verificar si el bot está pausado ───
    if phone in _paused_chats:
        elapsed = now - _paused_chats[phone]
        if elapsed < PAUSE_DURATION:
            print(f"[BOT] Chat {phone} pausado, faltan {round((PAUSE_DURATION - elapsed) / 60)}min")
            return JSONResponse({"process": False, "reason": "paused"})
        else:
            _paused_chats.pop(phone, None)  # Ya expiró la pausa

    # ─── 3. Verificar si hay conversación activa o si tiene keywords ───
    chat_active = _is_chat_active(phone)

    if not chat_active:
        # No hay conversación activa → verificar si el mensaje tiene keywords
        if _has_bot_keyword(message):
            # ¡Activar conversación!
            _active_chats[phone] = now
            print(f"[BOT] Keyword detectada en {phone} → conversación ACTIVADA")
        else:
            # No tiene keywords → ignorar, Esteban conversa normal
            print(f"[BOT] Mensaje de {phone} sin keywords, bot inactivo → ignorar")
            return JSONResponse({"process": False, "reason": "no_keywords"})

    # ─── 4. Conversación activa → acumular con debounce ───
    # Refrescar el timestamp de actividad
    _active_chats[phone] = now

    if phone not in _message_buffer:
        _message_buffer[phone] = {
            "messages": [],
            "name": name,
            "chatId": chat_id,
            "prefijo": prefijo,
            "desarrollo": desarrollo,
            "last_time": now,
            "sequence": 0,
        }

    buf = _message_buffer[phone]
    buf["messages"].append(message)
    buf["last_time"] = now
    buf["sequence"] += 1
    my_sequence = buf["sequence"]

    if prefijo and not buf["prefijo"]:
        buf["prefijo"] = prefijo
    if desarrollo and not buf["desarrollo"]:
        buf["desarrollo"] = desarrollo

    # Esperar 12 segundos para que termine de escribir
    await asyncio.sleep(12)

    # Verificar si llegaron más mensajes después del nuestro
    if phone in _message_buffer and _message_buffer[phone]["sequence"] != my_sequence:
        return JSONResponse({"process": False, "reason": "debounce_waiting"})

    # Somos el último mensaje, combinar todo y responder
    if phone in _message_buffer:
        final = _message_buffer.pop(phone)
        combined = "\n".join(final["messages"])

        # ─── Registrar prospecto en nuestra BD (buscar existente primero) ───
        try:
            referido = None
            if final["prefijo"]:
                referido = await get_user_by_prefijo(final["prefijo"])

            existente = await get_prospecto_by_telefono(phone)

            if existente:
                # Ya existe → actualizar campos faltantes y agregar historial
                prospecto_id = existente["id"]
                updates = {}
                if final["name"] and not existente.get("nombre_cliente"):
                    updates["nombre_cliente"] = final["name"]
                if final["desarrollo"]:
                    updates["desarrollo_interes"] = final["desarrollo"]
                if referido and not existente.get("referido_id"):
                    updates["referido_id"] = referido["id"]
                if updates:
                    await update_prospecto(prospecto_id, updates)
                # Agregar mensaje al historial
                from datetime import datetime as dt
                await agregar_historial_prospecto(prospecto_id, {
                    "tipo": "mensaje_chatbot",
                    "mensaje": combined,
                    "fecha": str(dt.now()),
                    "datos": {"desarrollo": final["desarrollo"]},
                })
                print(f"[PROSPECTO] Existente #{prospecto_id} actualizado para {phone}")
            else:
                # No existe → crear nuevo
                prospecto_id = await create_prospecto({
                    "referido_id": referido["id"] if referido else None,
                    "nombre_cliente": final["name"],
                    "telefono_cliente": phone,
                    "mensaje_original": combined,
                    "prefijo": final["prefijo"],
                    "desarrollo_interes": final["desarrollo"],
                    "estado": "nuevo",
                    "fuente": "chatbot",
                })
                print(f"[PROSPECTO] Nuevo #{prospecto_id} creado para {phone}")
        except Exception as e:
            print(f"[PROSPECTO] Error: {e}")

        # ─── Crear lead en Kommo (una vez cada 24h por telefono) ───
        await _create_kommo_lead(phone, final["name"])

        # ─── Marcar que el bot va a responder (para ignorar el eco fromMe) ───
        _bot_last_sent[phone] = time.time()

        return JSONResponse({
            "process": True,
            "phone": phone,
            "message": combined,
            "chatId": final["chatId"],
            "name": final["name"],
            "prefijo": final["prefijo"],
            "desarrollo": final["desarrollo"],
        })

    return JSONResponse({"process": False})


# ─── API: Disponibilidad de citas (para el chatbot) ───

@app.get("/api/citas/disponibilidad")
async def api_citas_disponibilidad(fecha: str, hora: str = None):
    """
    Consulta disponibilidad de citas para una fecha.
    - GET /api/citas/disponibilidad?fecha=2026-04-14
    - GET /api/citas/disponibilidad?fecha=2026-04-14&hora=10:00
    Retorna: citas del día, si la hora está ocupada, y horarios disponibles.
    """
    try:
        result = await check_disponibilidad_citas(fecha, hora)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/citas/registrar")
async def api_citas_registrar(request: Request):
    """
    Registra una cita confirmada desde n8n.
    Body: { telefono, nombre, fecha, hora, desarrollo, notas }
    Verifica disponibilidad antes de crear.
    """
    body = await request.json()
    telefono = body.get("telefono", "")
    nombre = body.get("nombre", "")
    fecha = body.get("fecha", "")
    hora = body.get("hora", "")
    desarrollo = body.get("desarrollo", "")
    notas = body.get("notas", "")

    if not fecha or not hora:
        return JSONResponse({"ok": False, "error": "Fecha y hora son requeridas"}, status_code=400)

    # Verificar disponibilidad
    disp = await check_disponibilidad_citas(fecha, hora)
    if disp["hora_solicitada_ocupada"]:
        return JSONResponse({
            "ok": False,
            "error": "Horario ocupado",
            "mensaje": f"Ya hay una cita agendada a esa hora. Horarios disponibles: {', '.join(disp['horarios_disponibles'])}",
            "horarios_disponibles": disp["horarios_disponibles"],
        })

    # Buscar prospecto por teléfono
    prospecto = await get_prospecto_by_telefono(telefono) if telefono else None
    prospecto_id = prospecto["id"] if prospecto else None

    # Calcular hora fin (1 hora después)
    from datetime import time as time_cls, datetime as dt_cls, timedelta
    hora_obj = time_cls.fromisoformat(hora if len(hora) == 5 else hora + ":00")
    hora_fin_dt = dt_cls.combine(dt_cls.today(), hora_obj) + timedelta(hours=1)
    hora_fin = hora_fin_dt.time().strftime("%H:%M")

    cita_id = await create_cita_chatbot({
        "prospecto_id": prospecto_id,
        "titulo": f"Visita {desarrollo} - {nombre}",
        "desarrollo": desarrollo,
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": hora_fin,
        "estado": "pendiente",
        "google_event_id": "",
        "notas": notas,
    })

    # Actualizar prospecto con datos de cita
    if prospecto_id:
        await update_prospecto(prospecto_id, {"estado": "cita_agendada"})
        await agregar_historial_prospecto(prospecto_id, {
            "tipo": "cita_agendada",
            "mensaje": f"Cita {fecha} a las {hora} - {desarrollo}",
            "fecha": str(dt_cls.now()),
            "datos": {"cita_id": cita_id, "fecha": fecha, "hora": hora},
        })

    print(f"[CITA] Nueva cita #{cita_id} — {nombre} → {fecha} {hora} ({desarrollo})")
    return JSONResponse({
        "ok": True,
        "cita_id": cita_id,
        "fecha": fecha,
        "hora": hora,
        "hora_fin": hora_fin,
        "desarrollo": desarrollo,
    })


# ─── API: Registro automatico de prospectos desde n8n/WhatsApp ───

@app.post("/api/prospectos/registrar")
async def api_registrar_prospecto(request: Request):
    """Endpoint para que n8n registre prospectos automaticamente desde WhatsApp."""
    body = await request.json()
    prefijo = body.get("prefijo", "").strip().upper()
    mensaje = body.get("mensaje", "")
    telefono = body.get("telefono", "")
    nombre = body.get("nombre", "")
    desarrollo = body.get("desarrollo", "")

    # Auto-detectar prefijo del mensaje si no viene explícito
    if not prefijo and mensaje:
        import re
        prefix_match = re.match(r'^([A-Za-z]{1,5})\s*[-–—]\s*', mensaje)
        if prefix_match:
            prefijo = prefix_match.group(1).upper()
            mensaje = mensaje[prefix_match.end():].strip()  # Limpiar prefijo del mensaje

    # Buscar referido por prefijo
    referido = None
    if prefijo:
        referido = await get_user_by_prefijo(prefijo)

    # Buscar si ya existe prospecto con ese teléfono
    existente = await get_prospecto_by_telefono(telefono) if telefono else None

    if existente:
        prospecto_id = existente["id"]
        updates = {}
        if nombre and not existente.get("nombre_cliente"):
            updates["nombre_cliente"] = nombre
        if desarrollo and not existente.get("desarrollo_interes"):
            updates["desarrollo_interes"] = desarrollo
        if referido and not existente.get("referido_id"):
            updates["referido_id"] = referido["id"]
        if updates:
            await update_prospecto(prospecto_id, updates)
        from datetime import datetime as dt
        await agregar_historial_prospecto(prospecto_id, {
            "tipo": "mensaje_whatsapp",
            "mensaje": mensaje,
            "fecha": str(dt.now()),
            "datos": {"desarrollo": desarrollo, "prefijo": prefijo},
        })
    else:
        data = {
            "referido_id": referido["id"] if referido else None,
            "nombre_cliente": nombre,
            "telefono_cliente": telefono,
            "mensaje_original": mensaje,
            "prefijo": prefijo,
            "desarrollo_interes": desarrollo,
            "estado": "nuevo",
            "fuente": "chatbot",
        }
        prospecto_id = await create_prospecto(data)

    return JSONResponse({
        "ok": True,
        "prospecto_id": prospecto_id,
        "referido": referido["nombre"] if referido else None,
    })


# ─── Páginas Públicas (web pública) ───

# Datos estáticos de desarrollos (editables desde aquí o futuro panel)
DESARROLLOS_DATA = {
    "carcamos-residencial": {
        "slug": "carcamos-residencial",
        "nombre": "Cárcamos Residencial",
        "ubicacion": "Cerca de ALAÏA, Guanajuato",
        "tipo": "Casas nuevas",
        "precio_desde": "$2,990,000 MXN",
        "unidades": "",
        "imagen": "/static/img/carcamos-hero.jpg",
        "descripcion_corta": "Casas nuevas residenciales en zona de alta plusvalía cerca de ALAÏA.",
        "descripcion": "Cárcamos Residencial es un desarrollo de casas nuevas residenciales ubicado en una de las zonas con mayor crecimiento y plusvalía en Guanajuato.\n\nIdeal para familias y profesionistas que buscan un hogar con concepto moderno y funcional, con opción de personalización de acabados.",
        "diferenciales": [
            "Zona con alta plusvalía",
            "Ideal para familias",
            "Personalización de acabados",
            "Concepto moderno y funcional",
            "Promoción vigente",
        ],
        "tags": ["Alta plusvalía", "Casas nuevas", "Personalizable"],
        "pdf_url": "/static/docs/carcamos-residencial.pdf",
    },
    "privada-del-fresno": {
        "slug": "privada-del-fresno",
        "nombre": "Privada del Fresno",
        "ubicacion": "Cerca de Las Teresas, Guanajuato",
        "tipo": "24 casas exclusivas",
        "precio_desde": "Consultar",
        "unidades": "24",
        "imagen": "/static/img/fresno-hero.png",
        "descripcion_corta": "Desarrollo exclusivo de solo 24 casas con gimnasio y áreas verdes.",
        "descripcion": "Privada del Fresno es un desarrollo exclusivo de solo 24 casas, lo que garantiza baja densidad y alta plusvalía.\n\nCuenta con amenidades como gimnasio y áreas verdes. Esquemas de preventa con enganches accesibles y posibilidad de elegir acabados.\n\nEntrega aproximada en 7 meses con seguimiento de obra mensual.",
        "diferenciales": [
            "Solo 24 casas",
            "Baja densidad",
            "Gimnasio y áreas verdes",
            "Enganches accesibles",
            "Elegir acabados",
            "Entrega en 7 meses",
        ],
        "tags": ["Exclusivo", "Preventa", "Amenidades"],
        "pdf_url": "/static/docs/privada-del-fresno.pdf",
    },
}


@app.get("/admin/desarrollos", response_class=HTMLResponse)
async def admin_desarrollos_page(request: Request, msg: Optional[str] = None, msg_type: str = "ok"):
    """Panel de gestión de desarrollos."""
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    # Verificar qué imágenes existen realmente
    devs_con_img = {}
    for slug, d in DESARROLLOS_DATA.items():
        d_copy = dict(d)
        img_path = BASE_DIR / "static" / "uploads" / f"{slug}-hero.jpg"
        img_path_png = BASE_DIR / "static" / "uploads" / f"{slug}-hero.png"
        if img_path.exists():
            d_copy["imagen_actual"] = f"/static/uploads/{slug}-hero.jpg"
        elif img_path_png.exists():
            d_copy["imagen_actual"] = f"/static/uploads/{slug}-hero.png"
        else:
            d_copy["imagen_actual"] = None
        devs_con_img[slug] = d_copy
    return templates.TemplateResponse(request=request, name="admin_desarrollos.html", context={
        "user": user,
        "desarrollos": devs_con_img,
        "msg": msg,
        "msg_type": msg_type,
    })


@app.post("/admin/desarrollos/{slug}/imagen")
async def admin_upload_desarrollo_imagen(request: Request, slug: str, imagen: UploadFile = File(...)):
    """Sube imagen hero de un desarrollo."""
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    if slug not in DESARROLLOS_DATA:
        return RedirectResponse("/admin/desarrollos?msg=Desarrollo no encontrado&msg_type=err", status_code=302)

    # Validar tipo
    content_type = imagen.content_type or ""
    if not content_type.startswith("image/"):
        return RedirectResponse("/admin/desarrollos?msg=Solo se permiten imágenes&msg_type=err", status_code=302)

    # Determinar extensión
    ext = "jpg"
    if "png" in content_type:
        ext = "png"
    elif "webp" in content_type:
        ext = "webp"

    filename = f"{slug}-hero.{ext}"
    filepath = UPLOAD_DIR / filename

    # Guardar archivo
    content = await imagen.read()
    with open(filepath, "wb") as f:
        f.write(content)

    # Actualizar DESARROLLOS_DATA en memoria
    DESARROLLOS_DATA[slug]["imagen"] = f"/static/uploads/{filename}"

    return RedirectResponse(f"/admin/desarrollos?msg=Imagen de {DESARROLLOS_DATA[slug]['nombre']} actualizada&msg_type=ok", status_code=302)


@app.post("/admin/desarrollos/{slug}/datos")
async def admin_update_desarrollo_datos(
    request: Request, slug: str,
    nombre: str = Form(""), ubicacion: str = Form(""),
    precio_desde: str = Form(""), tipo: str = Form(""),
    unidades: str = Form(""), descripcion_corta: str = Form(""),
    descripcion: str = Form(""), diferenciales: str = Form(""),
    tags: str = Form(""), pdf_url: str = Form(""),
):
    """Actualiza datos de un desarrollo."""
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    if slug not in DESARROLLOS_DATA:
        return RedirectResponse("/admin/desarrollos?msg=Desarrollo no encontrado&msg_type=err", status_code=302)

    d = DESARROLLOS_DATA[slug]
    if nombre:
        d["nombre"] = nombre
    if ubicacion:
        d["ubicacion"] = ubicacion
    if precio_desde:
        d["precio_desde"] = precio_desde
    if tipo:
        d["tipo"] = tipo
    d["unidades"] = unidades
    if descripcion_corta:
        d["descripcion_corta"] = descripcion_corta
    if descripcion:
        d["descripcion"] = descripcion
    if diferenciales:
        d["diferenciales"] = [x.strip() for x in diferenciales.split(",") if x.strip()]
    if tags:
        d["tags"] = [x.strip() for x in tags.split(",") if x.strip()]
    if pdf_url:
        d["pdf_url"] = pdf_url

    return RedirectResponse(f"/admin/desarrollos?msg=Datos de {d['nombre']} actualizados&msg_type=ok", status_code=302)


# ─── Configuración del Sitio ───

@app.get("/admin/config", response_class=HTMLResponse)
async def admin_config_page(request: Request, msg: Optional[str] = None):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    config = await get_all_site_config()
    return templates.TemplateResponse(request=request, name="admin_config.html", context={
        "user": user, "c": config, "msg": msg,
    })


@app.post("/admin/config")
async def admin_config_save(request: Request):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    form = await request.form()
    # Lista de todos los campos del formulario de configuración
    campos = [
        "hero_titulo", "hero_subtitulo",
        "telefono", "whatsapp", "email", "wa_mensaje",
        "agente_nombre", "agente_cargo", "agente_bio",
        "empresa_desc1", "empresa_desc2",
        "stat1_num", "stat1_label", "stat2_num", "stat2_label",
        "stat3_num", "stat3_label", "stat4_num", "stat4_label",
        "ciudades",
        "seo_titulo", "seo_descripcion",
        "cta_titulo", "cta_subtitulo", "cta_boton",
        "footer_texto", "footer_zonas",
        # Vender/Rentar
        "vender_titulo", "vender_subtitulo",
        "vender_stat1_num", "vender_stat1_label",
        "vender_stat2_num", "vender_stat2_label",
        "vender_stat3_num", "vender_stat3_label",
    ]
    # Agregar campos dinámicos de beneficios
    for i in range(1, 7):
        campos.extend([
            f"vender_beneficio{i}_icono",
            f"vender_beneficio{i}_titulo",
            f"vender_beneficio{i}_desc",
        ])
    for campo in campos:
        valor = form.get(campo, "").strip()
        if valor:
            await set_site_config(campo, valor)
    return RedirectResponse("/admin/config?msg=Configuración guardada correctamente", status_code=302)


async def load_public_config() -> dict:
    """Carga toda la config del sitio para las páginas públicas."""
    config = await get_all_site_config()
    # Valores por defecto
    defaults = {
        "hero_titulo": "Tu {gold}hogar ideal{/gold} en Guanajuato",
        "hero_subtitulo": "Compra, venta y renta de propiedades con asesoría legal completa y acompañamiento de inicio a fin.",
        "telefono": "4737365219",
        "whatsapp": "524737365219",
        "email": "irealestatemx@gmail.com",
        "wa_mensaje": "Hola, me interesa información sobre sus propiedades",
        "agente_nombre": "Esteban Castellanos",
        "agente_cargo": "CEO / Fundador",
        "agente_bio": "Abogado especialista en bienes raíces. Más de 650 operaciones cerradas exitosamente.",
        "empresa_desc1": "Somos una empresa de asesores inmobiliarios certificados en Guanajuato, especializados en compra, venta y renta de propiedades con acompañamiento legal completo.",
        "empresa_desc2": "Con más de 15 años de experiencia en bienes raíces y derecho inmobiliario, ofrecemos certeza jurídica, contratos claros y estrategias de inversión personalizadas.",
        "stat1_num": "650+", "stat1_label": "Operaciones exitosas",
        "stat2_num": "15+", "stat2_label": "Años de experiencia",
        "stat3_num": "100%", "stat3_label": "Respaldo legal",
        "stat4_num": "3", "stat4_label": "Ciudades activas",
        "ciudades": "Guanajuato, León, Irapuato",
        "seo_titulo": "iRealEstateMx — Inmobiliaria en Guanajuato",
        "seo_descripcion": "Compra, venta y renta de propiedades en Guanajuato. Casas, departamentos y terrenos con asesoría legal completa.",
        "cta_titulo": "¿Listo para invertir?",
        "cta_subtitulo": "Agenda una visita o solicita información sin compromiso",
        "cta_boton": "Contactar por WhatsApp",
        "footer_texto": "Asesores inmobiliarios certificados en Guanajuato. Compra, venta y renta con respaldo legal completo.",
        "footer_zonas": "Guanajuato, León e Irapuato",
        # Sección Vender/Rentar
        "vender_titulo": "Vende o Renta tu {gold}Propiedad{/gold}",
        "vender_subtitulo": "Nos encargamos de todo: desde la publicación hasta el cierre. Déjanos tu información y te contactamos en menos de 24 horas.",
        "vender_stat1_num": "50+", "vender_stat1_label": "Propiedades publicadas",
        "vender_stat2_num": "95%", "vender_stat2_label": "Clientes satisfechos",
        "vender_stat3_num": "30", "vender_stat3_label": "Días promedio de venta",
        "vender_beneficio1_icono": "📸", "vender_beneficio1_titulo": "Contenido profesional", "vender_beneficio1_desc": "Fotos, descripciones y publicaciones diseñadas para atraer compradores",
        "vender_beneficio2_icono": "📊", "vender_beneficio2_titulo": "Análisis de mercado", "vender_beneficio2_desc": "Definimos el precio justo basado en datos reales del mercado",
        "vender_beneficio3_icono": "🔑", "vender_beneficio3_titulo": "Gestión integral", "vender_beneficio3_desc": "Desde la publicación hasta la firma. Visitas, negociación y cierre",
        "vender_beneficio4_icono": "📱", "vender_beneficio4_titulo": "Máxima exposición", "vender_beneficio4_desc": "Tu propiedad en nuestro sitio, Instagram, WhatsApp y portales inmobiliarios",
        "vender_beneficio5_icono": "💰", "vender_beneficio5_titulo": "Sin costo inicial", "vender_beneficio5_desc": "Solo cobramos al cerrar la operación. Sin riesgo para ti",
        "vender_beneficio6_icono": "⚡", "vender_beneficio6_titulo": "Respuesta rápida", "vender_beneficio6_desc": "Te contactamos en menos de 24 horas con un plan personalizado",
    }
    for k, v in defaults.items():
        if k not in config or not config[k]:
            config[k] = v
    return config


@app.get("/web")
async def public_home(request: Request):
    """Página principal pública."""
    props = await get_all_properties(active_only=True, limit=12, offset=0, publicada_web=True)
    desarrollos = list(DESARROLLOS_DATA.values())
    c = await load_public_config()
    return templates.TemplateResponse(request=request, name="public_home.html", context={
        "propiedades": props,
        "desarrollos": desarrollos,
        "desarrollos_dict": DESARROLLOS_DATA,
        "c": c,
    })


@app.get("/propiedades")
async def public_propiedades(
    request: Request,
    operacion: Optional[str] = None,
    tipo: Optional[str] = None,
    ciudad: Optional[str] = None,
    precio_max: Optional[str] = None,
    limit: int = 12,
    offset: int = 0,
):
    """Listado público de propiedades con filtros."""
    precio_max_f = float(precio_max) if precio_max else None
    if any([operacion, tipo, ciudad, precio_max_f]):
        props = await search_properties(
            ciudad=ciudad, operacion=operacion, tipo=tipo,
            precio_max=precio_max_f, limit=limit, publicada_web=True
        )
        total = len(props)
    else:
        props = await get_all_properties(active_only=True, limit=limit, offset=offset, publicada_web=True)
        total = await count_properties(active_only=True, publicada_web=True)

    c = await load_public_config()
    return templates.TemplateResponse(request=request, name="public_propiedades.html", context={
        "propiedades": props,
        "total": total,
        "tiene_mas": total > offset + limit,
        "filtro_operacion": operacion or "",
        "filtro_tipo": tipo or "",
        "filtro_ciudad": ciudad or "",
        "filtro_precio_max": precio_max or "",
        "desarrollos_dict": DESARROLLOS_DATA,
        "c": c,
    })


@app.get("/propiedad/{prop_id}")
async def public_propiedad_detalle(request: Request, prop_id: int):
    """Detalle público de una propiedad."""
    prop = await get_property_by_id(prop_id)
    if not prop:
        return RedirectResponse("/propiedades", status_code=302)

    # Parsear fotos extra
    fotos_extra = prop.get("fotos_extra_urls") or []
    if isinstance(fotos_extra, str):
        import json as _json
        try:
            fotos_extra = _json.loads(fotos_extra)
        except Exception:
            fotos_extra = []

    # Parsear amenidades
    amenidades = prop.get("amenidades") or []
    if isinstance(amenidades, str):
        import json as _json
        try:
            amenidades = _json.loads(amenidades)
        except Exception:
            amenidades = []

    # Buscar propiedades similares (misma ciudad u operacion, excluyendo la actual)
    similares = []
    try:
        all_similar = await search_properties(
            ciudad=prop.get("ciudad"), operacion=prop.get("operacion"),
            limit=5, publicada_web=True
        )
        similares = [s for s in all_similar if s["id"] != prop_id][:4]
    except Exception:
        pass

    # Resolver nombre del desarrollo si tiene uno vinculado
    desarrollo_info = DESARROLLOS_DATA.get(prop.get("desarrollo_slug") or "") if prop.get("desarrollo_slug") else None

    c = await load_public_config()
    return templates.TemplateResponse(request=request, name="public_propiedad.html", context={
        "prop": prop,
        "fotos_extra": fotos_extra,
        "amenidades": amenidades,
        "similares": similares,
        "desarrollo": desarrollo_info,
        "desarrollos_dict": DESARROLLOS_DATA,
        "c": c,
    })


@app.get("/desarrollos")
async def public_desarrollos(request: Request):
    """Listado de desarrollos."""
    c = await load_public_config()
    return templates.TemplateResponse(request=request, name="public_desarrollos.html", context={
        "desarrollos": list(DESARROLLOS_DATA.values()),
        "c": c,
    })


@app.get("/desarrollo/{slug}")
async def public_desarrollo_detalle(request: Request, slug: str):
    """Detalle de un desarrollo con sus propiedades."""
    desarrollo = DESARROLLOS_DATA.get(slug)
    if not desarrollo:
        return templates.TemplateResponse(request=request, name="public_desarrollos.html", context={
            "desarrollos": list(DESARROLLOS_DATA.values()),
        })

    # Buscar propiedades vinculadas al desarrollo por slug
    props_dev = await get_properties_by_desarrollo(slug)

    c = await load_public_config()
    return templates.TemplateResponse(request=request, name="public_desarrollo.html", context={
        "desarrollo": desarrollo,
        "propiedades": props_dev,
        "c": c,
    })


# ─── Propiedades Vendidas ───

@app.get("/vendidas", response_class=HTMLResponse)
async def public_vendidas(request: Request):
    """Listado de propiedades vendidas / cerradas."""
    # Buscar propiedades con vendida=True
    query = """
    SELECT * FROM propiedades WHERE vendida = TRUE ORDER BY fecha_venta DESC NULLS LAST, updated_at DESC LIMIT 50
    """
    rows = await database.fetch_all(query=query)
    props = [dict(r._mapping) for r in rows]
    c = await load_public_config()
    return templates.TemplateResponse(request=request, name="public_vendidas.html", context={
        "propiedades": props,
        "c": c,
    })


@app.post("/dashboard/marcar-vendida/{prop_id}")
async def marcar_vendida(request: Request, prop_id: int):
    """Marca una propiedad como vendida desde el dashboard."""
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    from datetime import datetime as dt
    await update_property(prop_id, {"vendida": True, "fecha_venta": dt.now()})
    return RedirectResponse("/dashboard?msg=Propiedad marcada como vendida", status_code=302)


# ─── Páginas Legales ───

@app.get("/aviso-de-privacidad", response_class=HTMLResponse)
async def aviso_privacidad(request: Request):
    c = await load_public_config()
    return templates.TemplateResponse(request=request, name="public_privacidad.html", context={"c": c})


@app.get("/terminos-y-condiciones", response_class=HTMLResponse)
async def terminos_condiciones(request: Request):
    c = await load_public_config()
    return templates.TemplateResponse(request=request, name="public_terminos.html", context={"c": c})


# ─── Vende/Renta tu Propiedad ───

@app.get("/vender", response_class=HTMLResponse)
async def public_vender(request: Request):
    """Página para captar propietarios que quieran vender o rentar."""
    c = await load_public_config()
    return templates.TemplateResponse(request=request, name="public_vender.html", context={
        "c": c,
        "enviado": False,
    })


@app.post("/vender", response_class=HTMLResponse)
async def public_vender_submit(
    request: Request,
    nombre: str = Form(...),
    telefono: str = Form(...),
    email: Optional[str] = Form(None),
    operacion: str = Form(...),
    tipo_propiedad: str = Form(...),
    ciudad: str = Form("León"),
    mensaje: Optional[str] = Form(None),
):
    """Recibe el formulario de propietarios y crea un prospecto."""
    # Verificar si ya existe un prospecto con ese teléfono
    existente = await get_prospecto_by_telefono(telefono)
    nota = f"[WEB-VENDEDOR] Quiere {operacion.lower()} un(a) {tipo_propiedad} en {ciudad}."
    if mensaje:
        nota += f" Mensaje: {mensaje}"

    if existente:
        prospecto_id = existente["id"]
        updates = {}
        if nombre and not existente.get("nombre_cliente"):
            updates["nombre_cliente"] = nombre
        if email and not existente.get("email_cliente"):
            updates["email_cliente"] = email
        if updates:
            await update_prospecto(prospecto_id, updates)
        await agregar_historial_prospecto(prospecto_id, {
            "tipo": "formulario_vendedor",
            "nota": nota,
            "operacion": operacion,
            "tipo_propiedad": tipo_propiedad,
            "ciudad": ciudad,
        })
    else:
        prospecto_id = await create_prospecto({
            "nombre_cliente": nombre,
            "telefono_cliente": telefono,
            "email_cliente": email or "",
            "mensaje_original": nota,
            "desarrollo_interes": "",
            "estado": "nuevo",
            "fuente": "web_vendedor",
            "historial": [{
                "tipo": "formulario_vendedor",
                "nota": nota,
                "operacion": operacion,
                "tipo_propiedad": tipo_propiedad,
                "ciudad": ciudad,
            }],
        })

    # ─── Notificar a admins por email + WhatsApp + notificación interna ───
    lead_meta = {
        "nombre": nombre,
        "telefono": telefono,
        "email": email or "No proporcionado",
        "operacion": operacion,
        "tipo_propiedad": tipo_propiedad,
        "ciudad": ciudad,
        "mensaje": mensaje or "Sin mensaje adicional",
        "prospecto_id": prospecto_id,
    }

    email_body = f"""
    <strong>Nuevo lead de propietario desde la web:</strong><br><br>
    <table style="border-collapse:collapse;width:100%;font-size:14px;">
      <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#888;width:120px;">Nombre</td><td style="padding:8px;border-bottom:1px solid #eee;font-weight:600;">{nombre}</td></tr>
      <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#888;">Teléfono</td><td style="padding:8px;border-bottom:1px solid #eee;font-weight:600;"><a href="tel:+52{telefono}">{telefono}</a></td></tr>
      <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#888;">Email</td><td style="padding:8px;border-bottom:1px solid #eee;">{email or 'No proporcionado'}</td></tr>
      <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#888;">Operación</td><td style="padding:8px;border-bottom:1px solid #eee;font-weight:600;">{operacion}</td></tr>
      <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#888;">Tipo</td><td style="padding:8px;border-bottom:1px solid #eee;">{tipo_propiedad}</td></tr>
      <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#888;">Ciudad</td><td style="padding:8px;border-bottom:1px solid #eee;">{ciudad}</td></tr>
      <tr><td style="padding:8px;color:#888;">Mensaje</td><td style="padding:8px;">{mensaje or 'Sin mensaje adicional'}</td></tr>
    </table>
    <br>
    <a href="https://irealestatemx.com/admin/prospectos" style="background:#c9a227;color:#1a3c5e;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:700;display:inline-block;">
      Ver en el panel
    </a>
    """

    try:
        admin_users = await get_users_by_rol("admin")
        for admin in admin_users:
            # Notificación interna en BD
            await crear_notificacion(
                tipo="lead_vendedor",
                user_id=admin["id"],
                propiedad_id=None,
                metadata=lead_meta,
            )
            admin_email = admin.get("email", "")
            admin_nombre = admin.get("nombre", "Admin")
            # Email al admin
            if admin_email:
                await enviar_email_notificacion(
                    to_email=admin_email,
                    to_name=admin_nombre,
                    asunto=f"Nuevo lead: {nombre} quiere {operacion.lower()} {tipo_propiedad} en {ciudad}",
                    cuerpo=email_body,
                )
            # WhatsApp al admin (usa plantilla NOTIF_MENSAJES["lead_vendedor"])
            admin_tel = admin.get("telefono", "")
            if admin_tel:
                await enviar_whatsapp_waha(
                    tipo="lead_vendedor",
                    destinatario={"telefono": admin_tel, "nombre": admin_nombre},
                    metadata=lead_meta,
                )
    except Exception as e:
        print(f"[VENDER] Error notificando admins: {e}")

    c = await load_public_config()
    return templates.TemplateResponse(request=request, name="public_vender.html", context={
        "c": c,
        "enviado": True,
    })


# ─── SEO: Sitemap y Robots ───

@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    return """User-agent: *
Allow: /
Disallow: /admin/
Disallow: /dashboard
Disallow: /login
Disallow: /generate
Disallow: /api/

Sitemap: https://irealestatemx.com/sitemap.xml
"""


@app.get("/sitemap.xml")
async def sitemap_xml():
    from datetime import datetime as dt
    props = await get_all_properties(active_only=True, limit=500, publicada_web=True)
    now = dt.utcnow().strftime("%Y-%m-%d")

    urls = []
    # Páginas estáticas
    static_pages = [
        ("/", "1.0", "weekly"),
        ("/propiedades", "0.9", "daily"),
        ("/desarrollos", "0.8", "weekly"),
        ("/propiedades?operacion=venta", "0.8", "daily"),
        ("/propiedades?operacion=renta", "0.8", "daily"),
        ("/propiedades?operacion=preventa", "0.8", "weekly"),
        ("/vender", "0.8", "monthly"),
        ("/vendidas", "0.5", "weekly"),
        ("/aviso-de-privacidad", "0.3", "yearly"),
        ("/terminos-y-condiciones", "0.3", "yearly"),
    ]
    for path, priority, freq in static_pages:
        urls.append(f"""  <url>
    <loc>https://irealestatemx.com{path}</loc>
    <lastmod>{now}</lastmod>
    <changefreq>{freq}</changefreq>
    <priority>{priority}</priority>
  </url>""")

    # Desarrollos
    for slug, dev in DESARROLLOS_DATA.items():
        urls.append(f"""  <url>
    <loc>https://irealestatemx.com/desarrollo/{slug}</loc>
    <lastmod>{now}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>""")

    # Propiedades individuales
    for p in props:
        lastmod = p.get("updated_at") or p.get("created_at")
        lastmod_str = lastmod.strftime("%Y-%m-%d") if lastmod else now
        urls.append(f"""  <url>
    <loc>https://irealestatemx.com/propiedad/{p['id']}</loc>
    <lastmod>{lastmod_str}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.7</priority>
  </url>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""
    return StarletteResponse(content=xml, media_type="application/xml")


# ─── API REST de Propiedades (para web, chatbot, n8n) ───

@app.get("/api/propiedades")
async def api_list_properties(
    ciudad: Optional[str] = None,
    operacion: Optional[str] = None,
    tipo: Optional[str] = None,
    precio_min: Optional[float] = None,
    precio_max: Optional[float] = None,
    limit: int = 20,
    offset: int = 0,
    activas: bool = True,
):
    """Lista propiedades con filtros. Usado por web, chatbot y n8n."""
    if any([ciudad, operacion, tipo, precio_min, precio_max]):
        props = await search_properties(
            ciudad=ciudad, operacion=operacion, tipo=tipo,
            precio_min=precio_min, precio_max=precio_max, limit=limit
        )
    else:
        props = await get_all_properties(active_only=activas, limit=limit, offset=offset)

    total = await count_properties(active_only=activas)

    # Serializar datetimes y Decimals para JSON
    for p in props:
        for k, v in p.items():
            if hasattr(v, 'isoformat'):
                p[k] = v.isoformat()
            elif isinstance(v, (int, float, str, bool, list, dict)) or v is None:
                pass
            else:
                p[k] = str(v)

    return JSONResponse({"total": total, "propiedades": props})


@app.get("/api/propiedades/stats/resumen")
async def api_stats():
    """Estadisticas rapidas para dashboard."""
    total = await count_properties(active_only=False)
    activas = await count_properties(active_only=True)
    return JSONResponse({
        "total": total,
        "activas": activas,
        "inactivas": total - activas,
    })


@app.get("/api/propiedades/{prop_id}")
async def api_get_property(prop_id: int):
    """Detalle de una propiedad por ID."""
    prop = await get_property_by_id(prop_id)
    if not prop:
        return JSONResponse({"error": "Propiedad no encontrada"}, status_code=404)

    for k, v in prop.items():
        if hasattr(v, 'isoformat'):
            prop[k] = v.isoformat()
        elif isinstance(v, (int, float, str, bool, list, dict)) or v is None:
            pass
        else:
            prop[k] = str(v)

    return JSONResponse({"propiedad": prop})


@app.patch("/api/propiedades/{prop_id}")
async def api_update_property(prop_id: int, request: Request):
    """Actualiza campos de una propiedad (ej: marcar publicada, desactivar)."""
    body = await request.json()
    existing = await get_property_by_id(prop_id)
    if not existing:
        return JSONResponse({"error": "Propiedad no encontrada"}, status_code=404)
    ok = await update_property(prop_id, body)
    return JSONResponse({"ok": ok, "id": prop_id})


@app.delete("/api/propiedades/{prop_id}")
async def api_deactivate_property(prop_id: int):
    """Desactiva una propiedad (soft delete)."""
    existing = await get_property_by_id(prop_id)
    if not existing:
        return JSONResponse({"error": "Propiedad no encontrada"}, status_code=404)
    await toggle_property(prop_id, active=False)
    return JSONResponse({"ok": True, "id": prop_id, "activa": False})


@app.post("/api/propiedades/{prop_id}/reactivar")
async def api_reactivate_property(prop_id: int):
    """Reactiva una propiedad desactivada."""
    existing = await get_property_by_id(prop_id)
    if not existing:
        return JSONResponse({"error": "Propiedad no encontrada"}, status_code=404)
    await toggle_property(prop_id, active=True)
    return JSONResponse({"ok": True, "id": prop_id, "activa": True})


# ─── API REST de Desarrollos (para chatbot, web, n8n) ───

@app.get("/api/desarrollos")
async def api_list_desarrollos(
    texto: Optional[str] = None,
    ciudad: Optional[str] = None,
):
    """Lista desarrollos con busqueda opcional."""
    if texto or ciudad:
        devs = await search_desarrollos(texto=texto, ciudad=ciudad)
    else:
        devs = await get_all_desarrollos()
    for d in devs:
        for k, v in d.items():
            if hasattr(v, 'isoformat'):
                d[k] = v.isoformat()
            elif not isinstance(v, (int, float, str, bool, list, dict, type(None))):
                d[k] = str(v)
    return JSONResponse({"desarrollos": devs})


@app.get("/api/desarrollos/{dev_id}")
async def api_get_desarrollo(dev_id: int):
    """Detalle de un desarrollo por ID."""
    dev = await get_desarrollo_by_id(dev_id)
    if not dev:
        return JSONResponse({"error": "Desarrollo no encontrado"}, status_code=404)
    for k, v in dev.items():
        if hasattr(v, 'isoformat'):
            dev[k] = v.isoformat()
        elif not isinstance(v, (int, float, str, bool, list, dict, type(None))):
            dev[k] = str(v)
    return JSONResponse({"desarrollo": dev})


@app.post("/api/desarrollos")
async def api_create_desarrollo(request: Request):
    """Crea un nuevo desarrollo."""
    body = await request.json()
    dev_id = await save_desarrollo(body)
    return JSONResponse({"ok": True, "id": dev_id})


@app.patch("/api/desarrollos/{dev_id}")
async def api_update_desarrollo(dev_id: int, request: Request):
    """Actualiza un desarrollo."""
    body = await request.json()
    existing = await get_desarrollo_by_id(dev_id)
    if not existing:
        return JSONResponse({"error": "Desarrollo no encontrado"}, status_code=404)
    ok = await update_desarrollo(dev_id, body)
    return JSONResponse({"ok": ok, "id": dev_id})


# ─── Endpoint especial para el chatbot (busca en propiedades + desarrollos) ───

@app.get("/api/chatbot/buscar")
async def api_chatbot_search(
    q: Optional[str] = None,
    ciudad: Optional[str] = None,
    operacion: Optional[str] = None,
    tipo: Optional[str] = None,
    precio_min: Optional[float] = None,
    precio_max: Optional[float] = None,
):
    """Busca en propiedades Y desarrollos. Pensado para el chatbot de WhatsApp."""
    props = await search_properties(
        ciudad=ciudad, operacion=operacion, tipo=tipo,
        precio_min=precio_min, precio_max=precio_max, limit=10
    )
    devs = await search_desarrollos(texto=q, ciudad=ciudad)

    # Formatear propiedades para respuesta del chatbot
    props_resumen = []
    for p in props:
        props_resumen.append({
            "id": p["id"],
            "tipo": "propiedad",
            "nombre": f"{p.get('tipo_propiedad', '')} en {p.get('direccion', '')}",
            "operacion": p.get("operacion", ""),
            "precio": str(p.get("precio_formateado", "")),
            "ciudad": p.get("ciudad", ""),
            "recamaras": p.get("recamaras"),
            "banos": p.get("banos"),
            "metros": p.get("metros_construidos"),
            "descripcion": (p.get("descripcion_profesional", "") or "")[:300],
            "foto": p.get("foto_portada_url"),
            "agente_nombre": p.get("agente_nombre"),
            "agente_telefono": p.get("agente_telefono"),
        })

    devs_resumen = []
    for d in devs:
        devs_resumen.append({
            "id": d["id"],
            "tipo": "desarrollo",
            "nombre": d.get("nombre", ""),
            "ubicacion": d.get("ubicacion", ""),
            "ciudad": d.get("ciudad", ""),
            "precio_desde": str(d.get("precio_desde", "")),
            "precio_hasta": str(d.get("precio_hasta", "")),
            "descripcion": (d.get("descripcion", "") or "")[:300],
            "caracteristicas": d.get("caracteristicas"),
            "amenidades": d.get("amenidades", []),
            "pdf_url": d.get("pdf_url"),
            "foto": d.get("foto_portada_url"),
            "agente_nombre": d.get("agente_nombre"),
            "agente_telefono": d.get("agente_telefono"),
        })

    return JSONResponse({
        "propiedades": props_resumen,
        "desarrollos": devs_resumen,
        "total": len(props_resumen) + len(devs_resumen),
    })


@app.post("/generate", response_class=HTMLResponse)
async def generate(
    request: Request,
    nombre_propiedad: Optional[str] = Form(None),
    tipo_propiedad: str = Form(...),
    operacion: str = Form(...),
    direccion: str = Form(...),
    latitud: Optional[str] = Form(None),
    longitud: Optional[str] = Form(None),
    ciudad: str = Form(...),
    estado: str = Form(...),
    precio: str = Form(...),
    recamaras: Optional[str] = Form(None),
    banos: Optional[str] = Form(None),
    metros_construidos: Optional[str] = Form(None),
    metros_terreno: Optional[str] = Form(None),
    estacionamientos: Optional[str] = Form(None),
    descripcion_agente: Optional[str] = Form(None),
    agente_nombre: str = Form(...),
    agente_telefono: str = Form(...),
    agente_email: str = Form(...),
    agente_instagram: Optional[str] = Form(None),
    agente_inmobiliaria: Optional[str] = Form(None),
    fotos: List[UploadFile] = File(default=[]),
    desarrollo_slug: Optional[str] = Form(None),
    # ─── Nuevos campos del wizard ───
    amenidades_custom: Optional[str] = Form(None),
    video_tipo: Optional[str] = Form("reel"),
    voice_over_enabled: Optional[str] = Form(None),
    voice_gender: Optional[str] = Form("feminine"),
    voice_context: Optional[str] = Form(None),
    # Escenas del video (texto del guión)
    scene_fachada_text: Optional[str] = Form(None),
    scene_sala_text: Optional[str] = Form(None),
    scene_cocina_text: Optional[str] = Form(None),
    scene_recamara_text: Optional[str] = Form(None),
    scene_bano_text: Optional[str] = Form(None),
    scene_cierre_text: Optional[str] = Form(None),
    # Fotos por escena
    foto_hero_pdf: Optional[UploadFile] = File(None),
    scene_fachada: Optional[UploadFile] = File(None),
    scene_sala: Optional[UploadFile] = File(None),
    scene_cocina: Optional[UploadFile] = File(None),
    scene_recamara: Optional[UploadFile] = File(None),
    scene_bano: Optional[UploadFile] = File(None),
    scene_cierre: Optional[UploadFile] = File(None),
    # Qué generar
    gen_descripcion: Optional[str] = Form(None),
    gen_instagram_copy: Optional[str] = Form(None),
    gen_pdf: Optional[str] = Form(None),
    gen_ig_post: Optional[str] = Form(None),
    gen_ig_story: Optional[str] = Form(None),
    gen_ig_carousel: Optional[str] = Form(None),
    gen_video: Optional[str] = Form(None),
):
    # Auth check
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    # Solo admin/agente pueden subir propiedades
    user_check = await require_auth(request)
    if user_check and user_check["rol"] in ("vendedor", "comprador", "referido"):
        return RedirectResponse("/", status_code=302)

    # Recoger amenidades desde el form (checkboxes)
    form_data = await request.form()
    amenidades = form_data.getlist("amenidades")
    voice_tones = form_data.getlist("voice_tone")

    # Agregar amenidades personalizadas (separadas por coma)
    if amenidades_custom and amenidades_custom.strip():
        custom_list = [a.strip() for a in amenidades_custom.split(",") if a.strip()]
        amenidades = list(amenidades) + custom_list

    # Guardar fotos subidas
    session_id = str(uuid.uuid4())
    session_upload_dir = UPLOAD_DIR / session_id
    session_upload_dir.mkdir(parents=True, exist_ok=True)

    foto_portada_url = None
    fotos_extra_urls = []

    valid_fotos = [f for f in fotos if f.filename and f.size > 0]

    for i, foto in enumerate(valid_fotos):
        ext = Path(foto.filename).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            continue
        filename = f"{i:03d}{ext}"
        dest = session_upload_dir / filename
        with open(dest, "wb") as buffer:
            shutil.copyfileobj(foto.file, buffer)
        url = f"/static/uploads/{session_id}/{filename}"
        if i == 0:
            foto_portada_url = url
        else:
            fotos_extra_urls.append(url)

    # Guardar foto hero panorámica para PDF (opcional)
    foto_hero_pdf_url = None
    if foto_hero_pdf and foto_hero_pdf.filename and foto_hero_pdf.size > 0:
        ext = Path(foto_hero_pdf.filename).suffix.lower()
        if ext in {".jpg", ".jpeg", ".png", ".webp"}:
            fname = f"hero_pdf{ext}"
            dest = session_upload_dir / fname
            with open(dest, "wb") as buffer:
                shutil.copyfileobj(foto_hero_pdf.file, buffer)
            foto_hero_pdf_url = f"/static/uploads/{session_id}/{fname}"

    # Guardar fotos de escenas
    scene_photos = {}
    scene_files = {
        "fachada": scene_fachada, "sala": scene_sala, "cocina": scene_cocina,
        "recamara": scene_recamara, "bano": scene_bano, "cierre": scene_cierre,
    }
    for scene_name, scene_file in scene_files.items():
        if scene_file and scene_file.filename and scene_file.size > 0:
            ext = Path(scene_file.filename).suffix.lower()
            fname = f"scene_{scene_name}{ext}"
            dest = session_upload_dir / fname
            with open(dest, "wb") as buffer:
                shutil.copyfileobj(scene_file.file, buffer)
            scene_photos[scene_name] = f"/static/uploads/{session_id}/{fname}"

    data = {
        "tipo_propiedad": tipo_propiedad,
        "operacion": operacion,
        "direccion": direccion,
        "ciudad": ciudad,
        "estado": estado,
        "precio": precio,
        "recamaras": recamaras,
        "banos": banos,
        "metros_construidos": metros_construidos,
        "metros_terreno": metros_terreno,
        "estacionamientos": estacionamientos,
        "amenidades": amenidades,
        "descripcion_agente": descripcion_agente,
    }

    summary = build_property_summary(data)

    # ─── Generar textos con IA ───
    descripcion_profesional = ""
    instagram_copy = ""

    if gen_descripcion:
        descripcion_profesional = generate_professional_description(summary)
    if gen_instagram_copy:
        instagram_copy = generate_instagram_copy(summary, tipo_propiedad, operacion, ciudad)

    precio_formateado = format_price(float(precio.replace(",", "").replace("$", "").strip()))

    # ─── Generar guión del video con IA ───
    video_script = {}
    audio_path = ""
    vo_enabled = voice_over_enabled is not None

    if gen_video:
        # Guión: usar textos manuales si los puso, sino generar con IA
        manual_scenes = {
            "fachada": scene_fachada_text,
            "sala": scene_sala_text,
            "cocina": scene_cocina_text,
            "recamara": scene_recamara_text,
            "bano": scene_bano_text,
            "cierre": scene_cierre_text,
        }

        # Verificar si hay textos manuales
        has_manual = any(v and v.strip() for v in manual_scenes.values())

        if has_manual:
            # Usar textos manuales, rellenar vacíos con IA
            ai_script = generate_video_script(summary, video_tipo or "reel", voice_tones, voice_context or "")
            video_script = {}
            for name in SCENE_NAMES:
                manual = manual_scenes.get(name, "")
                if manual and manual.strip():
                    video_script[name] = manual.strip()
                else:
                    video_script[name] = ai_script.get(name, "")
        else:
            video_script = generate_video_script(summary, video_tipo or "reel", voice_tones, voice_context or "")

        # ─── Generar Voice Over con OpenAI TTS ───
        if vo_enabled and video_script:
            full_narration = " ... ".join(video_script.get(s, "") for s in SCENE_NAMES if video_script.get(s))
            voice = get_tts_voice(voice_gender or "feminine")
            audio_path = generate_tts_audio(full_narration, voice)

    context = {
        "nombre_propiedad": nombre_propiedad or "",
        "desarrollo_slug": desarrollo_slug or None,
        "tipo_propiedad": tipo_propiedad,
        "operacion": operacion,
        "direccion": direccion,
        "ciudad": ciudad,
        "estado": estado,
        "latitud": latitud,
        "longitud": longitud,
        "precio_formateado": precio_formateado,
        "recamaras": recamaras,
        "banos": banos,
        "metros_construidos": metros_construidos,
        "metros_terreno": metros_terreno,
        "estacionamientos": estacionamientos,
        "amenidades": amenidades,
        "agente_nombre": agente_nombre,
        "agente_telefono": agente_telefono,
        "agente_email": agente_email,
        "agente_instagram": agente_instagram,
        "agente_inmobiliaria": agente_inmobiliaria,
        "foto_portada_url": foto_portada_url,
        "foto_hero_pdf_url": foto_hero_pdf_url,
        "fotos_extra_urls": fotos_extra_urls,
        "descripcion_profesional": descripcion_profesional,
        "instagram_copy": instagram_copy,
        # Nuevos campos
        "video_script": video_script,
        "scene_photos": scene_photos,
        "video_tipo": video_tipo,
        "voice_over_enabled": vo_enabled,
        "audio_path": audio_path,
        "gen_video": gen_video is not None,
        "gen_pdf": gen_pdf is not None,
        "gen_ig_post": gen_ig_post is not None,
        "gen_ig_story": gen_ig_story is not None,
        "gen_ig_carousel": gen_ig_carousel is not None,
        "session_id": session_id,
    }

    # ─── Guardar propiedad en base de datos ───
    try:
        user = await require_auth(request)
        db_data = {
            **context,
            "session_id": session_id,
            "precio": precio,
            "user_id": user["id"] if user else None,
        }
        prop_id = await save_property(db_data)
        # Si operación es "Vendida", marcar como vendida
        if context.get("operacion") == "Vendida":
            from datetime import datetime as _dt
            await update_property(prop_id, {"vendida": True, "fecha_venta": _dt.now()})
        context["property_id"] = prop_id
    except Exception as e:
        print(f"[DB] Error guardando propiedad: {e}")
        context["property_id"] = None

    # ─── Iniciar renderizado de video en background ───
    if gen_video and valid_fotos:
        photo_paths = []
        # Usar fotos de escena si las hay, sino fotos principales
        for sn in SCENE_NAMES:
            if sn in scene_photos:
                fpath = url_to_filepath(scene_photos[sn])
                if fpath.exists():
                    photo_paths.append(str(fpath.resolve()))
        if not photo_paths:
            all_urls = [foto_portada_url] + fotos_extra_urls if foto_portada_url else fotos_extra_urls
            for url in all_urls:
                fpath = url_to_filepath(url)
                if fpath.exists():
                    photo_paths.append(str(fpath.resolve()))

        if photo_paths:
            job_id = str(uuid.uuid4())[:8]
            tipo_clean = tipo_propiedad.lower().replace(" ", "_")
            output_filename = f"reel_{tipo_clean}_{job_id}.mp4"
            output_path = VIDEO_DIR / output_filename

            video_jobs[job_id] = {
                "status": "queued", "progress": 0,
                "file": None, "error": None, "filename": output_filename,
            }

            video_data = {
                "photos": photo_paths,
                "operacion": operacion,
                "precio_formateado": precio_formateado,
                "direccion": direccion,
                "ciudad": ciudad,
                "estado": estado,
                "recamaras": recamaras or "",
                "banos": banos or "",
                "metros_construidos": metros_construidos or "",
                "metros_terreno": metros_terreno or "",
                "estacionamientos": estacionamientos or "",
                "tipoPropiedad": tipo_propiedad,
                "agente_nombre": agente_nombre,
                "agente_telefono": agente_telefono,
                "agente_email": agente_email,
                "audio_path": audio_path,
            }

            asyncio.create_task(render_video_task(job_id, video_data, output_path))
            context["video_job_id"] = job_id
            context["video_filename"] = output_filename

    return templates.TemplateResponse(request=request, name="result.html", context=context)


@app.post("/download-pdf")
async def download_pdf(
    request: Request,
    tipo_propiedad: str = Form(""),
    operacion: str = Form(""),
    direccion: str = Form(""),
    ciudad: str = Form(""),
    estado: str = Form(""),
    precio_formateado: str = Form(""),
    recamaras: Optional[str] = Form(None),
    banos: Optional[str] = Form(None),
    metros_construidos: Optional[str] = Form(None),
    metros_terreno: Optional[str] = Form(None),
    estacionamientos: Optional[str] = Form(None),
    agente_nombre: str = Form(""),
    agente_telefono: str = Form(""),
    agente_email: str = Form(""),
    foto_portada_url: Optional[str] = Form(None),
    foto_hero_pdf_url: Optional[str] = Form(None),
    descripcion_profesional: str = Form(""),
    foto_hero_pdf_upload: Optional[UploadFile] = File(None),
):
    form_data = await request.form()
    amenidades = form_data.getlist("amenidades")
    fotos_extra_urls = form_data.getlist("fotos_extra_urls")

    # Si subieron una foto hero nueva, guardarla temporalmente
    hero_pdf_path = None
    if foto_hero_pdf_upload and foto_hero_pdf_upload.filename and foto_hero_pdf_upload.size > 0:
        ext = Path(foto_hero_pdf_upload.filename).suffix.lower()
        if ext in {".jpg", ".jpeg", ".png", ".webp"}:
            tmp_dir = UPLOAD_DIR / "tmp_hero"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp_file = tmp_dir / f"hero_{uuid.uuid4().hex[:8]}{ext}"
            with open(tmp_file, "wb") as buffer:
                shutil.copyfileobj(foto_hero_pdf_upload.file, buffer)
            hero_pdf_path = str(tmp_file)
    elif foto_hero_pdf_url:
        # Usar la foto hero que ya se subió en el wizard
        p = url_to_filepath(foto_hero_pdf_url)
        if p.exists():
            hero_pdf_path = str(p)

    data = {
        "tipo_propiedad": tipo_propiedad,
        "operacion": operacion,
        "direccion": direccion,
        "ciudad": ciudad,
        "estado": estado,
        "precio_formateado": precio_formateado,
        "recamaras": recamaras,
        "banos": banos,
        "metros_construidos": metros_construidos,
        "metros_terreno": metros_terreno,
        "estacionamientos": estacionamientos,
        "amenidades": amenidades,
        "agente_nombre": agente_nombre,
        "agente_telefono": agente_telefono,
        "agente_email": agente_email,
        "foto_portada_url": foto_portada_url,
        "fotos_extra_urls": fotos_extra_urls,
        "descripcion_profesional": descripcion_profesional,
        "hero_pdf_path": hero_pdf_path,
    }

    pdf_bytes = generate_property_pdf(data)

    tipo_clean = tipo_propiedad.lower().replace(" ", "_")
    filename = f"ficha_{tipo_clean}_{ciudad.lower().replace(' ', '_')}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/download-image")
async def download_image(
    request: Request,
    tipo_propiedad: str = Form(""),
    operacion: str = Form(""),
    direccion: str = Form(""),
    ciudad: str = Form(""),
    estado: str = Form(""),
    precio_formateado: str = Form(""),
    recamaras: Optional[str] = Form(None),
    banos: Optional[str] = Form(None),
    metros_construidos: Optional[str] = Form(None),
    metros_terreno: Optional[str] = Form(None),
    estacionamientos: Optional[str] = Form(None),
    foto_portada_url: Optional[str] = Form(None),
):
    data = {
        "tipo_propiedad": tipo_propiedad,
        "operacion": operacion,
        "direccion": direccion,
        "ciudad": ciudad,
        "estado": estado,
        "precio_formateado": precio_formateado,
        "recamaras": recamaras,
        "banos": banos,
        "metros_construidos": metros_construidos,
        "metros_terreno": metros_terreno,
        "estacionamientos": estacionamientos,
        "foto_portada_url": foto_portada_url,
    }

    img_bytes = generate_instagram_image(data)

    tipo_clean = tipo_propiedad.lower().replace(" ", "_")
    filename = f"instagram_{tipo_clean}_{ciudad.lower().replace(' ', '_')}.jpg"

    return StreamingResponse(
        io.BytesIO(img_bytes),
        media_type="image/jpeg",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/download-story")
async def download_story(
    request: Request,
    tipo_propiedad: str = Form(""),
    operacion: str = Form(""),
    direccion: str = Form(""),
    ciudad: str = Form(""),
    estado: str = Form(""),
    precio_formateado: str = Form(""),
    recamaras: Optional[str] = Form(None),
    banos: Optional[str] = Form(None),
    metros_construidos: Optional[str] = Form(None),
    metros_terreno: Optional[str] = Form(None),
    estacionamientos: Optional[str] = Form(None),
    agente_nombre: str = Form(""),
    agente_telefono: str = Form(""),
    agente_email: str = Form(""),
    foto_portada_url: Optional[str] = Form(None),
):
    data = {
        "tipo_propiedad": tipo_propiedad,
        "operacion": operacion,
        "direccion": direccion,
        "ciudad": ciudad,
        "estado": estado,
        "precio_formateado": precio_formateado,
        "recamaras": recamaras,
        "banos": banos,
        "metros_construidos": metros_construidos,
        "metros_terreno": metros_terreno,
        "estacionamientos": estacionamientos,
        "agente_nombre": agente_nombre,
        "agente_telefono": agente_telefono,
        "foto_portada_url": foto_portada_url,
    }
    img_bytes = generate_instagram_story(data)
    tipo_clean = tipo_propiedad.lower().replace(" ", "_")
    filename = f"story_{tipo_clean}_{ciudad.lower().replace(' ', '_')}.jpg"
    return StreamingResponse(
        io.BytesIO(img_bytes),
        media_type="image/jpeg",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/download-carousel")
async def download_carousel(
    request: Request,
    tipo_propiedad: str = Form(""),
    operacion: str = Form(""),
    direccion: str = Form(""),
    ciudad: str = Form(""),
    estado: str = Form(""),
    precio_formateado: str = Form(""),
    recamaras: Optional[str] = Form(None),
    banos: Optional[str] = Form(None),
    metros_construidos: Optional[str] = Form(None),
    metros_terreno: Optional[str] = Form(None),
    estacionamientos: Optional[str] = Form(None),
    agente_nombre: str = Form(""),
    agente_telefono: str = Form(""),
    agente_email: str = Form(""),
    foto_portada_url: Optional[str] = Form(None),
    descripcion_profesional: Optional[str] = Form(None),
):
    form_data = await request.form()
    fotos_extra_urls = form_data.getlist("fotos_extra_urls")
    amenidades = form_data.getlist("amenidades")

    data = {
        "tipo_propiedad": tipo_propiedad,
        "operacion": operacion,
        "direccion": direccion,
        "ciudad": ciudad,
        "estado": estado,
        "precio_formateado": precio_formateado,
        "recamaras": recamaras,
        "banos": banos,
        "metros_construidos": metros_construidos,
        "metros_terreno": metros_terreno,
        "estacionamientos": estacionamientos,
        "agente_nombre": agente_nombre,
        "agente_telefono": agente_telefono,
        "agente_email": agente_email,
        "foto_portada_url": foto_portada_url,
        "fotos_extra_urls": fotos_extra_urls,
        "amenidades": amenidades,
        "descripcion_profesional": descripcion_profesional or "",
    }

    slides_bytes = generate_instagram_carousel(data)

    # Empaquetar slides en un ZIP
    import zipfile
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, slide_bytes in enumerate(slides_bytes):
            zf.writestr(f"slide_{i + 1:02d}.jpg", slide_bytes)

    zip_buf.seek(0)
    tipo_clean = tipo_propiedad.lower().replace(" ", "_")
    filename = f"carousel_{tipo_clean}_{ciudad.lower().replace(' ', '_')}.zip"

    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/publish-instagram")
async def publish_instagram(request: Request):
    """Genera imagen(es) IG y publica via Upload Post API. Soporta post, story y carousel."""
    form = await request.form()

    api_key = os.getenv("UPLOADPOST_API_KEY", "")
    ig_user = os.getenv("UPLOADPOST_USER", "")

    if not api_key or not ig_user:
        return {"success": False, "error": "Faltan las variables UPLOADPOST_API_KEY o UPLOADPOST_USER en el .env"}

    publish_type = form.get("publish_type", "post")  # post | story | carousel
    instagram_copy = form.get("instagram_copy", "")
    session_id = form.get("session_id", "")

    # Datos comunes para generar imágenes
    data = {
        "tipo_propiedad": form.get("tipo_propiedad", ""),
        "operacion": form.get("operacion", ""),
        "direccion": form.get("direccion", ""),
        "ciudad": form.get("ciudad", ""),
        "estado": form.get("estado", ""),
        "precio_formateado": form.get("precio_formateado", ""),
        "recamaras": form.get("recamaras"),
        "banos": form.get("banos"),
        "metros_construidos": form.get("metros_construidos"),
        "metros_terreno": form.get("metros_terreno"),
        "estacionamientos": form.get("estacionamientos"),
        "foto_portada_url": form.get("foto_portada_url"),
        "agente_nombre": form.get("agente_nombre", ""),
        "agente_telefono": form.get("agente_telefono", ""),
        "agente_email": form.get("agente_email", ""),
        "descripcion_profesional": form.get("descripcion_profesional", ""),
    }
    # Amenidades y fotos extra (pueden venir múltiples valores)
    data["amenidades"] = form.getlist("amenidades") if hasattr(form, "getlist") else []
    fotos_extra = form.getlist("fotos_extra_urls") if hasattr(form, "getlist") else []
    data["fotos_extra_urls"] = fotos_extra

    # ─── Stories: no soportadas por la API de Instagram ───
    if publish_type == "story":
        return {
            "success": False,
            "error": "Instagram no permite publicar Stories por API (limitación de Meta). Descarga la imagen y súbela manualmente desde la app."
        }

    # ─── Generar imágenes según tipo ───
    files_list = []

    if publish_type == "carousel":
        try:
            slides = generate_instagram_carousel(data)
            for i, slide_bytes in enumerate(slides):
                files_list.append(("photos[]", (f"carousel_{i+1}.jpg", slide_bytes, "image/jpeg")))
        except Exception as e:
            return {"success": False, "error": f"Error generando carrusel: {e}"}
    else:
        # Post normal (1080x1080)
        try:
            img_bytes = generate_instagram_image(data)
            files_list.append(("photos[]", ("instagram_post.jpg", img_bytes, "image/jpeg")))
        except Exception as e:
            return {"success": False, "error": f"Error generando imagen: {e}"}

    # ─── Llamar a Upload Post API ───
    try:
        async with httpx.AsyncClient(timeout=120.0) as client_http:
            response = await client_http.post(
                "https://api.upload-post.com/api/upload_photos",
                headers={
                    "Authorization": f"Apikey {api_key}",
                },
                data={
                    "user": ig_user,
                    "platform[]": "instagram",
                    "title": instagram_copy,
                },
                files=files_list,
            )

        result = response.json()

        if response.status_code == 200 and result.get("success"):
            ig_result = result.get("results", {}).get("instagram", {})
            post_url = ig_result.get("url", "")
            # Marcar como publicada en DB
            try:
                if session_id:
                    from database import get_property_by_session
                    prop = await get_property_by_session(session_id)
                    if prop:
                        await update_property(prop["id"], {"publicada_instagram": True})
            except Exception:
                pass
            tipo_label = "Carrusel publicado" if publish_type == "carousel" else "Publicado"
            return {
                "success": True,
                "message": f"{tipo_label} exitosamente en Instagram",
                "post_url": post_url,
            }
        elif response.status_code == 202:
            return {
                "success": True,
                "message": "Publicación programada exitosamente",
                "job_id": result.get("job_id", ""),
            }
        else:
            error_msg = result.get("error") or result.get("message") or f"Error HTTP {response.status_code}"
            return {"success": False, "error": error_msg}

    except httpx.TimeoutException:
        return {"success": False, "error": "Timeout: la publicación está siendo procesada en segundo plano"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─── Generacion de Video con MoviePy + Pillow ───

W_VID, H_VID = 1080, 1920
FPS_VID = 30
SCENE_SECS = 4
COVER_SECS = 5
CONTACT_SECS = 5

NAVY_RGB = (26, 60, 94)
GOLD_RGB = (201, 162, 39)
WHITE_RGB = (255, 255, 255)


def _pil_to_frame(img: Image.Image):
    """Convierte Pillow RGBA/RGB a array numpy para MoviePy."""
    import numpy as np
    return np.array(img.convert("RGB"))


def _load_and_crop_vertical(path: str) -> Image.Image:
    """Carga imagen y la recorta a 1080x1920 (9:16 centrado)."""
    img = _open_image(path, "RGB")
    w, h = img.size
    target_ratio = W_VID / H_VID  # 0.5625
    current_ratio = w / h
    if current_ratio > target_ratio:
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
    return img.resize((W_VID, H_VID), Image.LANCZOS)


def _draw_gradient(draw: ImageDraw.Draw, w: int, h: int, top_alpha=150, bottom_alpha=220):
    """Gradiente oscuro arriba y abajo."""
    for y in range(min(400, h)):
        a = int(top_alpha * (1 - y / 400))
        draw.line([(0, y), (w, y)], fill=(0, 0, 0, a))
    start = h - 650
    for y in range(start, h):
        progress = (y - start) / 650
        a = int(bottom_alpha * progress)
        draw.line([(0, y), (w, y)], fill=(0, 0, 0, a))


def _apply_ken_burns(base_img: Image.Image, t: float, duration: float, direction: str = "in") -> Image.Image:
    """Aplica efecto Ken Burns (zoom lento) al frame."""
    progress = t / duration if duration > 0 else 0
    if direction == "in":
        scale = 1.0 + 0.08 * progress
        dx = -10 * progress
    else:
        scale = 1.08 - 0.08 * progress
        dx = -10 * (1 - progress)
    new_w = int(W_VID * scale)
    new_h = int(H_VID * scale)
    zoomed = base_img.resize((new_w, new_h), Image.LANCZOS)
    cx = (new_w - W_VID) // 2 + int(dx)
    cy = (new_h - H_VID) // 2
    cx = max(0, min(cx, new_w - W_VID))
    cy = max(0, min(cy, new_h - H_VID))
    return zoomed.crop((cx, cy, cx + W_VID, cy + H_VID))


def _build_scene_cover(photo_path: str, data: dict) -> Image.Image:
    """Escena 1: portada con badge + precio + ubicacion."""
    base = _load_and_crop_vertical(photo_path)
    overlay = Image.new("RGBA", (W_VID, H_VID), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    _draw_gradient(draw, W_VID, H_VID, 150, 230)

    fb = _find_font(True)
    fr = _find_font(False)
    font_badge = ImageFont.truetype(fb, 36) if fb else ImageFont.load_default()
    font_price = ImageFont.truetype(fb, 78) if fb else ImageFont.load_default()
    font_loc = ImageFont.truetype(fr, 34) if fr else ImageFont.load_default()

    # Gold top line
    draw.rectangle([0, 0, W_VID, 6], fill=GOLD_RGB)

    # Badge
    badge = f"  EN {data.get('operacion', 'VENTA').upper()}  "
    bb = font_badge.getbbox(badge)
    bw = bb[2] - bb[0] + 36
    bh = bb[3] - bb[1] + 22
    draw.rounded_rectangle([60, 60, 60 + bw, 60 + bh], radius=8, fill=(*GOLD_RGB, 255))
    draw.text((60 + 18, 60 + 9), badge, fill=(*NAVY_RGB, 255), font=font_badge)

    # Logo header top-right
    logo_path = BASE_DIR / "static" / "img" / "logo-header.png"
    if logo_path.exists():
        logo = _open_image(logo_path, "RGBA")
        lh = 55
        lr = logo.width / logo.height
        logo = logo.resize((int(lh * lr), lh), Image.LANCZOS)
        overlay.paste(logo, (W_VID - logo.width - 60, 55), logo)

    # Gold line + price + location (bottom)
    y = H_VID - 380
    draw.rectangle([60, y, W_VID - 60, y + 3], fill=(*GOLD_RGB, 255))
    y += 30
    draw.text((60, y), data.get("precio_formateado", ""), fill=(*WHITE_RGB, 255), font=font_price)
    y += 100
    ubic = f"{data.get('direccion', '')}, {data.get('ciudad', '')}"
    if len(ubic) > 45:
        ubic = ubic[:42] + "..."
    draw.text((60, y), ubic, fill=(255, 255, 255, 180), font=font_loc)

    result = Image.alpha_composite(base.convert("RGBA"), overlay)
    return result.convert("RGB")


def _build_scene_specs(photo_path: str, data: dict) -> Image.Image:
    """Escena 2: foto con datos principales."""
    base = _load_and_crop_vertical(photo_path)
    overlay = Image.new("RGBA", (W_VID, H_VID), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    _draw_gradient(draw, W_VID, H_VID, 120, 210)

    fb = _find_font(True)
    fr = _find_font(False)
    font_val = ImageFont.truetype(fb, 64) if fb else ImageFont.load_default()
    font_lbl = ImageFont.truetype(fr, 24) if fr else ImageFont.load_default()
    font_badge = ImageFont.truetype(fb, 30) if fb else ImageFont.load_default()

    # Top badge
    tipo = data.get("tipoPropiedad", "").upper()
    bb = font_badge.getbbox(tipo)
    bw = bb[2] - bb[0] + 48
    bh = bb[3] - bb[1] + 22
    draw.rounded_rectangle([60, 80, 60 + bw, 80 + bh], radius=6,
                           fill=(26, 60, 94, 200), outline=(*GOLD_RGB, 255), width=2)
    draw.text((60 + 24, 80 + 9), tipo, fill=(*GOLD_RGB, 255), font=font_badge)

    # Specs at bottom
    specs = []
    if data.get("recamaras"): specs.append(("Rec", data["recamaras"]))
    if data.get("banos"): specs.append(("Banos", data["banos"]))
    if data.get("metros_construidos"): specs.append(("m2", data["metros_construidos"]))
    if data.get("metros_terreno"): specs.append(("m2 Ter", data["metros_terreno"]))
    if data.get("estacionamientos"): specs.append(("Est", data["estacionamientos"]))

    if specs:
        y = H_VID - 300
        draw.rectangle([60, y, W_VID - 60, y + 3], fill=(*GOLD_RGB, 255))
        y += 30
        col_w = (W_VID - 120) // len(specs)
        for i, (lbl, val) in enumerate(specs):
            x = 60 + i * col_w + col_w // 2
            vbb = font_val.getbbox(str(val))
            vw = vbb[2] - vbb[0]
            draw.text((x - vw // 2, y), str(val), fill=(*WHITE_RGB, 255), font=font_val)
            lbb = font_lbl.getbbox(lbl.upper())
            lw = lbb[2] - lbb[0]
            draw.text((x - lw // 2, y + 72), lbl.upper(), fill=(*GOLD_RGB, 255), font=font_lbl)
        draw.rectangle([60, y + 115, W_VID - 60, y + 118], fill=(*GOLD_RGB, 255))

    result = Image.alpha_composite(base.convert("RGBA"), overlay)
    return result.convert("RGB")


def _build_scene_detail(photo_path: str, data: dict) -> Image.Image:
    """Escena intermedia: foto con precio y ubicacion."""
    base = _load_and_crop_vertical(photo_path)
    overlay = Image.new("RGBA", (W_VID, H_VID), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    _draw_gradient(draw, W_VID, H_VID, 80, 200)

    fb = _find_font(True)
    fr = _find_font(False)
    font_price = ImageFont.truetype(fb, 60) if fb else ImageFont.load_default()
    font_loc = ImageFont.truetype(fr, 30) if fr else ImageFont.load_default()

    y = H_VID - 260
    draw.text((60, y), data.get("precio_formateado", ""), fill=(*WHITE_RGB, 255), font=font_price)
    draw.rectangle([60, y + 75, 260, y + 78], fill=(*GOLD_RGB, 255))
    draw.text((60, y + 90), f"{data.get('direccion', '')}, {data.get('ciudad', '')}",
              fill=(255, 255, 255, 170), font=font_loc)

    result = Image.alpha_composite(base.convert("RGBA"), overlay)
    return result.convert("RGB")


def _build_scene_contact(data: dict) -> Image.Image:
    """Escena final: fondo navy + logo + datos de contacto."""
    base = Image.new("RGB", (W_VID, H_VID), NAVY_RGB)
    overlay = Image.new("RGBA", (W_VID, H_VID), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    fb = _find_font(True)
    fr = _find_font(False)
    font_name = ImageFont.truetype(fb, 48) if fb else ImageFont.load_default()
    font_phone = ImageFont.truetype(fb, 38) if fb else ImageFont.load_default()
    font_email = ImageFont.truetype(fr, 30) if fr else ImageFont.load_default()
    font_cta = ImageFont.truetype(fb, 34) if fb else ImageFont.load_default()

    # Gold lines top/bottom
    draw.rectangle([0, 0, W_VID, 6], fill=(*GOLD_RGB, 255))
    draw.rectangle([0, H_VID - 6, W_VID, H_VID], fill=(*GOLD_RGB, 255))

    # Logo full centered
    logo_path = BASE_DIR / "static" / "img" / "logo-full.png"
    y_cursor = 500
    if logo_path.exists():
        logo = _open_image(logo_path, "RGBA")
        lh = 220
        lr = logo.width / logo.height
        logo = logo.resize((int(lh * lr), lh), Image.LANCZOS)
        lx = (W_VID - logo.width) // 2
        overlay.paste(logo, (lx, y_cursor), logo)
        y_cursor += lh + 40

    # Gold divider
    draw.rectangle([(W_VID - 300) // 2, y_cursor, (W_VID + 300) // 2, y_cursor + 3], fill=(*GOLD_RGB, 255))
    y_cursor += 50

    # Agent name
    name = data.get("agente_nombre", "")
    nbb = font_name.getbbox(name)
    nw = nbb[2] - nbb[0]
    draw.text(((W_VID - nw) // 2, y_cursor), name, fill=(*WHITE_RGB, 255), font=font_name)
    y_cursor += 70

    # Phone
    phone = f"Tel: {data.get('agente_telefono', '')}"
    pbb = font_phone.getbbox(phone)
    pw = pbb[2] - pbb[0]
    draw.text(((W_VID - pw) // 2, y_cursor), phone, fill=(*GOLD_RGB, 255), font=font_phone)
    y_cursor += 60

    # Email
    email = data.get("agente_email", "")
    ebb = font_email.getbbox(email)
    ew = ebb[2] - ebb[0]
    draw.text(((W_VID - ew) // 2, y_cursor), email, fill=(255, 255, 255, 150), font=font_email)
    y_cursor += 100

    # CTA button
    cta = "AGENDA TU VISITA HOY"
    cbb = font_cta.getbbox(cta)
    cw = cbb[2] - cbb[0] + 80
    ch = cbb[3] - cbb[1] + 36
    cx = (W_VID - cw) // 2
    draw.rounded_rectangle([cx, y_cursor, cx + cw, y_cursor + ch], radius=12, fill=(*GOLD_RGB, 255))
    draw.text((cx + 40, y_cursor + 16), cta, fill=(*NAVY_RGB, 255), font=font_cta)

    result = Image.alpha_composite(base.convert("RGBA"), overlay)
    return result.convert("RGB")


def _build_overlay_cover(data: dict) -> Image.Image:
    """Construye SOLO el overlay transparente de la escena cover (sin foto de fondo)."""
    overlay = Image.new("RGBA", (W_VID, H_VID), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    _draw_gradient(draw, W_VID, H_VID, 150, 230)

    fb = _find_font(True)
    fr = _find_font(False)
    font_badge = ImageFont.truetype(fb, 36) if fb else ImageFont.load_default()
    font_price = ImageFont.truetype(fb, 78) if fb else ImageFont.load_default()
    font_loc = ImageFont.truetype(fr, 34) if fr else ImageFont.load_default()

    draw.rectangle([0, 0, W_VID, 6], fill=GOLD_RGB)
    badge = f"  EN {data.get('operacion', 'VENTA').upper()}  "
    bb = font_badge.getbbox(badge)
    bw = bb[2] - bb[0] + 36
    bh = bb[3] - bb[1] + 22
    draw.rounded_rectangle([60, 60, 60 + bw, 60 + bh], radius=8, fill=(*GOLD_RGB, 255))
    draw.text((60 + 18, 60 + 9), badge, fill=(*NAVY_RGB, 255), font=font_badge)

    logo_path = BASE_DIR / "static" / "img" / "logo-header.png"
    if logo_path.exists():
        logo = _open_image(logo_path, "RGBA")
        lh = 55
        lr = logo.width / logo.height
        logo = logo.resize((int(lh * lr), lh), Image.LANCZOS)
        overlay.paste(logo, (W_VID - logo.width - 60, 55), logo)

    y = H_VID - 380
    draw.rectangle([60, y, W_VID - 60, y + 3], fill=(*GOLD_RGB, 255))
    y += 30
    draw.text((60, y), data.get("precio_formateado", ""), fill=(*WHITE_RGB, 255), font=font_price)
    y += 100
    ubic = f"{data.get('direccion', '')}, {data.get('ciudad', '')}"
    if len(ubic) > 45:
        ubic = ubic[:42] + "..."
    draw.text((60, y), ubic, fill=(255, 255, 255, 180), font=font_loc)
    return overlay


def _build_overlay_specs(data: dict) -> Image.Image:
    """Construye SOLO el overlay transparente de la escena specs."""
    overlay = Image.new("RGBA", (W_VID, H_VID), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    _draw_gradient(draw, W_VID, H_VID, 120, 210)

    fb = _find_font(True)
    fr = _find_font(False)
    font_val = ImageFont.truetype(fb, 64) if fb else ImageFont.load_default()
    font_lbl = ImageFont.truetype(fr, 24) if fr else ImageFont.load_default()
    font_badge = ImageFont.truetype(fb, 30) if fb else ImageFont.load_default()

    tipo = data.get("tipoPropiedad", "").upper()
    bb = font_badge.getbbox(tipo)
    bw = bb[2] - bb[0] + 48
    bh = bb[3] - bb[1] + 22
    draw.rounded_rectangle([60, 80, 60 + bw, 80 + bh], radius=6,
                           fill=(26, 60, 94, 200), outline=(*GOLD_RGB, 255), width=2)
    draw.text((60 + 24, 80 + 9), tipo, fill=(*GOLD_RGB, 255), font=font_badge)

    specs = []
    if data.get("recamaras"): specs.append(("Rec", data["recamaras"]))
    if data.get("banos"): specs.append(("Banos", data["banos"]))
    if data.get("metros_construidos"): specs.append(("m2", data["metros_construidos"]))
    if data.get("metros_terreno"): specs.append(("m2 Ter", data["metros_terreno"]))
    if data.get("estacionamientos"): specs.append(("Est", data["estacionamientos"]))

    if specs:
        y = H_VID - 300
        draw.rectangle([60, y, W_VID - 60, y + 3], fill=(*GOLD_RGB, 255))
        y += 30
        col_w = (W_VID - 120) // len(specs)
        for i, (lbl, val) in enumerate(specs):
            x = 60 + i * col_w + col_w // 2
            vbb = font_val.getbbox(str(val))
            vw = vbb[2] - vbb[0]
            draw.text((x - vw // 2, y), str(val), fill=(*WHITE_RGB, 255), font=font_val)
            lbb = font_lbl.getbbox(lbl.upper())
            lw = lbb[2] - lbb[0]
            draw.text((x - lw // 2, y + 72), lbl.upper(), fill=(*GOLD_RGB, 255), font=font_lbl)
        draw.rectangle([60, y + 115, W_VID - 60, y + 118], fill=(*GOLD_RGB, 255))
    return overlay


def _build_overlay_detail(data: dict) -> Image.Image:
    """Construye SOLO el overlay transparente de la escena detail."""
    overlay = Image.new("RGBA", (W_VID, H_VID), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    _draw_gradient(draw, W_VID, H_VID, 80, 200)

    fb = _find_font(True)
    fr = _find_font(False)
    font_price = ImageFont.truetype(fb, 60) if fb else ImageFont.load_default()
    font_loc = ImageFont.truetype(fr, 30) if fr else ImageFont.load_default()

    y = H_VID - 260
    draw.text((60, y), data.get("precio_formateado", ""), fill=(*WHITE_RGB, 255), font=font_price)
    draw.rectangle([60, y + 75, 260, y + 78], fill=(*GOLD_RGB, 255))
    draw.text((60, y + 90), f"{data.get('direccion', '')}, {data.get('ciudad', '')}",
              fill=(255, 255, 255, 170), font=font_loc)
    return overlay


def _make_kb_clip(photo_path: str, overlay: Image.Image, duration: float, direction: str = "in"):
    """Crea un VideoClip con efecto Ken Burns sobre la foto + overlay de texto."""
    from moviepy import VideoClip
    import numpy as np

    base = _load_and_crop_vertical(photo_path)

    def make_frame(t):
        kb = _apply_ken_burns(base, t, duration, direction)
        combined = Image.alpha_composite(kb.convert("RGBA"), overlay)
        return np.array(combined.convert("RGB"))

    return VideoClip(make_frame, duration=duration).with_fps(FPS_VID)


def render_video_sync(data: dict, output_path: Path, job_id: str):
    """Renderiza el reel MP4 con MoviePy + Pillow. Soporta voice over con audio."""
    from moviepy import ImageClip, concatenate_videoclips, AudioFileClip
    import numpy as np

    photos = data.get("photos", [])
    audio_path = data.get("audio_path", "")
    scenes = []

    # Si hay audio, calcular duración por escena basado en audio
    audio_duration = 0
    if audio_path and os.path.exists(audio_path):
        try:
            audio_clip = AudioFileClip(audio_path)
            audio_duration = audio_clip.duration
            audio_clip.close()
        except Exception as e:
            print(f"[VIDEO] Error leyendo audio: {e}")
            audio_duration = 0

    # Calcular duración por escena
    n_scenes = max(len(photos), 1)
    if audio_duration > 0:
        # Distribuir audio entre las escenas + contacto
        scene_dur = audio_duration / n_scenes
        scene_dur = max(scene_dur, 3)  # mínimo 3 segundos
    else:
        scene_dur = SCENE_SECS

    # Escena 1: Cover — Ken Burns zoom IN
    if photos:
        ov_cover = _build_overlay_cover(data)
        clip = _make_kb_clip(photos[0], ov_cover, COVER_SECS if not audio_duration else scene_dur, "in")
        scenes.append(clip)
        video_jobs[job_id]["progress"] = 20

    # Escena 2: Specs — Ken Burns zoom OUT
    if len(photos) > 1:
        ov_specs = _build_overlay_specs(data)
        clip = _make_kb_clip(photos[1], ov_specs, scene_dur, "out")
        scenes.append(clip)
        video_jobs[job_id]["progress"] = 35

    # Escenas intermedias: detail — alternar zoom in/out
    detail_start = 2
    for i in range(min(len(photos) - detail_start, 3)):
        idx = detail_start + i
        if idx < len(photos):
            ov_detail = _build_overlay_detail(data)
            direction = "in" if i % 2 == 0 else "out"
            clip = _make_kb_clip(photos[idx], ov_detail, scene_dur, direction)
            scenes.append(clip)
        video_jobs[job_id]["progress"] = 35 + (i + 1) * 10

    # Escena final: contacto — estatica (sin foto, fondo navy)
    contact_img = _build_scene_contact(data)
    clip = ImageClip(_pil_to_frame(contact_img), duration=CONTACT_SECS)
    scenes.append(clip)
    video_jobs[job_id]["progress"] = 70

    # Concatenar escenas
    final = concatenate_videoclips(scenes, method="compose")
    video_jobs[job_id]["progress"] = 80

    # Si hay audio, combinarlo con el video
    has_audio = False
    if audio_path and os.path.exists(audio_path):
        try:
            audio_clip = AudioFileClip(audio_path)
            # Ajustar duración de audio al video o viceversa
            if audio_clip.duration > final.duration:
                try:
                    audio_clip = audio_clip.subclipped(0, final.duration)
                except AttributeError:
                    audio_clip = audio_clip.subclip(0, final.duration)
            final = final.with_audio(audio_clip)
            has_audio = True
            print(f"[VIDEO] Audio añadido: {audio_clip.duration:.1f}s")
        except Exception as e:
            print(f"[VIDEO] Error combinando audio: {e}")

    final.write_videofile(
        str(output_path),
        fps=FPS_VID,
        codec="libx264",
        audio=has_audio,
        audio_codec="aac" if has_audio else None,
        preset="fast",
        threads=2,
        logger=None,
    )
    video_jobs[job_id]["progress"] = 100


async def render_video_task(job_id: str, data: dict, output_path: Path):
    """Lanza el render en un thread separado para no bloquear asyncio."""
    try:
        video_jobs[job_id]["status"] = "rendering"
        video_jobs[job_id]["progress"] = 5

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, render_video_sync, data, output_path, job_id)

        if output_path.exists():
            video_jobs[job_id]["status"] = "done"
            video_jobs[job_id]["file"] = str(output_path)
        else:
            video_jobs[job_id]["status"] = "error"
            video_jobs[job_id]["error"] = "No se genero el archivo MP4"

    except Exception as e:
        video_jobs[job_id]["status"] = "error"
        video_jobs[job_id]["error"] = str(e)


@app.post("/generate-video")
async def generate_video(
    request: Request,
    tipo_propiedad: str = Form(""),
    operacion: str = Form(""),
    direccion: str = Form(""),
    ciudad: str = Form(""),
    estado: str = Form(""),
    precio_formateado: str = Form(""),
    recamaras: Optional[str] = Form(None),
    banos: Optional[str] = Form(None),
    metros_construidos: Optional[str] = Form(None),
    metros_terreno: Optional[str] = Form(None),
    estacionamientos: Optional[str] = Form(None),
    agente_nombre: str = Form(""),
    agente_telefono: str = Form(""),
    agente_email: str = Form(""),
    foto_portada_url: Optional[str] = Form(None),
):
    form_data = await request.form()
    fotos_extra_urls = form_data.getlist("fotos_extra_urls")

    # Recoger rutas de fotos locales
    photo_paths = []
    all_urls = []
    if foto_portada_url:
        all_urls.append(foto_portada_url)
    all_urls.extend(fotos_extra_urls)

    for url in all_urls:
        fpath = url_to_filepath(url)
        if fpath.exists():
            photo_paths.append(str(fpath.resolve()))

    data = {
        "photos": photo_paths,
        "operacion": operacion,
        "precio_formateado": precio_formateado,
        "direccion": direccion,
        "ciudad": ciudad,
        "estado": estado,
        "recamaras": recamaras or "",
        "banos": banos or "",
        "metros_construidos": metros_construidos or "",
        "estacionamientos": estacionamientos or "",
        "tipoPropiedad": tipo_propiedad,
        "agente_nombre": agente_nombre,
        "agente_telefono": agente_telefono,
        "agente_email": agente_email,
    }

    job_id = str(uuid.uuid4())[:8]
    tipo_clean = tipo_propiedad.lower().replace(" ", "_")
    output_filename = f"reel_{tipo_clean}_{job_id}.mp4"
    output_path = VIDEO_DIR / output_filename

    video_jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "file": None,
        "error": None,
        "filename": output_filename,
    }

    asyncio.create_task(render_video_task(job_id, data, output_path))

    return JSONResponse({"success": True, "job_id": job_id})


@app.get("/video-status/{job_id}")
async def video_status(job_id: str):
    job = video_jobs.get(job_id)
    if not job:
        return JSONResponse({"success": False, "error": "Job no encontrado"}, status_code=404)

    return JSONResponse({
        "success": True,
        "status": job["status"],
        "progress": job["progress"],
        "error": job.get("error"),
        "download_url": f"/static/videos/{job['filename']}" if job["status"] == "done" else None,
    })


@app.get("/download-video/{job_id}")
async def download_video(job_id: str):
    job = video_jobs.get(job_id)
    if not job or job["status"] != "done" or not job.get("file"):
        return JSONResponse({"success": False, "error": "Video no disponible"}, status_code=404)

    return FileResponse(
        job["file"],
        media_type="video/mp4",
        filename=job["filename"],
    )


# ─── Portal del comprador ───────────────────────────────────────────

TIPOS_COMPRA = ["Contado", "Transferencia", "Crédito bancario", "Crédito Infonavit", "Crédito ISSEG"]

# Documentos base obligatorios para TODOS los compradores (cualquier tipo de compra)
_DOCS_COMPRADOR_BASE = [
    {"tipo": "INE (Identificación oficial)", "obligatorio": True},
    {"tipo": "CURP", "obligatorio": True},
    {"tipo": "Constancia de situación fiscal", "obligatorio": True},
    {"tipo": "Acta de nacimiento", "obligatorio": True},
    {"tipo": "Acta de matrimonio", "obligatorio": False},
]

DOCS_COMPRADOR = {
    "Crédito Infonavit": _DOCS_COMPRADOR_BASE + [
        {"tipo": "Solicitud de avalúo", "obligatorio": True},
        {"tipo": "Solicitud de crédito", "obligatorio": True},
        {"tipo": "Constancia Saber +", "obligatorio": True},
        {"tipo": "Aviso de retención", "obligatorio": True},
        {"tipo": "Carta autorización crédito", "obligatorio": False},
        {"tipo": "Avalúo", "obligatorio": True},
        {"tipo": "Croquis de localización (Anexo C)", "obligatorio": True},
        {"tipo": "Constancia de crédito", "obligatorio": True},
        {"tipo": "Elección de notario", "obligatorio": True},
        {"tipo": "Formato Bajoprotesta (Creditereno)", "obligatorio": True},
        {"tipo": "Poder para trámites Infonavit", "obligatorio": True},
        {"tipo": "Alineamiento", "obligatorio": True},
        {"tipo": "Predial", "obligatorio": True},
        {"tipo": "Agua y luz", "obligatorio": True},
    ],
    "Crédito ISSEG": _DOCS_COMPRADOR_BASE + [
        {"tipo": "Solicitud de préstamo", "obligatorio": True},
        {"tipo": "Talón de pago actual", "obligatorio": True},
        {"tipo": "Aviso de privacidad firmado", "obligatorio": True},
        {"tipo": "Carta de pago de gastos notariales", "obligatorio": True},
        {"tipo": "Avalúo comercial", "obligatorio": True},
        {"tipo": "Avalúo fiscal", "obligatorio": True},
        {"tipo": "Comprobante de domicilio", "obligatorio": True},
        {"tipo": "Consentimiento de monto y plazo", "obligatorio": True},
        {"tipo": "Contrato de promesa", "obligatorio": True},
    ],
    "Crédito bancario": _DOCS_COMPRADOR_BASE + [
        {"tipo": "Escritura de propiedad completa y legible con registro público", "obligatorio": True},
        {"tipo": "Régimen de propiedad en condominio", "obligatorio": False},
        {"tipo": "Planos arquitectónicos", "obligatorio": False},
        {"tipo": "Constancia de Alineamiento y Número oficial", "obligatorio": False},
        {"tipo": "Boleta predial con comprobante de pago", "obligatorio": True},
        {"tipo": "Boleta de agua con comprobante de pago", "obligatorio": True},
        {"tipo": "Contacto para el avalúo (Nombre y teléfono)", "obligatorio": True},
        {"tipo": "Confirmación de notaría o carta petición del cliente", "obligatorio": True},
        {"tipo": "Cuenta del cliente donde se ligará el crédito", "obligatorio": True},
        {"tipo": "Estado de cuenta del vendedor", "obligatorio": True},
        {"tipo": "Comprobante de domicilio", "obligatorio": True},
    ],
    "Contado": _DOCS_COMPRADOR_BASE + [
        {"tipo": "Comprobante de domicilio", "obligatorio": True},
        {"tipo": "Estado de cuenta", "obligatorio": True},
    ],
    "Transferencia": _DOCS_COMPRADOR_BASE + [
        {"tipo": "Comprobante de domicilio", "obligatorio": True},
        {"tipo": "Estado de cuenta", "obligatorio": True},
    ],
    "_basico": _DOCS_COMPRADOR_BASE + [
        {"tipo": "Comprobante de domicilio", "obligatorio": True},
        {"tipo": "Estado de cuenta", "obligatorio": True},
    ],
}

def get_docs_comprador(tipo_compra: str) -> list:
    """Retorna la lista de documentos según tipo de compra."""
    return DOCS_COMPRADOR.get(tipo_compra, DOCS_COMPRADOR["_basico"])


@app.get("/portal-comprador", response_class=HTMLResponse)
async def portal_comprador_sin_id(request: Request):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    props = await get_properties_by_comprador(user["id"])

    if len(props) == 1:
        return RedirectResponse(f"/portal-comprador/{props[0]['id']}", status_code=302)
    elif len(props) > 1:
        return templates.TemplateResponse(request=request, name="portal_comprador.html", context={
            "user": user,
            "propiedad": None,
            "propiedades": props,
            "tipos_compra": TIPOS_COMPRA,
        })

    # Sin propiedad asignada → flujo de selección
    return RedirectResponse("/seleccionar-propiedad", status_code=302)


@app.get("/portal-comprador/{propiedad_id}", response_class=HTMLResponse)
async def portal_comprador(request: Request, propiedad_id: int):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    prop = await get_property_by_id(propiedad_id)
    if not prop:
        return RedirectResponse("/portal-comprador", status_code=302)

    # Permisos: admin, agente, o comprador asignado
    rol = user["rol"]
    es_comprador_asignado = prop.get("comprador_id") == user["id"]
    if rol not in ("admin", "agente") and not es_comprador_asignado:
        return RedirectResponse("/portal-comprador", status_code=302)

    # Checklist y documentos subidos
    checklist = []
    docs_subidos = {}
    progreso = None

    if prop.get("tipo_compra"):
        checklist = get_docs_comprador(prop["tipo_compra"])
        docs = await get_documentos_by_propiedad(propiedad_id)
        for d in docs:
            if d.get("categoria") == "comprador":
                docs_subidos[d["tipo_documento"]] = d

        total_oblig = sum(1 for d in checklist if d["obligatorio"])
        subidos_oblig = sum(1 for d in checklist if d["obligatorio"] and d["tipo"] in docs_subidos)
        progreso = {
            "subidos": len(docs_subidos),
            "total": len(checklist),
            "obligatorios_subidos": subidos_oblig,
            "obligatorios_total": total_oblig,
            "porcentaje": round(subidos_oblig / total_oblig * 100) if total_oblig > 0 else 0,
        }

    return templates.TemplateResponse(request=request, name="portal_comprador.html", context={
        "user": user,
        "propiedad": prop,
        "propiedades": [],
        "tipos_compra": TIPOS_COMPRA,
        "checklist": checklist,
        "docs_subidos": docs_subidos,
        "progreso": progreso,
    })


@app.post("/portal-comprador/tipo-compra")
async def guardar_tipo_compra(request: Request):
    user = await require_auth(request)
    if not user:
        return JSONResponse({"success": False, "error": "No autenticado"}, status_code=401)

    form = await request.form()
    propiedad_id = int(form.get("propiedad_id", 0))
    tipo_compra = form.get("tipo_compra", "").strip()

    if not propiedad_id or tipo_compra not in TIPOS_COMPRA:
        return JSONResponse({"success": False, "error": "Datos inválidos"}, status_code=400)

    prop = await get_property_by_id(propiedad_id)
    if not prop:
        return JSONResponse({"success": False, "error": "Propiedad no encontrada"}, status_code=404)

    # Solo comprador asignado, agente o admin
    es_comprador_asignado = prop.get("comprador_id") == user["id"]
    if user["rol"] not in ("admin", "agente") and not es_comprador_asignado:
        return JSONResponse({"success": False, "error": "Sin permisos"}, status_code=403)

    # Si ya tiene tipo_compra, no permitir cambio
    if prop.get("tipo_compra"):
        return JSONResponse({"success": False, "error": "El tipo de compra ya fue seleccionado"}, status_code=400)

    await set_tipo_compra(propiedad_id, tipo_compra)
    return RedirectResponse(f"/portal-comprador/{propiedad_id}", status_code=302)


# ─── Selección de propiedad (onboarding vendedor/comprador) ─────────

@app.get("/seleccionar-propiedad", response_class=HTMLResponse)
async def seleccionar_propiedad_page(request: Request, agente_id: Optional[str] = None):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    if user["rol"] not in ("vendedor", "comprador"):
        return RedirectResponse("/dashboard", status_code=302)

    # Convert agente_id to int safely (dropdown sends "" when nothing selected)
    try:
        agente_id = int(agente_id) if agente_id else None
    except (ValueError, TypeError):
        agente_id = None

    agentes = await get_users_by_rol("agente") + await get_users_by_rol("admin")
    propiedades = []

    if agente_id:
        todas = await get_properties_by_user(agente_id)
        # Filtrar: solo propiedades sin vendedor/comprador asignado según el rol
        for p in todas:
            if not p.get("activa", True):
                continue
            if user["rol"] == "vendedor" and not p.get("vendedor_id"):
                propiedades.append(p)
            elif user["rol"] == "comprador" and not p.get("comprador_id"):
                propiedades.append(p)

    return templates.TemplateResponse(request=request, name="seleccionar_propiedad.html", context={
        "user": user,
        "agentes": agentes,
        "agente_id": agente_id,
        "propiedades": propiedades,
    })


@app.post("/seleccionar-propiedad")
async def seleccionar_propiedad_submit(request: Request):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    if user["rol"] not in ("vendedor", "comprador"):
        return RedirectResponse("/dashboard", status_code=302)

    form = await request.form()
    propiedad_id = int(form.get("propiedad_id", 0))
    if not propiedad_id:
        return RedirectResponse("/seleccionar-propiedad", status_code=302)

    prop = await get_property_by_id(propiedad_id)
    if not prop:
        return RedirectResponse("/seleccionar-propiedad", status_code=302)

    # Asignar según rol
    if user["rol"] == "vendedor":
        if prop.get("vendedor_id"):
            return RedirectResponse("/seleccionar-propiedad", status_code=302)
        await update_property(propiedad_id, {"vendedor_id": user["id"]})
        return RedirectResponse("/mis-documentos", status_code=302)
    else:
        if prop.get("comprador_id"):
            return RedirectResponse("/seleccionar-propiedad", status_code=302)
        await update_property(propiedad_id, {"comprador_id": user["id"]})
        return RedirectResponse("/portal-comprador", status_code=302)


# ─── Subida simplificada de propiedad (vendedor) ─────────

@app.get("/nueva-propiedad-vendedor", response_class=HTMLResponse)
async def nueva_propiedad_vendedor_page(request: Request):
    user = await require_auth(request)
    if not user or user["rol"] != "vendedor":
        return RedirectResponse("/login", status_code=302)
    # Necesita haber seleccionado al menos un agente antes
    props = await get_properties_by_vendedor(user["id"])
    # Obtener agentes disponibles
    agentes = await get_users_by_rol("agente") + await get_users_by_rol("admin")
    return templates.TemplateResponse(request=request, name="nueva_propiedad_vendedor.html", context={
        "user": user,
        "agentes": agentes,
    })

@app.post("/nueva-propiedad-vendedor")
async def nueva_propiedad_vendedor_submit(request: Request):
    user = await require_auth(request)
    if not user or user["rol"] != "vendedor":
        return RedirectResponse("/login", status_code=302)

    form = await request.form()
    tipo_propiedad = form.get("tipo_propiedad", "Casa")
    operacion = form.get("operacion", "Venta")
    direccion = form.get("direccion", "")
    ciudad = form.get("ciudad", "")
    precio = form.get("precio", "")
    recamaras = form.get("recamaras", "")
    banos = form.get("banos", "")
    metros_construidos = form.get("metros_construidos", "")
    agente_id = form.get("agente_id")

    if not direccion or not ciudad or not agente_id:
        return RedirectResponse("/nueva-propiedad-vendedor", status_code=302)

    try:
        agente_id = int(agente_id)
    except (ValueError, TypeError):
        return RedirectResponse("/nueva-propiedad-vendedor", status_code=302)

    # Formatear precio
    precio_num = None
    precio_formateado = ""
    if precio:
        try:
            precio_num = float(precio.replace(",", "").replace("$", ""))
            precio_formateado = f"${precio_num:,.0f} MXN"
        except ValueError:
            precio_formateado = precio

    # Guardar fotos si las hay
    fotos_files = form.getlist("fotos")
    session_id = str(uuid.uuid4())
    foto_portada_url = None
    fotos_extra_urls = []

    valid_fotos = [f for f in fotos_files if hasattr(f, 'filename') and f.filename and f.size > 0]
    if valid_fotos:
        session_upload_dir = UPLOAD_DIR / session_id
        session_upload_dir.mkdir(parents=True, exist_ok=True)
        for i, foto in enumerate(valid_fotos):
            ext = Path(foto.filename).suffix.lower()
            if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
                continue
            filename = f"{i:03d}{ext}"
            dest = session_upload_dir / filename
            with open(dest, "wb") as buffer:
                shutil.copyfileobj(foto.file, buffer)
            url = f"/static/uploads/{session_id}/{filename}"
            if i == 0:
                foto_portada_url = url
            else:
                fotos_extra_urls.append(url)

    db_data = {
        "tipo_propiedad": tipo_propiedad,
        "operacion": operacion,
        "direccion": direccion,
        "ciudad": ciudad,
        "precio": precio_num,
        "precio_formateado": precio_formateado,
        "recamaras": recamaras or None,
        "banos": banos or None,
        "metros_construidos": metros_construidos or None,
        "foto_portada_url": foto_portada_url,
        "fotos_extra_urls": fotos_extra_urls,
        "session_id": session_id,
        "user_id": agente_id,
        "vendedor_id": user["id"],
        "activa": True,
    }

    await save_property(db_data)
    return RedirectResponse("/mis-documentos", status_code=302)


# ═══════════════════════════════════════════════════════════
# REstateFlow — Accountability & KPIs
# ═══════════════════════════════════════════════════════════

@app.get("/restateflow", response_class=HTMLResponse)
async def restateflow_page(request: Request, vista: str = "dashboard"):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user["rol"] not in ("admin", "agente"):
        return RedirectResponse("/", status_code=302)

    context = {"user": user, "vista": vista}

    # Sprint activo
    sprint = await get_sprint_activo()
    context["sprint"] = sprint

    # Bloqueos activos
    if user["rol"] == "admin":
        bloqueos = await get_bloqueos_activos()
    else:
        bloqueos = await get_bloqueos_activos(agente_id=user["id"])
    context["bloqueos_activos"] = bloqueos

    if vista == "dashboard":
        # Standup
        context["standup_hoy"] = await get_standup_hoy(user["id"])

        if user["rol"] == "admin":
            agentes_kpis = await get_kpis_todos_agentes()
            context["agentes_kpis"] = agentes_kpis
            context["kpis_global"] = {
                "total_propiedades": sum(a["total_asignadas"] for a in agentes_kpis),
                "total_ventas": sum(a["ventas_completadas"] for a in agentes_kpis),
                "total_docs_pendientes": sum(a["docs_pendientes_72h"] for a in agentes_kpis),
                "total_prospectos": agentes_kpis[0]["prospectos_30d"] if agentes_kpis else 0,
            }
        else:
            context["mis_kpis"] = await get_kpis_agente(user["id"])

    elif vista == "scrum":
        if sprint:
            if user["rol"] == "admin":
                context["sprint_items"] = await get_sprint_items(sprint["id"])
            else:
                context["sprint_items"] = await get_sprint_items(sprint["id"], agente_id=user["id"])
            # Propiedades disponibles para agregar
            all_props = await get_all_properties(active_only=True, limit=200, offset=0)
            items_ids = {i["propiedad_id"] for i in context["sprint_items"]}
            context["propiedades_disponibles"] = [p for p in all_props if p["id"] not in items_ids]
        else:
            context["sprint_items"] = []
            context["propiedades_disponibles"] = []

    elif vista == "referidos":
        context["referidos_kpis"] = await get_kpis_todos_referidos()

    elif vista == "review":
        if user["rol"] != "admin":
            return RedirectResponse("/restateflow", status_code=302)
        context["sprints_historial"] = await get_sprints_historial()
        # Último sprint cerrado para review
        historial = context["sprints_historial"]
        cerrados = [s for s in historial if s["estado"] == "cerrado"]
        if cerrados:
            context["review_data"] = await get_sprint_review_data(cerrados[0]["id"])
        else:
            context["review_data"] = {}

    return templates.TemplateResponse(request=request, name="restateflow.html", context=context)


# ── Sprint CRUD routes ──

@app.post("/restateflow/sprint/crear")
async def restateflow_crear_sprint(request: Request):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    form = await request.form()
    nombre = form.get("nombre", "")
    fecha_inicio = form.get("fecha_inicio", "")
    fecha_fin = form.get("fecha_fin", "")
    meta_texto = form.get("meta_texto", "")
    if nombre and fecha_inicio and fecha_fin:
        await crear_sprint(nombre, fecha_inicio, fecha_fin, meta_texto, user["id"])
    return RedirectResponse("/restateflow?vista=scrum", status_code=302)


@app.post("/restateflow/sprint/cerrar")
async def restateflow_cerrar_sprint(request: Request):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    form = await request.form()
    sprint_id = int(form.get("sprint_id", 0))
    if sprint_id:
        await cerrar_sprint(sprint_id)
    return RedirectResponse("/restateflow?vista=review", status_code=302)


@app.post("/restateflow/sprint/agregar")
async def restateflow_agregar_item(request: Request):
    user = await require_auth(request)
    if not user or user["rol"] not in ("admin", "agente"):
        return RedirectResponse("/login", status_code=302)
    form = await request.form()
    sprint_id = int(form.get("sprint_id", 0))
    propiedad_id = int(form.get("propiedad_id", 0))
    if sprint_id and propiedad_id:
        await agregar_sprint_item(sprint_id, propiedad_id, user["id"])
    return RedirectResponse("/restateflow?vista=scrum", status_code=302)


@app.post("/restateflow/sprint/mover")
async def restateflow_mover_item(request: Request):
    user = await require_auth(request)
    if not user or user["rol"] not in ("admin", "agente"):
        return RedirectResponse("/login", status_code=302)
    form = await request.form()
    item_id = int(form.get("item_id", 0))
    columna = form.get("columna", "")
    bloqueo_texto = form.get("bloqueo_texto", "")
    if item_id and columna in ("para_esta_semana", "en_progreso", "bloqueado", "por_revisar", "completado"):
        await mover_sprint_item(item_id, columna, bloqueo_texto or None)
    return RedirectResponse("/restateflow?vista=scrum", status_code=302)


# ── Daily Standup ──

@app.post("/restateflow/standup")
async def restateflow_standup(request: Request):
    user = await require_auth(request)
    if not user or user["rol"] not in ("admin", "agente"):
        return RedirectResponse("/login", status_code=302)
    form = await request.form()
    que_avance = form.get("que_avance", "")
    bloqueos_text = form.get("bloqueos", "")
    plan_hoy = form.get("plan_hoy", "")
    sprint = await get_sprint_activo()
    sprint_id = sprint["id"] if sprint else None
    if que_avance and plan_hoy:
        await guardar_standup(user["id"], sprint_id, que_avance, bloqueos_text, plan_hoy)
    return RedirectResponse("/restateflow", status_code=302)


# ── Bloqueos ──

@app.post("/restateflow/bloqueo/crear")
async def restateflow_crear_bloqueo(request: Request):
    user = await require_auth(request)
    if not user or user["rol"] not in ("admin", "agente"):
        return RedirectResponse("/login", status_code=302)
    form = await request.form()
    sprint_item_id = int(form.get("sprint_item_id", 0))
    descripcion = form.get("descripcion", "")
    categoria = form.get("categoria", "")
    if sprint_item_id and descripcion:
        # Obtener propiedad_id del sprint item
        items = await database.fetch_one(
            "SELECT propiedad_id FROM sprint_items WHERE id = :id", {"id": sprint_item_id}
        )
        if items:
            await registrar_bloqueo(sprint_item_id, items["propiedad_id"], user["id"], descripcion, categoria)
            # Mover item a bloqueado
            await mover_sprint_item(sprint_item_id, "bloqueado", descripcion)
    return RedirectResponse("/restateflow?vista=scrum", status_code=302)


@app.post("/restateflow/bloqueo/{bloqueo_id}/resolver")
async def restateflow_resolver_bloqueo(request: Request, bloqueo_id: int):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    form = await request.form()
    accion = form.get("accion", "Resuelto")
    await resolver_bloqueo(bloqueo_id, accion, user["id"])
    return RedirectResponse("/restateflow", status_code=302)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
