"""
bot_claude.py — Cerebro del chatbot de WhatsApp con Claude (Anthropic).

Reemplaza al "AI Agent" de n8n/OpenAI. Corre nativo dentro de la app FastAPI.
- Modelo configurable (default: claude-sonnet-5).
- Tool use: `buscar_propiedades` llama DIRECTO a la BD (sin HTTP intermedio).
- Prompt caching: la persona + catálogo de desarrollos se cachean (system prompt).
- Memoria de conversación por teléfono (la maneja main.py y se pasa aquí).

Requiere la variable de entorno ANTHROPIC_API_KEY.
"""

import os
import json
from typing import List, Dict, Tuple, Optional

from anthropic import AsyncAnthropic

from database import search_properties, search_desarrollos

# ─────────────────────────────────────────────────────────────
# Cliente (se crea una sola vez, perezoso)
# ─────────────────────────────────────────────────────────────
_client: Optional[AsyncAnthropic] = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        # Lee ANTHROPIC_API_KEY del entorno automáticamente
        _client = AsyncAnthropic()
    return _client


def bot_configurado() -> bool:
    """True si hay API key de Anthropic disponible."""
    return bool(os.getenv("ANTHROPIC_API_KEY"))


DEFAULT_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
MAX_TOOL_ITERS = 4          # tope de vueltas del loop de herramientas
MAX_TOKENS = 1024           # respuestas de WhatsApp son cortas


# ─────────────────────────────────────────────────────────────
# Herramienta: buscar propiedades / desarrollos
# ─────────────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "buscar_propiedades",
        "description": (
            "Busca propiedades y desarrollos REALES disponibles en el inventario de la "
            "inmobiliaria. Úsala SIEMPRE que el cliente pregunte por casas, departamentos, "
            "terrenos, precios, disponibilidad, ubicación o un desarrollo específico "
            "(ej: 'Cárcamos Residencial', 'Privada del Fresno'). NUNCA inventes propiedades, "
            "precios ni datos: responde solo con lo que devuelva esta herramienta. Si no hay "
            "resultados, dilo y ofrece que un asesor lo contacte."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Texto libre: nombre del desarrollo o palabras clave (ej: 'Carcamos', 'Fresno', 'residencial').",
                },
                "ciudad": {"type": "string", "description": "Ciudad, ej: León, Guanajuato, Irapuato."},
                "operacion": {"type": "string", "description": "'venta' o 'renta'."},
                "tipo": {"type": "string", "description": "casa, departamento, terreno, local, etc."},
                "precio_min": {"type": "number", "description": "Precio mínimo en MXN."},
                "precio_max": {"type": "number", "description": "Precio máximo en MXN."},
            },
        },
    },
    {
        "name": "agendar_cita",
        "description": (
            "Agenda una visita/cita cuando el cliente CONFIRMA un día y una hora concretos. "
            "Antes de llamarla debes tener: nombre del cliente, fecha y hora. Convierte SIEMPRE "
            "la fecha a formato YYYY-MM-DD y la hora a HH:MM en 24 horas (ej: las 5 de la tarde = 17:00). "
            "Usa la fecha de HOY que se indica en el contexto para resolver 'mañana', 'el viernes', etc. "
            "Si la herramienta devuelve que el horario está ocupado (horarios_disponibles), ofrécele "
            "esos horarios al cliente y vuelve a intentar cuando elija otro."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string", "description": "Nombre del cliente."},
                "fecha": {"type": "string", "description": "Fecha en formato YYYY-MM-DD."},
                "hora": {"type": "string", "description": "Hora en formato HH:MM (24h), ej: 17:00."},
                "desarrollo": {"type": "string", "description": "Desarrollo o propiedad a visitar."},
                "notas": {"type": "string", "description": "Notas u observaciones opcionales."},
            },
            "required": ["fecha", "hora"],
        },
    },
]


async def _ejecutar_buscar(args: dict) -> str:
    """Ejecuta la búsqueda real contra la BD y devuelve un JSON compacto para Claude."""
    try:
        props = await search_properties(
            ciudad=args.get("ciudad"),
            operacion=args.get("operacion"),
            tipo=args.get("tipo"),
            precio_min=args.get("precio_min"),
            precio_max=args.get("precio_max"),
            limit=8,
        )
        devs = await search_desarrollos(texto=args.get("q"), ciudad=args.get("ciudad"))
    except Exception as e:
        return json.dumps({"error": f"No se pudo consultar el inventario: {e}", "propiedades": [], "desarrollos": []})

    props_out = []
    for p in props:
        props_out.append({
            "tipo": p.get("tipo_propiedad"),
            "operacion": p.get("operacion"),
            "precio": str(p.get("precio_formateado") or ""),
            "ciudad": p.get("ciudad"),
            "direccion": p.get("direccion"),
            "recamaras": p.get("recamaras"),
            "banos": p.get("banos"),
            "metros": p.get("metros_construidos"),
            "descripcion": (p.get("descripcion_profesional") or "")[:280],
            "agente": p.get("agente_nombre"),
            "agente_tel": p.get("agente_telefono"),
        })

    devs_out = []
    for d in devs:
        devs_out.append({
            "nombre": d.get("nombre"),
            "ubicacion": d.get("ubicacion"),
            "ciudad": d.get("ciudad"),
            "precio_desde": str(d.get("precio_desde") or ""),
            "precio_hasta": str(d.get("precio_hasta") or ""),
            "descripcion": (d.get("descripcion") or "")[:400],
            "amenidades": d.get("amenidades"),
            "agente": d.get("agente_nombre"),
            "agente_tel": d.get("agente_telefono"),
        })

    return json.dumps({
        "propiedades": props_out,
        "desarrollos": devs_out,
        "total": len(props_out) + len(devs_out),
    }, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────
# System prompt (persona + catálogo). Se cachea.
# ─────────────────────────────────────────────────────────────
PERSONA_DEFAULT = """Eres el asistente virtual de iRealEstateMx, una inmobiliaria profesional en Guanajuato, México. Atiendes clientes por WhatsApp.

TU PERSONALIDAD:
- Cálido, cercano y profesional, como un asesor experto que de verdad conoce cada propiedad.
- Escribes en español mexicano, natural y humano. Nada robótico ni acartonado.
- Conciso: máximo 3–4 párrafos cortos. Es WhatsApp, no un correo.
- Persuasivo pero sin presionar. Generas confianza y avanzas hacia una cita o el contacto con un asesor.

FORMATO (WhatsApp):
- Texto plano. NADA de markdown: sin asteriscos, sin #, sin viñetas con guiones raros. Puedes usar saltos de línea y emojis con moderación.
- Fechas SIEMPRE en formato día/mes/año (DD/MM/YYYY). Ejemplo: 15/04/2026. NUNCA uses el formato estadounidense.
- Horas en formato 12h con a.m./p.m. en minúsculas: "5:00 p.m.".
- Zona horaria México (America/Mexico_City, es-MX).

UBICACIÓN (regla estricta):
- NO compartas la ubicación exacta ni el link de mapa de forma proactiva. No lo incluyas en tus respuestas a menos que el cliente lo PIDA explícitamente.
- Si el cliente pregunta por la ubicación/dirección/cómo llegar, puedes darle la zona general (ej: "cerca de ALAÏA") e invitarlo a agendar una visita. Comparte el link de mapa SOLO cuando lo pida directamente.
- Idealmente, la ubicación se comparte una vez que hay una cita agendada.

CÓMO TRABAJAS:
- Cuando el cliente pregunte por propiedades, desarrollos, precios o disponibilidad, usa la herramienta buscar_propiedades para consultar el inventario REAL. NUNCA inventes datos.
- Presenta los resultados de forma natural y atractiva, destacando lo que más le puede interesar según lo que pidió (presupuesto, zona, recámaras).
- Si un desarrollo coincide (como Cárcamos Residencial o Privada del Fresno), destácalo y ofrece enviarle la ficha técnica en PDF o agendar una visita.
- Si no encuentras algo que coincida, pide más detalles o sugiere ampliar la búsqueda, y ofrece que un asesor lo contacte personalmente.
- Siempre que tenga sentido, invita a agendar una cita o a que un asesor le dé seguimiento.
- Si te preguntan algo fuera de bienes raíces, redirige amablemente al tema.

AGENDAR CITAS (importante, sigue este orden):
1. Cuando el cliente quiera agendar una visita, primero confirma el DÍA y la HORA.
2. Antes de agendar, PREGUNTA explícitamente: "¿A nombre de quién agendo la cita?" y espera su respuesta. Usa ese nombre (el nombre completo que te dé el cliente), NO uses uno genérico.
3. Con nombre + día + hora, llama a la herramienta agendar_cita pasando el nombre tal cual, la fecha en formato YYYY-MM-DD y la hora en HH:MM (24h). Ejemplo: las 5 de la tarde = 17:00.
4. Si el horario está ocupado, ofrécele los horarios disponibles que devuelve la herramienta y vuelve a agendar cuando elija otro.
5. Al confirmar, repite los datos: nombre, fecha en DD/MM/YYYY y hora en formato 12h (ej: "5:00 p.m."), para que el cliente valide.
6. UNA VEZ AGENDADA la cita, NO la vuelvas a agendar ni llames otra vez a agendar_cita para esa misma cita. Si el cliente después pide la ubicación, el mapa u otra cosa, respóndele directamente eso que pide; su horario NO está "ocupado", esa cita es suya. Solo llama a agendar_cita de nuevo si el cliente pide EXPLÍCITAMENTE cambiar de día u hora.

PROPIETARIOS QUE QUIEREN VENDER O RENTAR (dueños que buscan que trabajemos su propiedad):
- Si detectas que la persona es DUEÑA de una propiedad y quiere VENDERLA o RENTARLA con nosotros (ej: "quiero vender mi casa", "tengo un terreno para vender", "quiero rentar mi departamento", "cómo trabajan con propietarios", "qué comisión cobran", "quiero que me ayuden a vender/rentar"), explícale brevemente el proceso y COMPARTE el PDF con la información según el caso:
  • VENTA: https://api.irealestatemx.cloud/static/docs/venta-propietarios.pdf
  • RENTA: https://api.irealestatemx.cloud/static/docs/renta-propietarios.pdf
- Comparte el enlace del PDF que corresponda (venta o renta) y ofrécele que un asesor lo contacte para iniciar el proceso. Si no queda claro si es venta o renta, pregúntaselo antes de mandar el PDF.
- No mezcles esto con los desarrollos (Cárcamos, Fresno): esos son para clientes COMPRADORES. Aquí el cliente es el DUEÑO que nos contrata.

Nunca inventes propiedades, precios ni promesas. Solo comparte información que provenga de la herramienta de búsqueda."""


def _fecha_hoy_mx() -> str:
    """Fecha/hora actual en México (Central, sin DST) como texto legible para el modelo."""
    from datetime import datetime, timedelta
    ahora = datetime.utcnow() - timedelta(hours=6)  # America/Mexico_City
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    return f"{dias[ahora.weekday()]} {ahora.strftime('%d/%m/%Y')} (ISO: {ahora.strftime('%Y-%m-%d')}), {ahora.strftime('%H:%M')} h"


def construir_system(persona: str, catalogo_texto: str) -> list:
    """Arma el system prompt como bloques. Cachea el bloque grande (persona + catálogo)
    y deja la fecha de hoy en un bloque aparte NO cacheado (cambia cada día)."""
    texto = persona.strip()
    if catalogo_texto:
        texto += "\n\n=== DESARROLLOS DESTACADOS (contexto de referencia) ===\n" + catalogo_texto.strip()
    return [
        {
            "type": "text",
            "text": texto,
            "cache_control": {"type": "ephemeral"},  # se cachea → lecturas siguientes ~10% del costo
        },
        {
            "type": "text",
            "text": f"Contexto: hoy es {_fecha_hoy_mx()} en Guanajuato, México. Úsalo para calcular fechas relativas al agendar citas.",
        },
    ]


# ─────────────────────────────────────────────────────────────
# Motor de conversación
# ─────────────────────────────────────────────────────────────
async def responder(
    mensaje: str,
    historial: List[Dict],
    persona: str,
    catalogo_texto: str,
    model: Optional[str] = None,
    agendar_cb=None,
) -> Tuple[str, List[Dict]]:
    """
    Genera la respuesta del bot.
    - mensaje: texto (combinado) del cliente.
    - historial: lista de mensajes previos [{role, content}] (sin el mensaje actual).
    - Devuelve (texto_respuesta, historial_actualizado).
    """
    client = _get_client()
    model = model or DEFAULT_MODEL
    system_blocks = construir_system(persona, catalogo_texto)

    # 'messages' es el hilo COMPLETO (incluye rondas de herramientas) que se envía a la API.
    messages = list(historial) + [{"role": "user", "content": mensaje}]

    async def _create():
        """Llama a la API. Si el SDK/modelo rechaza params opcionales, reintenta mínimo."""
        base = dict(model=model, max_tokens=MAX_TOKENS, system=system_blocks,
                    tools=TOOLS, messages=messages)
        try:
            extra = {"thinking": {"type": "disabled"}}
            if "haiku" not in model.lower():
                extra["output_config"] = {"effort": "low"}
            return await client.messages.create(**base, **extra)
        except Exception as e1:
            print(f"[BOT] create con params opcionales falló ({e1}); reintento mínimo")
            return await client.messages.create(**base)

    texto_final = ""
    for _ in range(MAX_TOOL_ITERS):
        resp = await _create()

        if resp.stop_reason == "refusal":
            texto_final = ("Disculpa, no puedo ayudarte con eso. ¿Te apoyo con información de "
                           "nuestras propiedades o desarrollos? 🏡")
            break

        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            resultados = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                if block.name == "buscar_propiedades":
                    salida = await _ejecutar_buscar(block.input or {})
                elif block.name == "agendar_cita":
                    if agendar_cb:
                        try:
                            salida = await agendar_cb(block.input or {})
                        except Exception as e:
                            salida = json.dumps({"ok": False, "error": f"No se pudo agendar: {e}"})
                    else:
                        salida = json.dumps({"ok": False, "error": "Agenda no disponible ahora."})
                else:
                    salida = json.dumps({"ok": False, "error": "Herramienta desconocida."})
                resultados.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": salida,
                })
            messages.append({"role": "user", "content": resultados})
            continue

        # end_turn / stop normal
        texto_final = "".join(b.text for b in resp.content if b.type == "text").strip()
        break

    if not texto_final:
        texto_final = ("Déjame confirmar esa información con un asesor y te contactamos en breve. "
                       "¿Me compartes tu nombre? 🙏")

    # Historial LIMPIO para persistir: solo user + assistant (texto), sin bloques de herramientas.
    # Así evitamos pares tool_use/tool_result huérfanos al recortar la memoria en turnos futuros.
    historial_limpio = list(historial) + [
        {"role": "user", "content": mensaje},
        {"role": "assistant", "content": texto_final},
    ]
    return texto_final, historial_limpio
