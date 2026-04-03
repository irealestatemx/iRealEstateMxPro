import os
import io
import json
import uuid
import shutil
import asyncio
import subprocess
from pathlib import Path
from typing import List, Optional, Dict

from fastapi import FastAPI, Request, Form, File, UploadFile, Depends
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse, RedirectResponse
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
    authenticate_user, get_user_by_id, get_all_users, create_user,
    update_user, delete_user, seed_admin_user,
    get_properties_by_user,
    get_user_by_prefijo, get_all_referidos,
    create_prospecto, get_all_prospectos, get_prospecto_by_id,
    update_prospecto, count_prospectos, delete_prospecto,
)

# ─── Sesiones con cookie firmada ───
SECRET_KEY = os.getenv("SECRET_KEY", "irealestatemx-secret-key-change-me-2026")
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

# Tracking de renderizados de video en progreso
video_jobs: Dict[str, dict] = {}

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ─── Utilidades ───

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

    # ══════════════════════════════════════
    # PAGINA 1 — Portada + datos principales
    # ══════════════════════════════════════
    pdf.add_page()

    # ── Badge tipo + operacion ──
    badge_text = s(f"  {data['tipo_propiedad']} en {data['operacion']}  ")
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(*PropertyPDF.NAVY)
    pdf.set_text_color(*PropertyPDF.WHITE)
    badge_w = pdf.get_string_width(badge_text) + 8
    pdf.cell(badge_w, 7, badge_text, ln=False, fill=True)
    pdf.ln(10)

    # ── Precio ──
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(*PropertyPDF.NAVY)
    pdf.cell(0, 12, s(data.get("precio_formateado", "")), ln=True)

    # ── Ubicacion ──
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*PropertyPDF.GRAY_TEXT)
    ubicacion = f"{data.get('direccion', '')}, {data.get('ciudad', '')}, {data.get('estado', '')}"
    pdf.cell(0, 6, s(ubicacion), ln=True)
    pdf.ln(4)

    # ── Foto de portada ──
    portada_url = data.get("foto_portada_url")
    if portada_url:
        portada_path = url_to_filepath(portada_url)
        if portada_path.exists():
            try:
                pdf.image(str(portada_path), x=10, w=190)
                pdf.ln(4)
            except Exception:
                pass

    # ── Fotos extras (miniaturas en fila) ──
    fotos_extra = data.get("fotos_extra_urls", [])
    if fotos_extra:
        x_start = 10
        thumb_w = 35
        gap = 3
        x = x_start
        for url in fotos_extra[:4]:
            fpath = url_to_filepath(url)
            if fpath.exists():
                try:
                    pdf.image(str(fpath), x=x, y=pdf.get_y(), w=thumb_w, h=thumb_w * 0.75)
                    x += thumb_w + gap
                except Exception:
                    pass
        pdf.ln(thumb_w * 0.75 + 4)

    # ── Caracteristicas (grid visual) ──
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
        specs.append(("Estacionam.", str(data["estacionamientos"])))

    if specs:
        # Verificar si hay espacio suficiente, si no, nueva pagina
        if pdf.get_y() > 245:
            pdf.add_page()

        pdf.section_title("Caracteristicas")
        col_w = 190 / min(len(specs), 5)
        pdf.set_fill_color(*PropertyPDF.GRAY_LIGHT)
        row_y = pdf.get_y()
        pdf.rect(10, row_y, 190, 18, "F")

        for label, value in specs:
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(*PropertyPDF.NAVY)
            pdf.cell(col_w, 10, s(value), align="C")
        pdf.ln()
        pdf.set_x(10)
        for label, value in specs:
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(*PropertyPDF.GRAY_TEXT)
            pdf.cell(col_w, 6, s(label), align="C")
        pdf.ln(10)

    # ── Amenidades ──
    amenidades = data.get("amenidades", [])
    if amenidades:
        if pdf.get_y() > 255:
            pdf.add_page()

        pdf.section_title("Amenidades")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*PropertyPDF.DARK)

        x = 10
        y = pdf.get_y()
        for a in amenidades:
            tag_text = s(f"  {a}  ")
            tag_w = pdf.get_string_width(tag_text) + 4
            if x + tag_w > 200:
                x = 10
                y += 8
                pdf.set_y(y)
            pdf.set_xy(x, y)
            pdf.set_fill_color(*PropertyPDF.GRAY_LIGHT)
            pdf.set_draw_color(200, 200, 200)
            pdf.cell(tag_w, 6.5, tag_text, border=1, fill=True, align="C")
            x += tag_w + 3
        pdf.ln(12)

    # ══════════════════════════════════════
    # PAGINA 2 — Descripcion + Agente
    # ══════════════════════════════════════
    descripcion = data.get("descripcion_profesional", "")
    if descripcion:
        if pdf.get_y() > 200:
            pdf.add_page()

        pdf.section_title("Descripcion de la propiedad")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*PropertyPDF.DARK)
        pdf.multi_cell(190, 5, s(descripcion))
        pdf.ln(6)

    # ── Datos de contacto del agente ──
    if pdf.get_y() > 245:
        pdf.add_page()

    pdf.section_title("Agente de contacto")
    pdf.set_fill_color(*PropertyPDF.GRAY_LIGHT)
    box_y = pdf.get_y()
    pdf.rect(10, box_y, 190, 22, "F")

    # Avatar
    pdf.set_fill_color(*PropertyPDF.NAVY)
    pdf.rect(14, box_y + 3, 16, 16, "F")
    nombre = data.get("agente_nombre", "")
    initial = s(nombre[0].upper()) if nombre else "A"
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*PropertyPDF.WHITE)
    pdf.set_xy(14, box_y + 7)
    pdf.cell(16, 8, initial, align="C")

    pdf.set_xy(34, box_y + 3)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*PropertyPDF.NAVY)
    pdf.cell(80, 6, s(nombre))

    pdf.set_xy(34, box_y + 9)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*PropertyPDF.GRAY_TEXT)
    pdf.cell(80, 5, s(f"Tel: {data.get('agente_telefono', '')}"))

    pdf.set_xy(34, box_y + 14)
    pdf.cell(80, 5, s(f"Email: {data.get('agente_email', '')}"))

    pdf.ln(28)

    # ══════════════════════════════════════
    # PAGINAS EXTRA — Cada foto en grande
    # ══════════════════════════════════════
    all_photo_urls = []
    if portada_url:
        all_photo_urls.append(portada_url)
    all_photo_urls.extend(fotos_extra)

    if len(all_photo_urls) > 1:
        for i, url in enumerate(all_photo_urls):
            fpath = url_to_filepath(url)
            if not fpath.exists():
                continue
            try:
                pdf.add_page()
                label = "Foto de portada" if i == 0 else f"Foto {i + 1} de {len(all_photo_urls)}"
                pdf.section_title(label)

                # Calcular tamano maximo que cabe en la pagina
                # Espacio disponible: ancho 190mm, alto ~220mm (despues de header + titulo)
                avail_w = 190
                avail_h = 220
                pdf.image(str(fpath), x=10, y=pdf.get_y(), w=avail_w, h=0)
            except Exception:
                pass

    return pdf.output()


# ─── Generacion de imagen Instagram ───

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
            bg = Image.open(portada_path).convert("RGBA")
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
        logo_img = Image.open(logo_path).convert("RGBA")
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
        logo_full = Image.open(logo_full_path).convert("RGBA")
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
    redirect_url = "/mis-prospectos" if user["rol"] == "referido" else "/"
    response = RedirectResponse(redirect_url, status_code=302)
    response.set_cookie("session", token, max_age=SESSION_MAX_AGE, httponly=True, samesite="lax")
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("session")
    return response


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request=request, name="index.html", context={"user": user})


# ─── Panel de Usuarios (solo admin) ───

@app.get("/admin/usuarios", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    users = await get_all_users()
    return templates.TemplateResponse(request=request, name="admin_users.html", context={"user": user, "users": users})


@app.post("/admin/usuarios/crear")
async def admin_create_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    nombre: str = Form(...),
    rol: str = Form("agente"),
    prefijo_whatsapp: str = Form(""),
):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    try:
        user_id = await create_user(email, password, nombre, rol)
        if prefijo_whatsapp.strip():
            await update_user(user_id, {"prefijo_whatsapp": prefijo_whatsapp.strip().upper()})
    except Exception as e:
        print(f"[AUTH] Error creando usuario: {e}")
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
            props = await get_all_properties(active_only=False, limit=100)
        agents = await get_all_users()
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

    return templates.TemplateResponse(request=request, name="edit_property.html", context={
        "user": user,
        "prop": prop,
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
    }
    await update_property(prop_id, updates)
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
async def admin_prospectos_page(request: Request, referido: Optional[str] = None, estado: Optional[str] = None):
    user = await require_auth(request)
    if not user or user["rol"] != "admin":
        return RedirectResponse("/login", status_code=302)
    referido_id = int(referido) if referido and referido.isdigit() else None
    prospectos = await get_all_prospectos(referido_id=referido_id)
    if estado:
        prospectos = [p for p in prospectos if p["estado"] == estado]
    counts = await count_prospectos()
    referidos = await get_all_referidos()

    for p in prospectos:
        for k, v in p.items():
            if hasattr(v, 'isoformat'):
                p[k] = v.isoformat()
            elif not isinstance(v, (int, float, str, bool, list, dict, type(None))):
                p[k] = str(v)

    return templates.TemplateResponse(request=request, name="admin_prospectos.html", context={
        "user": user,
        "prospectos": prospectos,
        "counts": counts,
        "referidos": referidos,
        "selected_referido": referido_id,
        "selected_estado": estado or "",
    })


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


# ─── API: Debounce de mensajes WhatsApp ───
# Acumula mensajes del mismo numero y espera a que termine de escribir
# Tambien registra prospecto y crea lead en Kommo (una sola vez)

_message_buffer: Dict[str, dict] = {}
_kommo_created: Dict[str, float] = {}  # telefono -> timestamp de ultimo lead creado
_paused_chats: Dict[str, float] = {}  # telefono -> timestamp de cuando se pauso
PAUSE_DURATION = 3600 * 4  # 4 horas de pausa por defecto

KOMMO_SUBDOMAIN = os.getenv("KOMMO_SUBDOMAIN", "irealestatemxclaude")
KOMMO_ACCESS_TOKEN = os.getenv("KOMMO_ACCESS_TOKEN", "")
KOMMO_PIPELINE_ID = 13474343
KOMMO_STATUS_ID = 103949563


async def _create_kommo_lead(phone: str, name: str):
    """Crea un lead en Kommo si no se creo uno para este telefono en las ultimas 24h."""
    import time
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
    import time
    _paused_chats[phone] = time.time()
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
    """Lista todos los chats pausados."""
    import time
    now = time.time()
    active = {k: round((PAUSE_DURATION - (now - v)) / 60) for k, v in _paused_chats.items() if now - v < PAUSE_DURATION}
    return JSONResponse({"paused": active})


@app.post("/api/whatsapp/debounce")
async def whatsapp_debounce(request: Request):
    """
    Recibe cada mensaje de WhatsApp. Acumula mensajes del mismo telefono
    y espera 12 segundos sin nuevos mensajes antes de devolver el resultado.
    Si es el ultimo mensaje, registra prospecto y crea lead en Kommo.
    """
    body = await request.json()
    phone = body.get("phone", "")
    message = body.get("message", "")
    name = body.get("name", "")
    chat_id = body.get("chatId", "")
    prefijo = body.get("prefijo", "")
    desarrollo = body.get("desarrollo", "")

    import time

    # ─── Verificar si el bot esta pausado para este numero ───
    if phone in _paused_chats:
        elapsed = time.time() - _paused_chats[phone]
        if elapsed < PAUSE_DURATION:
            return JSONResponse({"process": False, "reason": "paused"})
        else:
            _paused_chats.pop(phone, None)  # Ya expiro la pausa
    now = time.time()

    # Acumular mensaje en el buffer
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

    # Verificar si llegaron mas mensajes despues del nuestro
    if phone in _message_buffer and _message_buffer[phone]["sequence"] != my_sequence:
        return JSONResponse({"process": False})

    # Somos el ultimo mensaje, combinar todo y responder
    if phone in _message_buffer:
        final = _message_buffer.pop(phone)
        combined = "\n".join(final["messages"])

        # ─── Registrar prospecto en nuestra BD (una vez) ───
        try:
            referido = None
            if final["prefijo"]:
                referido = await get_user_by_prefijo(final["prefijo"])
            await create_prospecto({
                "referido_id": referido["id"] if referido else None,
                "nombre_cliente": final["name"],
                "telefono_cliente": phone,
                "mensaje_original": combined,
                "prefijo": final["prefijo"],
                "desarrollo_interes": final["desarrollo"],
                "estado": "nuevo",
            })
        except Exception as e:
            print(f"[PROSPECTO] Error: {e}")

        # ─── Crear lead en Kommo (una vez cada 24h por telefono) ───
        await _create_kommo_lead(phone, final["name"])

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

    # Buscar referido por prefijo
    referido = None
    if prefijo:
        referido = await get_user_by_prefijo(prefijo)

    data = {
        "referido_id": referido["id"] if referido else None,
        "nombre_cliente": nombre,
        "telefono_cliente": telefono,
        "mensaje_original": mensaje,
        "prefijo": prefijo,
        "desarrollo_interes": desarrollo,
        "estado": "nuevo",
    }
    prospecto_id = await create_prospecto(data)
    return JSONResponse({
        "ok": True,
        "prospecto_id": prospecto_id,
        "referido": referido["nombre"] if referido else None,
    })


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
    tipo_propiedad: str = Form(...),
    operacion: str = Form(...),
    direccion: str = Form(...),
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
    fotos: List[UploadFile] = File(default=[]),
):
    # Auth check
    user = await require_auth(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    # Recoger amenidades desde el form (checkboxes)
    form_data = await request.form()
    amenidades = form_data.getlist("amenidades")

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
    descripcion_profesional = generate_professional_description(summary)
    instagram_copy = generate_instagram_copy(summary, tipo_propiedad, operacion, ciudad)

    precio_formateado = format_price(float(precio.replace(",", "").replace("$", "").strip()))

    context = {
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
        "instagram_copy": instagram_copy,
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
        context["property_id"] = prop_id
    except Exception as e:
        print(f"[DB] Error guardando propiedad: {e}")
        context["property_id"] = None

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
    descripcion_profesional: str = Form(""),
):
    form_data = await request.form()
    amenidades = form_data.getlist("amenidades")
    fotos_extra_urls = form_data.getlist("fotos_extra_urls")

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


@app.post("/publish-instagram")
async def publish_instagram(
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
    instagram_copy: str = Form(""),
):
    """Genera la imagen IG y la publica via Upload Post API."""
    api_key = os.getenv("UPLOADPOST_API_KEY", "")
    user = os.getenv("UPLOADPOST_USER", "")

    if not api_key or not user:
        return {"success": False, "error": "Faltan las variables UPLOADPOST_API_KEY o UPLOADPOST_USER en el .env"}

    # Generar la imagen
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

    # Llamar a Upload Post API
    try:
        async with httpx.AsyncClient(timeout=120.0) as client_http:
            response = await client_http.post(
                "https://api.upload-post.com/api/upload_photos",
                headers={
                    "Authorization": f"Apikey {api_key}",
                },
                data={
                    "user": user,
                    "platform[]": "instagram",
                    "title": instagram_copy,
                },
                files={
                    "photos[]": ("instagram_post.jpg", img_bytes, "image/jpeg"),
                },
            )

        result = response.json()

        if response.status_code == 200 and result.get("success"):
            ig_result = result.get("results", {}).get("instagram", {})
            post_url = ig_result.get("url", "")
            # Marcar como publicada en DB si tenemos el session_id
            try:
                form = await request.form()
                sid = form.get("session_id", "")
                if sid:
                    from database import get_property_by_session
                    prop = await get_property_by_session(sid)
                    if prop:
                        await update_property(prop["id"], {"publicada_instagram": True})
            except Exception:
                pass
            return {
                "success": True,
                "message": "Publicado exitosamente en Instagram",
                "post_url": post_url,
            }
        elif response.status_code == 202:
            return {
                "success": True,
                "message": "Publicacion programada exitosamente",
                "job_id": result.get("job_id", ""),
            }
        else:
            error_msg = result.get("error") or result.get("message") or f"Error HTTP {response.status_code}"
            return {"success": False, "error": error_msg}

    except httpx.TimeoutException:
        return {"success": False, "error": "Timeout: la publicacion esta siendo procesada en segundo plano"}
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
    img = Image.open(path).convert("RGB")
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
        logo = Image.open(logo_path).convert("RGBA")
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
        logo = Image.open(logo_path).convert("RGBA")
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
        logo = Image.open(logo_path).convert("RGBA")
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
    """Renderiza el reel MP4 con MoviePy + Pillow (puro Python)."""
    from moviepy import ImageClip, concatenate_videoclips
    import numpy as np

    photos = data.get("photos", [])
    scenes = []

    # Escena 1: Cover — Ken Burns zoom IN
    if photos:
        ov_cover = _build_overlay_cover(data)
        clip = _make_kb_clip(photos[0], ov_cover, COVER_SECS, "in")
        scenes.append(clip)
        video_jobs[job_id]["progress"] = 20

    # Escena 2: Specs — Ken Burns zoom OUT
    if len(photos) > 1:
        ov_specs = _build_overlay_specs(data)
        clip = _make_kb_clip(photos[1], ov_specs, SCENE_SECS, "out")
        scenes.append(clip)
        video_jobs[job_id]["progress"] = 35

    # Escenas intermedias: detail — alternar zoom in/out
    detail_start = 2
    for i in range(min(len(photos) - detail_start, 3)):
        idx = detail_start + i
        if idx < len(photos):
            ov_detail = _build_overlay_detail(data)
            direction = "in" if i % 2 == 0 else "out"
            clip = _make_kb_clip(photos[idx], ov_detail, SCENE_SECS, direction)
            scenes.append(clip)
        video_jobs[job_id]["progress"] = 35 + (i + 1) * 10

    # Escena final: contacto — estatica (sin foto, fondo navy)
    contact_img = _build_scene_contact(data)
    clip = ImageClip(_pil_to_frame(contact_img), duration=CONTACT_SECS)
    scenes.append(clip)
    video_jobs[job_id]["progress"] = 70

    # Concatenar y exportar
    final = concatenate_videoclips(scenes, method="compose")
    video_jobs[job_id]["progress"] = 80

    final.write_videofile(
        str(output_path),
        fps=FPS_VID,
        codec="libx264",
        audio=False,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
