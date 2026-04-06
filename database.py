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
        foto_portada_url, fotos_extra_urls, user_id
    ) VALUES (
        :session_id, :tipo_propiedad, :operacion, :direccion, :ciudad, :estado,
        :precio, :precio_formateado, :recamaras, :banos, :metros_construidos,
        :metros_terreno, :estacionamientos, :amenidades, :descripcion_agente,
        :descripcion_profesional, :instagram_copy,
        :agente_nombre, :agente_telefono, :agente_email,
        :foto_portada_url, :fotos_extra_urls, :user_id
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


async def get_all_properties(active_only: bool = True, limit: int = 50, offset: int = 0):
    """Lista propiedades, las mas recientes primero."""
    where = "WHERE activa = TRUE" if active_only else ""
    query = f"""
    SELECT * FROM propiedades {where}
    ORDER BY created_at DESC
    LIMIT :limit OFFSET :offset
    """
    rows = await database.fetch_all(query=query, values={"limit": limit, "offset": offset})
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
        "publicada_instagram", "publicada_web", "activa",
        "vendedor_id", "comprador_id", "cierre_data", "tipo_compra",
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
    """Elimina un usuario permanentemente. También limpia sus prospectos."""
    # Desasociar prospectos del referido (poner referido_id = NULL)
    query_prospectos = "UPDATE prospectos SET referido_id = NULL WHERE referido_id = :id"
    await database.execute(query=query_prospectos, values={"id": user_id})
    # Eliminar usuario
    query = "DELETE FROM usuarios WHERE id = :id"
    await database.execute(query=query, values={"id": user_id})


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
        mensaje_original, prefijo, desarrollo_interes, estado, notas
    ) VALUES (
        :referido_id, :agente_id, :nombre_cliente, :telefono_cliente,
        :mensaje_original, :prefijo, :desarrollo_interes, :estado, :notas
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
    allowed = {"nombre_cliente", "telefono_cliente", "desarrollo_interes", "estado", "notas", "agente_id"}
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
