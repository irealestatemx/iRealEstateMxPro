"""
gcal.py — Integración con Google Calendar (cuenta de servicio).

Crea eventos directamente en el calendario de Google del negocio, como lo hacía
n8n. Usa una CUENTA DE SERVICIO (service account), ideal para servidores.

Config por variables de entorno:
- GOOGLE_SERVICE_ACCOUNT_JSON  = el JSON completo de la cuenta de servicio (contenido), o
- GOOGLE_SERVICE_ACCOUNT_FILE  = ruta al archivo .json de la cuenta de servicio
- GOOGLE_CALENDAR_ID           = ID del calendario (normalmente el correo del negocio,
                                 ej: irealestatemx@gmail.com). Default: 'primary'.

Pasos de configuración (una sola vez):
1. En Google Cloud Console: crea un proyecto → habilita "Google Calendar API".
2. Crea una cuenta de servicio y genera una llave JSON. Descárgala.
3. Copia el "client_email" de esa cuenta de servicio.
4. En Google Calendar (con la cuenta del negocio) → Configuración del calendario →
   "Compartir con determinadas personas" → agrega ese client_email con permiso
   "Hacer cambios en los eventos".
5. Pon GOOGLE_SERVICE_ACCOUNT_JSON (o _FILE) y GOOGLE_CALENDAR_ID en el .env.

Si no está configurado, las funciones devuelven None y el sistema sigue funcionando
(solo se manda la invitación .ics por correo como respaldo).
"""

import os
import json

_service = None
_TZ = "America/Mexico_City"
_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def calendar_configurado() -> bool:
    return bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE"))


def _get_service():
    """Construye (una vez) el cliente de Google Calendar. None si no está configurado."""
    global _service
    if _service is not None:
        return _service
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except Exception as e:
        print(f"[GCAL] Librerías de Google no instaladas: {e}")
        return None

    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    try:
        if raw:
            info = json.loads(raw)
            creds = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
        elif path and os.path.exists(path):
            creds = service_account.Credentials.from_service_account_file(path, scopes=_SCOPES)
        else:
            return None
        _service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return _service
    except Exception as e:
        print(f"[GCAL] Error creando cliente: {e}")
        return None


def crear_evento(summary: str, description: str, location: str,
                 fecha: str, hora: str, hora_fin: str) -> str:
    """Crea un evento en Google Calendar. SÍNCRONO (llamar con asyncio.to_thread).
    fecha=YYYY-MM-DD, hora/hora_fin=HH:MM. Devuelve el event_id, o '' si falla."""
    svc = _get_service()
    if not svc:
        return ""
    cal_id = os.getenv("GOOGLE_CALENDAR_ID", "primary").strip() or "primary"
    body = {
        "summary": summary,
        "description": description,
        "location": location,
        "start": {"dateTime": f"{fecha}T{hora}:00", "timeZone": _TZ},
        "end": {"dateTime": f"{fecha}T{hora_fin}:00", "timeZone": _TZ},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 120}],
        },
    }
    try:
        created = svc.events().insert(calendarId=cal_id, body=body).execute()
        print(f"[GCAL] Evento creado: {created.get('id')} en {cal_id}")
        return created.get("id", "")
    except Exception as e:
        print(f"[GCAL] Error creando evento: {e}")
        return ""
