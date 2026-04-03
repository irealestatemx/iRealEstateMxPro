"""
Script para cargar desarrollos iniciales a la base de datos.
Ejecutar una sola vez: python seed_desarrollos.py
O se ejecuta automaticamente al iniciar si la tabla esta vacia.
"""

DESARROLLOS_INICIALES = [
    {
        "nombre": "Cárcamos Residencial",
        "descripcion": (
            "Cárcamos Residencial es una exclusiva privada ubicada en una zona de alto "
            "potencial de plusvalía a tan solo 3 minutos del Centro Comercial ALAÏA y "
            "15 minutos del centro histórico de Guanajuato capital. "
            "Un concepto único donde la exclusividad, la seguridad y un estilo de vida "
            "fresco harán de tu hogar un refugio de buen gusto. "
            "Privada con acceso controlado, casas con diseño arquitectónico contemporáneo "
            "y acabados de primera calidad."
        ),
        "ubicacion": "A 3 min del Centro Comercial ALAÏA, Guanajuato Capital",
        "ciudad": "Guanajuato",
        "estado": "Guanajuato",
        "precio_desde": 2990000,
        "precio_hasta": None,
        "tipo_propiedad": "Casa",
        "amenidades": [
            "Acceso controlado",
            "Seguridad 24/7",
            "Zona de alta plusvalía",
            "Cerca de Centro Comercial ALAÏA",
            "15 min del centro histórico"
        ],
        "caracteristicas": (
            "Privada exclusiva en Guanajuato Capital. "
            "Casas con diseño contemporáneo y acabados premium. "
            "Ubicación estratégica cerca de ALAÏA y centro histórico."
            "Casas desde 178 m2 de construcción"
        ),
        "agente_nombre": "Esteban Castellanos",
        "agente_telefono": "4737365219",
        "agente_email": "irealestatemx@gmail.com",
        "pdf_url": "/static/docs/carcamos-residencial.pdf",
    },
    {
        "nombre": "Privada del Fresno",
        "descripcion": (
            "Privada del Fresno es un desarrollo exclusivo de 24 casas ubicado muy cerca "
            "de Las Teresas. Algunas casas cuentan con sótano. "
            "Ofrece un estilo de vida completo con amenidades de primer nivel: "
            "gimnasio, asadores, juegos infantiles y área de lectura. "
            "Vigilancia 24/7 para la tranquilidad de tu familia."
        ),
        "ubicacion": "Muy cerca de Las Teresas, Guanajuato",
        "ciudad": "Guanajuato",
        "estado": "Guanajuato",
        "precio_desde": 3250000,
        "precio_hasta": None,
        "tipo_propiedad": "Casa",
        "amenidades": [
            "Gimnasio",
            "Asadores",
            "Juegos infantiles",
            "Área de lectura",
            "Vigilancia 24/7",
            "Sótano (algunas casas)"
        ],
        "caracteristicas": (
            "24 casas exclusivas. "
            "Construcción desde 207 m2 hasta 450 m2. "
            "Terrenos desde 120 m2 hasta 160 m2. "
            "Algunas casas con sótano. "
            "Privada con vigilancia 24/7."
            "Desde 209 m2 de construcción"
        ),
        "agente_nombre": "Esteban Castellanos",
        "agente_telefono": "4737365219",
        "agente_email": "irealestatemx@gmail.com",
        "pdf_url": "/static/docs/privada-del-fresno.pdf",
    },
]
