"""
Base de datos PostgreSQL para iRealEstateMxPro.
Guarda cada propiedad con todos sus datos, fotos, descripciones generadas, y estado.
"""

import os
import json
from datetime import datetime
from databases import Database
from passlib.hash import bcrypt

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
    user_id             INTEGER,
    publicada_instagram BOOLEAN DEFAULT FALSE,
    publicada_web       BOOLEAN DEFAULT TRUE,
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

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS usuarios (
    id                  SERIAL PRIMARY KEY,
    email               VARCHAR(300) UNIQUE NOT NULL,
    password            VARCHAR(300) NOT NULL,
    nombre              VARCHAR(300),
    rol                 VARCHAR(50) DEFAULT 'agente',
    prefijo_whatsapp    VARCHAR(10) UNIQUE,
    activo              BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMP DEFAULT NOW()
);
"""

CREATE_PROSPECTOS = """
CREATE TABLE IF NOT EXISTS prospectos (
    id                  SERIAL PRIMARY KEY,
    referido_id         INTEGER REFERENCES usuarios(id),
    agente_id           INTEGER REFERENCES usuarios(id),
    nombre_cliente      VARCHAR(300),
    telefono_cliente    VARCHAR(50),
    mensaje_original    TEXT,
    prefijo             VARCHAR(10),
    desarrollo_interes  VARCHAR(300),
    estado              VARCHAR(50) DEFAULT 'nuevo',
    notas               TEXT,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);
"""

CREATE_DOCUMENTOS = """
CREATE TABLE IF NOT EXISTS documentos (
    id              SERIAL PRIMARY KEY,
    propiedad_id    INTEGER REFERENCES propiedades(id) ON DELETE CASCADE,
    subido_por      INTEGER REFERENCES usuarios(id),
    tipo_documento  VARCHAR(100) NOT NULL,
    categoria       VARCHAR(50) NOT NULL,
    archivo_url     VARCHAR(500) NOT NULL,
    estado          VARCHAR(50) DEFAULT 'pendiente',
    obligatorio     BOOLEAN DEFAULT TRUE,
    version         INTEGER DEFAULT 1,
    notas           TEXT,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);
"""

CREATE_NOTIFICACIONES = """
CREATE TABLE IF NOT EXISTS notificaciones (
    id              SERIAL PRIMARY KEY,
    tipo            VARCHAR(50) NOT NULL,
    user_id         INTEGER REFERENCES usuarios(id),
    propiedad_id    INTEGER REFERENCES propiedades(id) ON DELETE CASCADE,
    metadata        JSONB DEFAULT '{}',
    leida           BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW()
);
"""

CREATE_SEGUIMIENTOS = """
CREATE TABLE IF NOT EXISTS seguimiento_mensajes (
    id              SERIAL PRIMARY KEY,
    comprador_id    INTEGER REFERENCES usuarios(id),
    propiedad_id    INTEGER REFERENCES propiedades(id) ON DELETE CASCADE,
    agente_id       INTEGER REFERENCES usuarios(id),
    mensaje         TEXT NOT NULL,
    modo            VARCHAR(20) DEFAULT 'seguimiento',
    created_at      TIMESTAMP DEFAULT NOW()
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
    "CREATE INDEX IF NOT EXISTS idx_prospectos_referido ON prospectos(referido_id);",
    "CREATE INDEX IF NOT EXISTS idx_prospectos_estado ON prospectos(estado);",
    "CREATE INDEX IF NOT EXISTS idx_prospectos_created ON prospectos(created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_documentos_propiedad ON documentos(propiedad_id);",
    "CREATE INDEX IF NOT EXISTS idx_documentos_subido_por ON documentos(subido_por);",
    "CREATE INDEX IF NOT EXISTS idx_documentos_estado ON documentos(estado);",
    "CREATE INDEX IF NOT EXISTS idx_notificaciones_user ON notificaciones(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_notificaciones_leida ON notificaciones(leida);",
    "CREATE INDEX IF NOT EXISTS idx_notificaciones_created ON notificaciones(created_at DESC);",
]


MIGRATIONS = [
    "ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS user_id INTEGER;",
    "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS prefijo_whatsapp VARCHAR(10);",
    "ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS vendedor_id INTEGER REFERENCES usuarios(id);",
    "ALTER TABLE documentos ADD COLUMN IF NOT EXISTS rol_documento VARCHAR(20) DEFAULT 'vendedor';",
    "ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS comprador_id INTEGER REFERENCES usuarios(id);",
    "ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS tipo_compra VARCHAR(50);",
    "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS telefono VARCHAR(20);",
    "ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS cierre_data JSONB DEFAULT '{}';",
    # Nuevos campos propiedades
    "ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS nombre_propiedad VARCHAR(300);",
    "ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS latitud DOUBLE PRECISION;",
    "ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS longitud DOUBLE PRECISION;",
    "ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS vendida BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS fecha_venta TIMESTAMP;",
    # Hacer visibles en web todas las propiedades activas existentes
    "UPDATE propiedades SET publicada_web = TRUE WHERE activa = TRUE AND publicada_web = FALSE;",
    # Cambiar default de publicada_web a TRUE
    "ALTER TABLE propiedades ALTER COLUMN publicada_web SET DEFAULT TRUE;",
    # Prospectos chatbot
    "ALTER TABLE prospectos ADD COLUMN IF NOT EXISTS fuente VARCHAR(50) DEFAULT 'chatbot';",
    "ALTER TABLE prospectos ADD COLUMN IF NOT EXISTS email_cliente VARCHAR(300);",
    "ALTER TABLE prospectos ADD COLUMN IF NOT EXISTS cita_data JSONB DEFAULT '{}';",
    "ALTER TABLE prospectos ADD COLUMN IF NOT EXISTS historial JSONB DEFAULT '[]';",
    # Vincular propiedades a desarrollos
    "ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS desarrollo_slug VARCHAR(100);",
    "CREATE INDEX IF NOT EXISTS idx_propiedades_desarrollo ON propiedades(desarrollo_slug);",
]

CREATE_CITAS_CHATBOT = """
CREATE TABLE IF NOT EXISTS citas_chatbot (
    id              SERIAL PRIMARY KEY,
    prospecto_id    INTEGER REFERENCES prospectos(id) ON DELETE CASCADE,
    titulo          VARCHAR(500),
    desarrollo      VARCHAR(300),
    fecha           DATE,
    hora_inicio     TIME,
    hora_fin        TIME,
    estado          VARCHAR(50) DEFAULT 'pendiente',
    google_event_id VARCHAR(300),
    notas           TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);
"""

CREATE_INDEXES_CITAS = [
    "CREATE INDEX IF NOT EXISTS idx_citas_prospecto ON citas_chatbot(prospecto_id);",
    "CREATE INDEX IF NOT EXISTS idx_citas_fecha ON citas_chatbot(fecha);",
    "CREATE INDEX IF NOT EXISTS idx_citas_estado ON citas_chatbot(estado);",
    "CREATE INDEX IF NOT EXISTS idx_prospectos_fuente ON prospectos(fuente);",
    "CREATE INDEX IF NOT EXISTS idx_prospectos_telefono ON prospectos(telefono_cliente);",
]


async def init_db():
    """Conecta y crea las tablas si no existen."""
    await database.connect()
    await database.execute(CREATE_TABLES)
    await database.execute(CREATE_USERS)
    await database.execute(CREATE_DESARROLLOS)
    await database.execute(CREATE_PROSPECTOS)
    await database.execute(CREATE_DOCUMENTOS)
    await database.execute(CREATE_NOTIFICACIONES)
    await database.execute(CREATE_SEGUIMIENTOS)
    for idx in CREATE_INDEXES:
        await database.execute(idx)
    for mig in MIGRATIONS:
        try:
            await database.execute(mig)
        except Exception:
            pass
    # Tabla de citas chatbot (después de migrations para que fuente exista)
    await database.execute(CREATE_CITAS_CHATBOT)
    for idx in CREATE_INDEXES_CITAS:
        try:
            await database.execute(idx)
        except Exception:
            pass
    # Tabla de configuración del sitio (key-value JSONB)
    await database.execute("""
    CREATE TABLE IF NOT EXISTS site_config (
        clave   VARCHAR(100) PRIMARY KEY,
        valor   JSONB DEFAULT '{}',
        updated_at TIMESTAMP DEFAULT NOW()
    );
    """)


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
        foto_portada_url, fotos_extra_urls, user_id,
        nombre_propiedad, latitud, longitud, desarrollo_slug
    ) VALUES (
        :session_id, :tipo_propiedad, :operacion, :direccion, :ciudad, :estado,
        :precio, :precio_formateado, :recamaras, :banos, :metros_construidos,
        :metros_terreno, :estacionamientos, :amenidades, :descripcion_agente,
        :descripcion_profesional, :instagram_copy,
        :agente_nombre, :agente_telefono, :agente_email,
        :foto_portada_url, :fotos_extra_urls, :user_id,
        :nombre_propiedad, :latitud, :longitud, :desarrollo_slug
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
        "user_id": data.get("user_id"),
        "nombre_propiedad": data.get("nombre_propiedad"),
        "latitud": float(data["latitud"]) if data.get("latitud") else None,
        "longitud": float(data["longitud"]) if data.get("longitud") else None,
        "desarrollo_slug": data.get("desarrollo_slug") or None,
    }
    row_id = await database.execute(query=query, values=values)
    return row_id


def _normalize_prop(d: dict) -> dict:
    """Asegura que los campos JSONB sean listas/dicts Python (no strings JSON)."""
    for key in ("amenidades", "fotos_extra_urls"):
        val = d.get(key)
        if val is None:
            d[key] = []
        elif isinstance(val, str):
            try:
                d[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                d[key] = []
    # JSONB dict fields
    for key in ("cierre_data",):
        val = d.get(key)
        if val is None:
            d[key] = {}
        elif isinstance(val, str):
            try:
                d[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                d[key] = {}
    return d


async def get_properties_by_user(user_id: int, limit: int = 50, offset: int = 0):
    """Lista propiedades de un usuario especifico."""
    query = """
    SELECT * FROM propiedades WHERE user_id = :user_id
    ORDER BY created_at DESC LIMIT :limit OFFSET :offset
    """
    rows = await database.fetch_all(query=query, values={"user_id": user_id, "limit": limit, "offset": offset})
    return [_normalize_prop(dict(r._mapping)) for r in rows]


async def get_propiedades_seguimiento(agente_id: int = None):
    """Lista propiedades con vendedor asignado + conteos de documentos para dashboard asesor."""
    where = "WHERE p.vendedor_id IS NOT NULL AND p.activa = TRUE"
    values = {}
    if agente_id:
        where += " AND p.user_id = :agente_id"
        values["agente_id"] = agente_id
    query = f"""
    SELECT p.id, p.tipo_propiedad, p.operacion, p.direccion, p.ciudad, p.estado,
           p.precio_formateado, p.foto_portada_url, p.vendedor_id, p.comprador_id, p.user_id,
           p.tipo_compra, p.cierre_data,
           u_v.nombre as vendedor_nombre, u_v.email as vendedor_email,
           u_c.nombre as comprador_nombre, u_c.email as comprador_email,
           COUNT(d.id) as docs_subidos,
           COUNT(CASE WHEN d.estado = 'aprobado' THEN 1 END) as docs_aprobados,
           COUNT(CASE WHEN d.estado = 'rechazado' THEN 1 END) as docs_rechazados,
           COUNT(CASE WHEN d.estado = 'pendiente' THEN 1 END) as docs_pendientes,
           MAX(d.created_at) as ultimo_movimiento
    FROM propiedades p
    LEFT JOIN usuarios u_v ON p.vendedor_id = u_v.id
    LEFT JOIN usuarios u_c ON p.comprador_id = u_c.id
    LEFT JOIN documentos d ON d.propiedad_id = p.id AND d.categoria = 'vendedor'
    {where}
    GROUP BY p.id, u_v.nombre, u_v.email, u_c.nombre, u_c.email
    ORDER BY p.created_at DESC
    """
    rows = await database.fetch_all(query=query, values=values)
    return [dict(r._mapping) for r in rows]


async def get_properties_by_vendedor(vendedor_id: int):
    """Lista propiedades asignadas a un vendedor."""
    query = """
    SELECT * FROM propiedades WHERE vendedor_id = :vendedor_id
    ORDER BY created_at DESC
    """
    rows = await database.fetch_all(query=query, values={"vendedor_id": vendedor_id})
    return [_normalize_prop(dict(r._mapping)) for r in rows]


async def get_properties_by_comprador(comprador_id: int):
    """Lista propiedades asignadas a un comprador."""
    query = """
    SELECT * FROM propiedades WHERE comprador_id = :comprador_id
    ORDER BY created_at DESC
    """
    rows = await database.fetch_all(query=query, values={"comprador_id": comprador_id})
    return [_normalize_prop(dict(r._mapping)) for r in rows]


async def guardar_seguimiento(comprador_id: int, propiedad_id: int, agente_id: int, mensaje: str, modo: str = "seguimiento"):
    """Guarda registro de mensaje de seguimiento enviado."""
    query = """
    INSERT INTO seguimiento_mensajes (comprador_id, propiedad_id, agente_id, mensaje, modo)
    VALUES (:comprador_id, :propiedad_id, :agente_id, :mensaje, :modo)
    RETURNING id
    """
    return await database.execute(query=query, values={
        "comprador_id": comprador_id,
        "propiedad_id": propiedad_id,
        "agente_id": agente_id,
        "mensaje": mensaje,
        "modo": modo,
    })


async def get_ultimo_seguimiento_por_propiedad(propiedad_ids: list):
    """Retorna el último seguimiento para cada propiedad. Recibe lista de IDs."""
    if not propiedad_ids:
        return {}
    placeholders = ", ".join(f":id{i}" for i in range(len(propiedad_ids)))
    query = f"""
    SELECT DISTINCT ON (propiedad_id)
        propiedad_id, mensaje, modo, created_at
    FROM seguimiento_mensajes
    WHERE propiedad_id IN ({placeholders})
    ORDER BY propiedad_id, created_at DESC
    """
    values = {f"id{i}": pid for i, pid in enumerate(propiedad_ids)}
    rows = await database.fetch_all(query=query, values=values)
    result = {}
    for r in rows:
        d = dict(r._mapping)
        result[d["propiedad_id"]] = d
    return result


async def set_tipo_compra(propiedad_id: int, tipo_compra: str):
    """Guarda el tipo de compra seleccionado por el comprador."""
    query = "UPDATE propiedades SET tipo_compra = :tipo_compra, updated_at = NOW() WHERE id = :id"
    await database.execute(query=query, values={"id": propiedad_id, "tipo_compra": tipo_compra})


async def get_all_properties(active_only: bool = True, limit: int = 50, offset: int = 0,
                             publicada_web: bool = None, include_vendidas: bool = False):
    """Lista propiedades, las mas recientes primero."""
    conditions = []
    if active_only:
        conditions.append("activa = TRUE")
    if publicada_web is not None:
        conditions.append(f"publicada_web = {'TRUE' if publicada_web else 'FALSE'}")
    if not include_vendidas:
        conditions.append("(vendida IS NULL OR vendida = FALSE)")
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    query = f"""
    SELECT * FROM propiedades {where}
    ORDER BY created_at DESC
    LIMIT :limit OFFSET :offset
    """
    rows = await database.fetch_all(query=query, values={"limit": limit, "offset": offset})
    return [_normalize_prop(dict(r._mapping)) for r in rows]


async def get_properties_by_desarrollo(slug: str, limit: int = 50):
    """Lista propiedades vinculadas a un desarrollo por slug."""
    query = """
    SELECT * FROM propiedades
    WHERE desarrollo_slug = :slug AND activa = TRUE AND publicada_web = TRUE
      AND (vendida IS NULL OR vendida = FALSE)
    ORDER BY created_at DESC LIMIT :limit
    """
    rows = await database.fetch_all(query=query, values={"slug": slug, "limit": limit})
    return [_normalize_prop(dict(r._mapping)) for r in rows]


async def get_property_by_id(prop_id: int):
    """Obtiene una propiedad por ID."""
    query = "SELECT * FROM propiedades WHERE id = :id"
    row = await database.fetch_one(query=query, values={"id": prop_id})
    return _normalize_prop(dict(row._mapping)) if row else None


async def get_property_by_session(session_id: str):
    """Obtiene una propiedad por session_id."""
    query = "SELECT * FROM propiedades WHERE session_id = :session_id"
    row = await database.fetch_one(query=query, values={"session_id": session_id})
    return _normalize_prop(dict(row._mapping)) if row else None


async def search_properties(ciudad: str = None, operacion: str = None,
                            tipo: str = None, precio_min: float = None,
                            precio_max: float = None, limit: int = 20,
                            publicada_web: bool = None):
    """Busca propiedades con filtros. Ideal para el chatbot de WhatsApp."""
    conditions = ["activa = TRUE", "(vendida IS NULL OR vendida = FALSE)"]
    if publicada_web is not None:
        conditions.append(f"publicada_web = {'TRUE' if publicada_web else 'FALSE'}")
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
        "publicada_instagram", "publicada_web", "activa",
        "vendedor_id", "comprador_id", "cierre_data", "tipo_compra",
        "nombre_propiedad", "latitud", "longitud", "vendida", "fecha_venta",
        "desarrollo_slug",
    }
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return False

    # Serializar JSON fields
    for jf in ("amenidades", "fotos_extra_urls", "cierre_data"):
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


async def count_properties(active_only: bool = True, publicada_web: bool = None, include_vendidas: bool = False) -> int:
    """Cuenta total de propiedades."""
    conditions = []
    if active_only:
        conditions.append("activa = TRUE")
    if publicada_web is not None:
        conditions.append(f"publicada_web = {'TRUE' if publicada_web else 'FALSE'}")
    if not include_vendidas:
        conditions.append("(vendida IS NULL OR vendida = FALSE)")
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
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
        :precio_desde, :precio_hasta, :tipo_propiedad, CAST(:amenidades AS jsonb),
        :caracteristicas, :agente_nombre, :agente_telefono, :agente_email,
        :foto_portada_url, CAST(:fotos_urls AS jsonb), :pdf_url
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


# ─── Usuarios ───

async def create_user(email: str, password: str, nombre: str, rol: str = "agente") -> int:
    """Crea un usuario con password hasheada."""
    hashed = bcrypt.hash(password)
    query = """
    INSERT INTO usuarios (email, password, nombre, rol)
    VALUES (:email, :password, :nombre, :rol)
    RETURNING id
    """
    return await database.execute(query=query, values={
        "email": email.lower().strip(),
        "password": hashed,
        "nombre": nombre,
        "rol": rol,
    })


async def get_user_by_email(email: str):
    """Obtiene un usuario por email (sin verificar contraseña)."""
    query = "SELECT id, email, nombre, rol, prefijo_whatsapp, telefono, activo, created_at FROM usuarios WHERE email = :email"
    row = await database.fetch_one(query=query, values={"email": email.lower().strip()})
    if not row:
        return None
    return dict(row._mapping)


async def authenticate_user(email: str, password: str):
    """Verifica credenciales. Devuelve el usuario o None."""
    query = "SELECT * FROM usuarios WHERE email = :email AND activo = TRUE"
    row = await database.fetch_one(query=query, values={"email": email.lower().strip()})
    if not row:
        return None
    user = dict(row._mapping)
    if bcrypt.verify(password, user["password"]):
        return user
    return None


async def get_user_by_id(user_id: int):
    """Obtiene usuario por ID."""
    query = "SELECT id, email, nombre, rol, prefijo_whatsapp, telefono, activo, created_at FROM usuarios WHERE id = :id"
    row = await database.fetch_one(query=query, values={"id": user_id})
    return dict(row._mapping) if row else None


async def get_all_users():
    """Lista todos los usuarios."""
    query = "SELECT id, email, nombre, rol, prefijo_whatsapp, telefono, activo, created_at FROM usuarios ORDER BY created_at DESC"
    rows = await database.fetch_all(query=query)
    return [dict(r._mapping) for r in rows]


async def get_users_by_rol(rol: str):
    """Lista usuarios activos de un rol específico."""
    query = "SELECT id, nombre, email, telefono FROM usuarios WHERE rol = :rol AND activo = TRUE ORDER BY nombre"
    rows = await database.fetch_all(query=query, values={"rol": rol})
    return [dict(r._mapping) for r in rows]


async def update_user(user_id: int, updates: dict):
    """Actualiza un usuario."""
    allowed = {"nombre", "email", "rol", "activo", "prefijo_whatsapp", "telefono"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if "password" in updates and updates["password"]:
        fields["password"] = bcrypt.hash(updates["password"])
    if not fields:
        return False
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = user_id
    query = f"UPDATE usuarios SET {set_clause} WHERE id = :id"
    await database.execute(query=query, values=fields)
    return True


async def delete_user(user_id: int):
    """Desactiva un usuario."""
    query = "UPDATE usuarios SET activo = FALSE WHERE id = :id"
    await database.execute(query=query, values={"id": user_id})


async def delete_user_permanent(user_id: int):
    """Elimina un usuario permanentemente. Limpia todas las FK que lo referencian."""
    v = {"id": user_id}
    # Desasociar prospectos
    await database.execute("UPDATE prospectos SET referido_id = NULL WHERE referido_id = :id", values=v)
    await database.execute("UPDATE prospectos SET agente_id = NULL WHERE agente_id = :id", values=v)
    # Desasociar propiedades
    await database.execute("UPDATE propiedades SET user_id = NULL WHERE user_id = :id", values=v)
    await database.execute("UPDATE propiedades SET vendedor_id = NULL WHERE vendedor_id = :id", values=v)
    await database.execute("UPDATE propiedades SET comprador_id = NULL WHERE comprador_id = :id", values=v)
    # Desasociar documentos
    await database.execute("UPDATE documentos SET subido_por = NULL WHERE subido_por = :id", values=v)
    # Desasociar seguimientos
    await database.execute("UPDATE seguimiento_mensajes SET comprador_id = NULL WHERE comprador_id = :id", values=v)
    await database.execute("UPDATE seguimiento_mensajes SET agente_id = NULL WHERE agente_id = :id", values=v)
    # Eliminar notificaciones del usuario
    await database.execute("DELETE FROM notificaciones WHERE user_id = :id", values=v)
    # Eliminar usuario
    await database.execute("DELETE FROM usuarios WHERE id = :id", values=v)


async def count_users() -> int:
    """Cuenta usuarios activos."""
    query = "SELECT COUNT(*) as total FROM usuarios WHERE activo = TRUE"
    row = await database.fetch_one(query=query)
    return row._mapping["total"] if row else 0


async def seed_admin_user():
    """Crea el usuario admin si no existe ningun usuario."""
    total = await count_users()
    if total == 0:
        admin_email = os.getenv("ADMIN_EMAIL", "irealestatemx@gmail.com")
        admin_pass = os.getenv("ADMIN_PASSWORD", "admin123")
        admin_name = os.getenv("ADMIN_NAME", "Esteban Castellanos")
        await create_user(admin_email, admin_pass, admin_name, "admin")
        print(f"[SEED] Usuario admin creado: {admin_email}")


# ─── Referidos (buscar por prefijo) ───

async def get_user_by_prefijo(prefijo: str):
    """Obtiene un referido por su prefijo de WhatsApp."""
    query = "SELECT id, email, nombre, rol, prefijo_whatsapp, activo FROM usuarios WHERE UPPER(prefijo_whatsapp) = :prefijo AND activo = TRUE"
    row = await database.fetch_one(query=query, values={"prefijo": prefijo.upper().strip()})
    return dict(row._mapping) if row else None


async def get_all_referidos():
    """Lista todos los usuarios con rol referido."""
    query = "SELECT id, email, nombre, rol, prefijo_whatsapp, activo, created_at FROM usuarios WHERE rol = 'referido' ORDER BY nombre"
    rows = await database.fetch_all(query=query)
    return [dict(r._mapping) for r in rows]


# ─── Prospectos ───

async def create_prospecto(data: dict) -> int:
    """Crea un prospecto y devuelve su ID."""
    query = """
    INSERT INTO prospectos (
        referido_id, agente_id, nombre_cliente, telefono_cliente,
        mensaje_original, prefijo, desarrollo_interes, estado, notas, fuente
    ) VALUES (
        :referido_id, :agente_id, :nombre_cliente, :telefono_cliente,
        :mensaje_original, :prefijo, :desarrollo_interes, :estado, :notas, :fuente
    ) RETURNING id
    """
    values = {
        "referido_id": data.get("referido_id"),
        "agente_id": data.get("agente_id"),
        "nombre_cliente": data.get("nombre_cliente", ""),
        "telefono_cliente": data.get("telefono_cliente", ""),
        "mensaje_original": data.get("mensaje_original", ""),
        "prefijo": data.get("prefijo", ""),
        "desarrollo_interes": data.get("desarrollo_interes", ""),
        "estado": data.get("estado", "nuevo"),
        "notas": data.get("notas", ""),
        "fuente": data.get("fuente", "chatbot"),
    }
    return await database.execute(query=query, values=values)


async def get_all_prospectos(referido_id: int = None, limit: int = 100):
    """Lista prospectos. Si referido_id se pasa, filtra por ese referido."""
    if referido_id:
        query = """
        SELECT p.*, u.nombre as referido_nombre
        FROM prospectos p
        LEFT JOIN usuarios u ON p.referido_id = u.id
        WHERE p.referido_id = :referido_id
        ORDER BY p.created_at DESC LIMIT :limit
        """
        rows = await database.fetch_all(query=query, values={"referido_id": referido_id, "limit": limit})
    else:
        query = """
        SELECT p.*, u.nombre as referido_nombre
        FROM prospectos p
        LEFT JOIN usuarios u ON p.referido_id = u.id
        ORDER BY p.created_at DESC LIMIT :limit
        """
        rows = await database.fetch_all(query=query, values={"limit": limit})
    return [dict(r._mapping) for r in rows]


async def get_prospecto_by_id(prospecto_id: int):
    """Obtiene un prospecto por ID."""
    query = """
    SELECT p.*, u.nombre as referido_nombre
    FROM prospectos p
    LEFT JOIN usuarios u ON p.referido_id = u.id
    WHERE p.id = :id
    """
    row = await database.fetch_one(query=query, values={"id": prospecto_id})
    return dict(row._mapping) if row else None


async def update_prospecto(prospecto_id: int, updates: dict):
    """Actualiza un prospecto (estado, notas, etc.)."""
    allowed = {"nombre_cliente", "telefono_cliente", "desarrollo_interes", "estado", "notas", "agente_id", "referido_id"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return False
    fields["updated_at"] = datetime.utcnow()
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = prospecto_id
    query = f"UPDATE prospectos SET {set_clause} WHERE id = :id"
    await database.execute(query=query, values=fields)
    return True


async def count_prospectos(referido_id: int = None) -> dict:
    """Cuenta prospectos por estado. Retorna dict con totales."""
    if referido_id:
        query = "SELECT estado, COUNT(*) as total FROM prospectos WHERE referido_id = :referido_id GROUP BY estado"
        rows = await database.fetch_all(query=query, values={"referido_id": referido_id})
    else:
        query = "SELECT estado, COUNT(*) as total FROM prospectos GROUP BY estado"
        rows = await database.fetch_all(query=query)
    counts = {}
    for r in rows:
        m = r._mapping
        counts[m["estado"]] = m["total"]
    counts["total"] = sum(counts.values())
    return counts


async def delete_prospecto(prospecto_id: int):
    """Elimina un prospecto permanentemente."""
    query = "DELETE FROM prospectos WHERE id = :id"
    await database.execute(query=query, values={"id": prospecto_id})


async def get_prospecto_by_telefono(telefono: str):
    """Busca prospecto por teléfono (últimos 10 dígitos)."""
    tel_limpio = "".join(c for c in str(telefono) if c.isdigit())
    if len(tel_limpio) > 10:
        tel_limpio = tel_limpio[-10:]
    query = """
    SELECT p.*, u.nombre as referido_nombre
    FROM prospectos p
    LEFT JOIN usuarios u ON p.referido_id = u.id
    WHERE RIGHT(p.telefono_cliente, 10) = :tel
    ORDER BY p.created_at DESC LIMIT 1
    """
    row = await database.fetch_one(query=query, values={"tel": tel_limpio})
    return dict(row._mapping) if row else None


async def agregar_historial_prospecto(prospecto_id: int, entrada: dict):
    """Agrega una entrada al historial JSONB del prospecto."""
    query = """
    UPDATE prospectos
    SET historial = COALESCE(historial, '[]'::jsonb) || CAST(:entrada AS jsonb),
        updated_at = NOW()
    WHERE id = :id
    """
    import json
    await database.execute(query=query, values={
        "id": prospecto_id,
        "entrada": json.dumps(entrada),
    })


# ─── Citas chatbot ───

async def create_cita_chatbot(data: dict) -> int:
    """Crea una cita desde el chatbot y retorna su ID."""
    query = """
    INSERT INTO citas_chatbot (
        prospecto_id, titulo, desarrollo, fecha, hora_inicio, hora_fin,
        estado, google_event_id, notas
    ) VALUES (
        :prospecto_id, :titulo, :desarrollo, :fecha, :hora_inicio, :hora_fin,
        :estado, :google_event_id, :notas
    ) RETURNING id
    """
    from datetime import date, time
    # Convertir strings a objetos date/time para asyncpg
    fecha_raw = data.get("fecha")
    hora_ini_raw = data.get("hora_inicio")
    hora_fin_raw = data.get("hora_fin")

    fecha_val = None
    if fecha_raw:
        if isinstance(fecha_raw, str):
            fecha_val = date.fromisoformat(fecha_raw)
        else:
            fecha_val = fecha_raw

    def parse_time(val):
        if not val:
            return None
        if isinstance(val, str):
            return time.fromisoformat(val)
        return val

    values = {
        "prospecto_id": data.get("prospecto_id"),
        "titulo": data.get("titulo", ""),
        "desarrollo": data.get("desarrollo", ""),
        "fecha": fecha_val,
        "hora_inicio": parse_time(hora_ini_raw),
        "hora_fin": parse_time(hora_fin_raw),
        "estado": data.get("estado", "pendiente"),
        "google_event_id": data.get("google_event_id", ""),
        "notas": data.get("notas", ""),
    }
    return await database.execute(query=query, values=values)


async def get_citas_chatbot(prospecto_id: int = None, fecha: str = None, limit: int = 50):
    """Lista citas. Filtra por prospecto o fecha."""
    conditions = []
    values = {"limit": limit}
    if prospecto_id:
        conditions.append("c.prospecto_id = :prospecto_id")
        values["prospecto_id"] = prospecto_id
    if fecha:
        conditions.append("c.fecha = :fecha")
        values["fecha"] = fecha
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    query = f"""
    SELECT c.*, p.nombre_cliente, p.telefono_cliente, p.desarrollo_interes
    FROM citas_chatbot c
    LEFT JOIN prospectos p ON c.prospecto_id = p.id
    {where}
    ORDER BY c.fecha DESC, c.hora_inicio DESC LIMIT :limit
    """
    rows = await database.fetch_all(query=query, values=values)
    return [dict(r._mapping) for r in rows]


async def check_disponibilidad_citas(fecha: str, hora: str = None):
    """Revisa las citas de un día. Si se pasa hora, verifica si esa hora está ocupada."""
    from datetime import date as date_cls, time as time_cls, timedelta
    fecha_val = date_cls.fromisoformat(fecha) if isinstance(fecha, str) else fecha

    # Traer todas las citas del día que no estén canceladas
    query = """
    SELECT c.id, c.hora_inicio, c.hora_fin, c.desarrollo, c.estado,
           p.nombre_cliente
    FROM citas_chatbot c
    LEFT JOIN prospectos p ON c.prospecto_id = p.id
    WHERE c.fecha = :fecha AND c.estado != 'cancelada'
    ORDER BY c.hora_inicio ASC
    """
    rows = await database.fetch_all(query=query, values={"fecha": fecha_val})
    citas_dia = []
    for r in rows:
        d = dict(r._mapping)
        d["hora_inicio"] = str(d["hora_inicio"])[:5] if d["hora_inicio"] else ""
        d["hora_fin"] = str(d["hora_fin"])[:5] if d["hora_fin"] else ""
        citas_dia.append(d)

    ocupada = False
    if hora:
        # Verificar si la hora solicitada choca con alguna cita existente
        hora_solicitada = time_cls.fromisoformat(hora if len(hora) == 5 else hora + ":00")
        hora_fin_solicitada = (
            (lambda dt: (dt + timedelta(hours=1)).time())(
                __import__("datetime").datetime.combine(fecha_val, hora_solicitada)
            )
        )
        for c in citas_dia:
            if c["hora_inicio"] and c["hora_fin"]:
                ci = time_cls.fromisoformat(c["hora_inicio"])
                cf = time_cls.fromisoformat(c["hora_fin"])
                # Hay empalme si: inicio_solicitado < fin_existente AND fin_solicitado > inicio_existente
                if hora_solicitada < cf and hora_fin_solicitada > ci:
                    ocupada = True
                    break

    # Generar horarios disponibles del día (9 AM a 7 PM, bloques de 1 hora)
    disponibles = []
    for h in range(9, 19):  # 9:00 a 18:00 (última cita a las 18:00, termina 19:00)
        slot_inicio = time_cls(h, 0)
        slot_fin = time_cls(h + 1, 0) if h < 23 else time_cls(23, 59)
        libre = True
        for c in citas_dia:
            if c["hora_inicio"] and c["hora_fin"]:
                ci = time_cls.fromisoformat(c["hora_inicio"])
                cf = time_cls.fromisoformat(c["hora_fin"])
                if slot_inicio < cf and slot_fin > ci:
                    libre = False
                    break
        if libre:
            disponibles.append(f"{h:02d}:00")

    return {
        "fecha": fecha,
        "citas_del_dia": citas_dia,
        "hora_solicitada_ocupada": ocupada,
        "horarios_disponibles": disponibles,
    }


async def update_cita_chatbot(cita_id: int, updates: dict):
    """Actualiza una cita (estado, google_event_id, notas)."""
    allowed = {"estado", "google_event_id", "notas"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return False
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = cita_id
    query = f"UPDATE citas_chatbot SET {set_clause} WHERE id = :id"
    await database.execute(query=query, values=fields)
    return True


# ─── Configuración del sitio ───

async def get_site_config(clave: str, default=None):
    """Obtiene un valor de configuración del sitio."""
    query = "SELECT valor FROM site_config WHERE clave = :clave"
    row = await database.fetch_one(query=query, values={"clave": clave})
    if row:
        val = row._mapping["valor"]
        if isinstance(val, str):
            import json as _j
            try:
                return _j.loads(val)
            except Exception:
                return val
        return val
    return default


async def set_site_config(clave: str, valor):
    """Guarda un valor de configuración del sitio (upsert)."""
    import json as _j
    valor_json = _j.dumps(valor, ensure_ascii=False)
    query = """
    INSERT INTO site_config (clave, valor, updated_at) VALUES (:clave, CAST(:valor AS jsonb), NOW())
    ON CONFLICT (clave) DO UPDATE SET valor = CAST(:valor AS jsonb), updated_at = NOW()
    """
    await database.execute(query=query, values={"clave": clave, "valor": valor_json})


async def get_all_site_config() -> dict:
    """Obtiene toda la configuración del sitio como dict."""
    query = "SELECT clave, valor FROM site_config ORDER BY clave"
    rows = await database.fetch_all(query=query)
    config = {}
    for r in rows:
        m = r._mapping
        val = m["valor"]
        if isinstance(val, str):
            import json as _j
            try:
                val = _j.loads(val)
            except Exception:
                pass
        config[m["clave"]] = val
    return config


# ─── Documentos ───

async def save_documento(data: dict) -> int:
    """Guarda un documento y devuelve su ID."""
    query = """
    INSERT INTO documentos (propiedad_id, subido_por, tipo_documento, categoria, archivo_url, estado, obligatorio, notas)
    VALUES (:propiedad_id, :subido_por, :tipo_documento, :categoria, :archivo_url, :estado, :obligatorio, :notas)
    RETURNING id
    """
    values = {
        "propiedad_id": data["propiedad_id"],
        "subido_por": data["subido_por"],
        "tipo_documento": data["tipo_documento"],
        "categoria": data["categoria"],
        "archivo_url": data["archivo_url"],
        "estado": data.get("estado", "pendiente"),
        "obligatorio": data.get("obligatorio", True),
        "notas": data.get("notas", ""),
    }
    return await database.execute(query=query, values=values)


async def get_documentos_by_propiedad(propiedad_id: int):
    """Lista todos los documentos de una propiedad."""
    query = """
    SELECT d.*, u.nombre as subido_por_nombre
    FROM documentos d
    LEFT JOIN usuarios u ON d.subido_por = u.id
    WHERE d.propiedad_id = :propiedad_id
    ORDER BY d.created_at DESC
    """
    rows = await database.fetch_all(query=query, values={"propiedad_id": propiedad_id})
    return [dict(r._mapping) for r in rows]


async def update_documento_estado(doc_id: int, estado: str, notas: str = ""):
    """Actualiza el estado de un documento (pendiente, aprobado, rechazado)."""
    query = """
    UPDATE documentos SET estado = :estado, notas = :notas, updated_at = NOW()
    WHERE id = :id RETURNING propiedad_id, tipo_documento, subido_por
    """
    row = await database.fetch_one(query=query, values={"id": doc_id, "estado": estado, "notas": notas})
    return dict(row._mapping) if row else None


# ─── Notificaciones ───

async def crear_notificacion(tipo: str, user_id: int, propiedad_id: int, metadata: dict = None):
    """Crea una notificación. Función reutilizable para cualquier trigger."""
    query = """
    INSERT INTO notificaciones (tipo, user_id, propiedad_id, metadata)
    VALUES (:tipo, :user_id, :propiedad_id, :metadata)
    RETURNING id
    """
    import json as _j
    values = {
        "tipo": tipo,
        "user_id": user_id,
        "propiedad_id": propiedad_id,
        "metadata": _j.dumps(metadata or {}),
    }
    return await database.execute(query=query, values=values)


async def get_notificaciones(user_id: int, solo_no_leidas: bool = False, limit: int = 50):
    """Lista notificaciones de un usuario."""
    where = "WHERE n.user_id = :user_id"
    if solo_no_leidas:
        where += " AND n.leida = FALSE"
    query = f"""
    SELECT n.*, p.tipo_propiedad, p.direccion, p.ciudad
    FROM notificaciones n
    LEFT JOIN propiedades p ON n.propiedad_id = p.id
    {where}
    ORDER BY n.created_at DESC LIMIT :limit
    """
    rows = await database.fetch_all(query=query, values={"user_id": user_id, "limit": limit})
    return [dict(r._mapping) for r in rows]


async def marcar_notificacion_leida(notif_id: int):
    """Marca una notificación como leída."""
    await database.execute("UPDATE notificaciones SET leida = TRUE WHERE id = :id", values={"id": notif_id})


async def contar_notificaciones_no_leidas(user_id: int) -> int:
    """Cuenta notificaciones no leídas de un usuario."""
    row = await database.fetch_one(
        "SELECT COUNT(*) as total FROM notificaciones WHERE user_id = :user_id AND leida = FALSE",
        values={"user_id": user_id}
    )
    return row._mapping["total"] if row else 0


async def get_propiedades_con_docs_pendientes():
    """Detecta propiedades con documentos obligatorios faltantes o pendientes.
    Función lista para ejecutarse manualmente o con cron después."""
    query = """
    SELECT p.id as propiedad_id, p.tipo_propiedad, p.direccion, p.ciudad,
           p.user_id as agente_id, p.vendedor_id,
           u_agente.nombre as agente_nombre,
           u_vendedor.nombre as vendedor_nombre,
           COUNT(d.id) as docs_subidos,
           COUNT(CASE WHEN d.estado = 'aprobado' THEN 1 END) as docs_aprobados,
           COUNT(CASE WHEN d.estado = 'rechazado' THEN 1 END) as docs_rechazados,
           COUNT(CASE WHEN d.estado = 'pendiente' THEN 1 END) as docs_pendientes
    FROM propiedades p
    LEFT JOIN documentos d ON d.propiedad_id = p.id AND d.categoria = 'vendedor'
    LEFT JOIN usuarios u_agente ON p.user_id = u_agente.id
    LEFT JOIN usuarios u_vendedor ON p.vendedor_id = u_vendedor.id
    WHERE p.vendedor_id IS NOT NULL AND p.activa = TRUE
    GROUP BY p.id, u_agente.nombre, u_vendedor.nombre
    ORDER BY p.created_at DESC
    """
    rows = await database.fetch_all(query=query)
    return [dict(r._mapping) for r in rows]
