import os
import io
import uuid
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import OpenAI
from dotenv import load_dotenv
from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import httpx

load_dotenv()

app = FastAPI(title="iRealEstateMxPro")

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

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

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
