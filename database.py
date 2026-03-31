"""
Base de datos PostgreSQL para iRealEstateMxPro.
Guarda cada propiedad con todos sus datos, fotos, descripciones generadas, y estado.
"""

import os
import json
from datetime import datetime
from databases import Database

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://irealestate:irealestate_secret_2024@postgres:5432/irealestate"
)

database = Database(DATABASE_URL)


# ─── Esquema SQL ───

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS propiedades (
    id              SERIAL PRIMARY KEY,
    session_id      VARCHAR(64) UNIQUE NOT NULL,
    tipo_propiedad  VARCHAR(100),
    operacion       VARCHAR(50),
    direccion       VARCHAR(500),
    ciudad          VARCHAR(200),
    estado          VARCHAR(200),
    precio          NUMERIC(14, 2),
    precio_formateado VARCHAR(60),
    recamaras       VARCHAR(10),
    banos           VARCHAR(10),
    metros_construidos VARCHAR(20),
    metros_terreno  VARCHAR(20),
    estacionamientos VARCHAR(10),
    amenidades      JSONB DEFAULT '[]',
    descripcion_agente TEXT,
    descripcion_profesional TEXT,
    instagram_copy  TEXT,
    agente_nombre   VARCHAR(300),
    agente_telefono VARCHAR(50),
    agente_email    VARCHAR(300),
    foto_portada_url VARCHAR(500),
    fotos_extra_urls JSONB DEFAULT '[]',
    publicada_instagram BOOLEAN DEFAULT FALSE,
    publicada_web       BOOLEAN DEFAULT FALSE,
    activa              BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

"""

CREATE_DESARROLLOS = """
CREATE TABLE IF NOT EXISTS desarrollos (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(300) NOT NULL,
    descripcion     TEXT,
    ubicacion       VARCHAR(500),
    ciudad          VARCHAR(200),
    estado          VARCHAR(200),
    precio_desde    NUMERIC(14, 2),
    precio_hasta    NUMERIC(14, 2),
    tipo_propiedad  VARCHAR(100),
    amenidades      JSONB DEFAULT '[]',
    caracteristicas TEXT,
    agente_nombre   VARCHAR(300),
    agente_telefono VARCHAR(50),
    agente_email    VARCHAR(300),
    foto_portada_url VARCHAR(500),
    fotos_urls      JSONB DEFAULT '[]',
    pdf_url         VARCHAR(500),
    activo          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_propiedades_ciudad ON propiedades(ciudad);",
    "CREATE INDEX IF NOT EXISTS idx_propiedades_operacion ON propiedades(operacion);",
    "CREATE INDEX IF NOT EXISTS idx_propiedades_activa ON propiedades(activa);",
    "CREATE INDEX IF NOT EXISTS idx_propiedades_created ON propiedades(created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_desarrollos_ciudad ON desarrollos(ciudad);",
    "CREATE INDEX IF NOT EXISTS idx_desarrollos_activo ON desarrollos(activo);",
    "CREATE INDEX IF NOT EXISTS idx_desarrollos_nombre ON desarrollos(nombre);",
]


async def init_db():
    """Conecta y crea las tablas si no existen."""
    await database.connect()
    await database.execute(CREATE_TABLES)
    await database.execute(CREATE_DESARROLLOS)
    for idx in CREATE_INDEXES:
        await database.execute(idx)


async def close_db():
    """Cierra la conexion."""
    await database.disconnect()


async def save_property(data: dict) -> int:
    """Guarda una propiedad y devuelve su ID."""
    query = """
    INSERT INTO propiedades (
        session_id, tipo_propiedad, operacion, direccion, ciudad, estado,
        precio, precio_formateado, recamaras, banos, metros_construidos,
        metros_terreno, estacionamientos, amenidades, descripcion_agente,
        descripcion_profesional, instagram_copy,
        agente_nombre, agente_telefono, agente_email,
        foto_portada_url, fotos_extra_urls
    ) VALUES (
        :session_id, :tipo_propiedad, :operacion, :direccion, :ciudad, :estado,
        :precio, :precio_formateado, :recamaras, :banos, :metros_construidos,
        :metros_terreno, :estacionamientos, :amenidades::jsonb, :descripcion_agente,
        :descripcion_profesional, :instagram_copy,
        :agente_nombre, :agente_telefono, :agente_email,
        :foto_portada_url, :fotos_extra_urls::jsonb
    ) RETURNING id
    """
    values = {
        "session_id": data.get("session_id", ""),
        "tipo_propiedad": data.get("tipo_propiedad", ""),
        "operacion": data.get("operacion", ""),
        "direccion": data.get("direccion", ""),
        "ciudad": data.get("ciudad", ""),
        "estado": data.get("estado", ""),
        "precio": float(data.get("precio", "0").replace(",", "").replace("$", "").strip() or 0),
        "precio_formateado": data.get("precio_formateado", ""),
        "recamaras": data.get("recamaras"),
        "banos": data.get("banos"),
        "metros_construidos": data.get("metros_construidos"),
        "metros_terreno": data.get("metros_terreno"),
        "estacionamientos": data.get("estacionamientos"),
        "amenidades": json.dumps(data.get("amenidades", [])),
        "descripcion_agente": data.get("descripcion_agente"),
        "descripcion_profesional": data.get("descripcion_profesional"),
        "instagram_copy": data.get("instagram_copy"),
        "agente_nombre": data.get("agente_nombre", ""),
        "agente_telefono": data.get("agente_telefono", ""),
        "agente_email": data.get("agente_email", ""),
        "foto_portada_url": data.get("foto_portada_url"),
        "fotos_extra_urls": json.dumps(data.get("fotos_extra_urls", [])),
    }
    row_id = await database.execute(query=query, values=values)
    return row_id


async def get_all_properties(active_only: bool = True, limit: int = 50, offset: int = 0):
    """Lista propiedades, las mas recientes primero."""
    where = "WHERE activa = TRUE" if active_only else ""
    query = f"""
    SELECT * FROM propiedades {where}
    ORDER BY created_at DESC
    LIMIT :limit OFFSET :offset
    """
    rows = await database.fetch_all(query=query, values={"limit": limit, "offset": offset})
    return [dict(r._mapping) for r in rows]


async def get_property_by_id(prop_id: int):
    """Obtiene una propiedad por ID."""
    query = "SELECT * FROM propiedades WHERE id = :id"
    row = await database.fetch_one(query=query, values={"id": prop_id})
    return dict(row._mapping) if row else None


async def get_property_by_session(session_id: str):
    """Obtiene una propiedad por session_id."""
    query = "SELECT * FROM propiedades WHERE session_id = :session_id"
    row = await database.fetch_one(query=query, values={"session_id": session_id})
    return dict(row._mapping) if row else None


async def search_properties(ciudad: str = None, operacion: str = None,
                            tipo: str = None, precio_min: float = None,
                            precio_max: float = None, limit: int = 20):
    """Busca propiedades con filtros. Ideal para el chatbot de WhatsApp."""
    conditions = ["activa = TRUE"]
    values = {"limit": limit}

    if ciudad:
        conditions.append("LOWER(ciudad) LIKE :ciudad")
        values["ciudad"] = f"%{ciudad.lower()}%"
    if operacion:
        conditions.append("LOWER(operacion) LIKE :operacion")
        values["operacion"] = f"%{operacion.lower()}%"
    if tipo:
        conditions.append("LOWER(tipo_propiedad) LIKE :tipo")
        values["tipo"] = f"%{tipo.lower()}%"
    if precio_min is not None:
        conditions.append("precio >= :precio_min")
        values["precio_min"] = precio_min
    if precio_max is not None:
        conditions.append("precio <= :precio_max")
        values["precio_max"] = precio_max

    where = "WHERE " + " AND ".join(conditions)
    query = f"""
    SELECT * FROM propiedades {where}
    ORDER BY created_at DESC LIMIT :limit
    """
    rows = await database.fetch_all(query=query, values=values)
    return [dict(r._mapping) for r in rows]


async def update_property(prop_id: int, updates: dict):
    """Actualiza campos de una propiedad."""
    allowed = {
        "tipo_propiedad", "operacion", "direccion", "ciudad", "estado",
        "precio", "precio_formateado", "recamaras", "banos",
        "metros_construidos", "metros_terreno", "estacionamientos",
        "amenidades", "descripcion_agente", "descripcion_profesional",
        "instagram_copy", "agente_nombre", "agente_telefono", "agente_email",
        "foto_portada_url", "fotos_extra_urls",
        "publicada_instagram", "publicada_web", "activa"
    }
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return False

    # Serializar JSON fields
    for jf in ("amenidades", "fotos_extra_urls"):
        if jf in fields and isinstance(fields[jf], (list, dict)):
            fields[jf] = json.dumps(fields[jf])

    fields["updated_at"] = datetime.utcnow()
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = prop_id
    query = f"UPDATE propiedades SET {set_clause} WHERE id = :id"
    await database.execute(query=query, values=fields)
    return True


async def toggle_property(prop_id: int, active: bool):
    """Activa/desactiva una propiedad."""
    query = "UPDATE propiedades SET activa = :activa, updated_at = NOW() WHERE id = :id"
    await database.execute(query=query, values={"activa": active, "id": prop_id})


async def count_properties(active_only: bool = True) -> int:
    """Cuenta total de propiedades."""
    where = "WHERE activa = TRUE" if active_only else ""
    query = f"SELECT COUNT(*) as total FROM propiedades {where}"
    row = await database.fetch_one(query=query)
    return row._mapping["total"] if row else 0


# ─── Desarrollos ───

async def save_desarrollo(data: dict) -> int:
    """Guarda un desarrollo y devuelve su ID."""
    query = """
    INSERT INTO desarrollos (
        nombre, descripcion, ubicacion, ciudad, estado,
        precio_desde, precio_hasta, tipo_propiedad, amenidades,
        caracteristicas, agente_nombre, agente_telefono, agente_email,
        foto_portada_url, fotos_urls, pdf_url
    ) VALUES (
        :nombre, :descripcion, :ubicacion, :ciudad, :estado,
        :precio_desde, :precio_hasta, :tipo_propiedad, :amenidades::jsonb,
        :caracteristicas, :agente_nombre, :agente_telefono, :agente_email,
        :foto_portada_url, :fotos_urls::jsonb, :pdf_url
    ) RETURNING id
    """
    values = {
        "nombre": data.get("nombre", ""),
        "descripcion": data.get("descripcion"),
        "ubicacion": data.get("ubicacion", ""),
        "ciudad": data.get("ciudad", ""),
        "estado": data.get("estado", ""),
        "precio_desde": data.get("precio_desde"),
        "precio_hasta": data.get("precio_hasta"),
        "tipo_propiedad": data.get("tipo_propiedad", ""),
        "amenidades": json.dumps(data.get("amenidades", [])),
        "caracteristicas": data.get("caracteristicas"),
        "agente_nombre": data.get("agente_nombre", ""),
        "agente_telefono": data.get("agente_telefono", ""),
        "agente_email": data.get("agente_email", ""),
        "foto_portada_url": data.get("foto_portada_url"),
        "fotos_urls": json.dumps(data.get("fotos_urls", [])),
        "pdf_url": data.get("pdf_url"),
    }
    return await database.execute(query=query, values=values)


async def get_all_desarrollos(active_only: bool = True):
    """Lista todos los desarrollos."""
    where = "WHERE activo = TRUE" if active_only else ""
    query = f"SELECT * FROM desarrollos {where} ORDER BY created_at DESC"
    rows = await database.fetch_all(query=query)
    return [dict(r._mapping) for r in rows]


async def get_desarrollo_by_id(dev_id: int):
    """Obtiene un desarrollo por ID."""
    query = "SELECT * FROM desarrollos WHERE id = :id"
    row = await database.fetch_one(query=query, values={"id": dev_id})
    return dict(row._mapping) if row else None


async def search_desarrollos(texto: str = None, ciudad: str = None, limit: int = 10):
    """Busca desarrollos por nombre o ciudad."""
    conditions = ["activo = TRUE"]
    values = {"limit": limit}
    if texto:
        conditions.append("(LOWER(nombre) LIKE :texto OR LOWER(descripcion) LIKE :texto)")
        values["texto"] = f"%{texto.lower()}%"
    if ciudad:
        conditions.append("LOWER(ciudad) LIKE :ciudad")
        values["ciudad"] = f"%{ciudad.lower()}%"
    where = "WHERE " + " AND ".join(conditions)
    query = f"SELECT * FROM desarrollos {where} ORDER BY created_at DESC LIMIT :limit"
    rows = await database.fetch_all(query=query, values=values)
    return [dict(r._mapping) for r in rows]


async def update_desarrollo(dev_id: int, updates: dict):
    """Actualiza un desarrollo."""
    allowed = {
        "nombre", "descripcion", "ubicacion", "ciudad", "estado",
        "precio_desde", "precio_hasta", "tipo_propiedad", "amenidades",
        "caracteristicas", "agente_nombre", "agente_telefono", "agente_email",
        "foto_portada_url", "fotos_urls", "pdf_url", "activo"
    }
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return False
    for jf in ("amenidades", "fotos_urls"):
        if jf in fields and isinstance(fields[jf], (list, dict)):
            fields[jf] = json.dumps(fields[jf])
    fields["updated_at"] = datetime.utcnow()
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = dev_id
    query = f"UPDATE desarrollos SET {set_clause} WHERE id = :id"
    await database.execute(query=query, values=fields)
    return True
