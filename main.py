import os
import uuid
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="iRealEstateMxPro")

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def format_price(price: float) -> str:
    return f"${price:,.0f} MXN"


def build_property_summary(data: dict) -> str:
    amenidades = data.get("amenidades", [])
    amenidades_str = ", ".join(amenidades) if amenidades else "ninguna especificada"

    caracteristicas = []
    if data.get("recamaras"):
        caracteristicas.append(f"{data['recamaras']} recámaras")
    if data.get("banos"):
        caracteristicas.append(f"{data['banos']} baños")
    if data.get("metros_construidos"):
        caracteristicas.append(f"{data['metros_construidos']} m² construidos")
    if data.get("metros_terreno"):
        caracteristicas.append(f"{data['metros_terreno']} m² de terreno")
    if data.get("estacionamientos"):
        caracteristicas.append(f"{data['estacionamientos']} cajón(es) de estacionamiento")

    return f"""
Tipo de propiedad: {data['tipo_propiedad']}
Operación: {data['operacion']}
Ubicación: {data['direccion']}, {data['ciudad']}, {data['estado']}
Precio: {format_price(float(data['precio']))}
Características: {', '.join(caracteristicas) if caracteristicas else 'No especificadas'}
Amenidades: {amenidades_str}
Notas del agente: {data.get('descripcion_agente', '')}
""".strip()


def generate_professional_description(summary: str) -> str:
    prompt = f"""Eres un experto en marketing inmobiliario de México, especializado en el mercado de Guanajuato y León.
Con base en los siguientes datos de la propiedad, redacta una descripción profesional, atractiva y persuasiva de 150 a 200 palabras.
El tono debe ser formal-moderno, resaltar los puntos fuertes de la propiedad y motivar al comprador/arrendatario potencial a contactar al agente.
Escribe directamente la descripción, sin títulos ni encabezados.

Datos de la propiedad:
{summary}

Descripción profesional:"""

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

    prompt = f"""Eres un experto en redes sociales para el sector inmobiliario en México.
Con base en los siguientes datos de propiedad, crea un copy atractivo para Instagram.

Estructura requerida:
1. Texto principal: 2-3 oraciones impactantes, máximo 280 caracteres, con emoji(s) al inicio, llamada a la acción al final (ej: "¡Agenda tu visita hoy! 📲")
2. Salto de línea
3. Bloque de hashtags: exactamente 20 hashtags relevantes al mercado inmobiliario mexicano, la ciudad ({ciudad}) y el tipo de operación.

Hashtags sugeridos a incluir (puedes agregar más relevantes):
#BienesRaicesMexico #Inmobiliaria #InmobiliariaLeón #InmobiliariaGuanajuato #{ciudad_lower} #Guanajuato #{tipo_tag}{operacion_tag} #PropiedadesLeón #Mexico #CasasMexico #InversionInmobiliaria #PropiedadesMexico #RealtorMexico #AgentInmobiliario #ViveLeón

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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


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

    return templates.TemplateResponse("result.html", {
        "request": request,
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
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
