const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, PageOrientation, LevelFormat,
  HeadingLevel, BorderStyle, WidthType, ShadingType, PageBreak, PageNumber,
  TabStopType, TabStopPosition, ExternalHyperlink
} = require('docx');

// ---------- Estilos comunes ----------
const border = { style: BorderStyle.SINGLE, size: 6, color: "C9A227" };
const borderGray = { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC" };
const bordersAll = { top: borderGray, bottom: borderGray, left: borderGray, right: borderGray };

// Shortcut para párrafos
const P = (text, opts = {}) => new Paragraph({
  children: [new TextRun({ text, ...(opts.run || {}) })],
  ...opts.para
});

const bullet = (text, level = 0) => new Paragraph({
  numbering: { reference: "bullets", level },
  children: [new TextRun(text)]
});

const number = (text) => new Paragraph({
  numbering: { reference: "numbers", level: 0 },
  children: [new TextRun(text)]
});

const H1 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  children: [new TextRun(text)],
  pageBreakBefore: true
});

const H2 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_2,
  children: [new TextRun(text)]
});

const H3 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_3,
  children: [new TextRun(text)]
});

const body = (text) => new Paragraph({
  children: [new TextRun({ text, size: 22 })],
  spacing: { after: 120 }
});

const bold = (text) => new Paragraph({
  children: [new TextRun({ text, size: 22, bold: true })],
  spacing: { after: 80 }
});

const kvRow = (key, value) => new TableRow({
  children: [
    new TableCell({
      borders: bordersAll,
      width: { size: 3000, type: WidthType.DXA },
      shading: { fill: "F5F0E0", type: ShadingType.CLEAR },
      margins: { top: 100, bottom: 100, left: 120, right: 120 },
      children: [new Paragraph({ children: [new TextRun({ text: key, bold: true, size: 20 })] })]
    }),
    new TableCell({
      borders: bordersAll,
      width: { size: 6360, type: WidthType.DXA },
      margins: { top: 100, bottom: 100, left: 120, right: 120 },
      children: [new Paragraph({ children: [new TextRun({ text: value, size: 20 })] })]
    })
  ]
});

// ========== CONTENIDO ==========
const content = [];

// ── PORTADA ──
content.push(new Paragraph({
  spacing: { before: 2400, after: 400 },
  alignment: AlignmentType.CENTER,
  children: [new TextRun({ text: "iRealEstateMx", font: "Georgia", bold: true, size: 72, color: "C9A227" })]
}));
content.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { after: 2400 },
  children: [new TextRun({ text: "MANUAL OPERATIVO", font: "Arial", size: 48, bold: true, color: "1A1A1A" })]
}));
content.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { after: 200 },
  children: [new TextRun({ text: "Guía por rol y fases del sistema", italics: true, size: 28 })]
}));
content.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { after: 1600 },
  children: [new TextRun({ text: "Plataforma de gestión inmobiliaria", size: 24, color: "666666" })]
}));
content.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  children: [new TextRun({ text: "irealestatemx.com", size: 24, color: "C9A227", bold: true })]
}));

// ── INTRODUCCIÓN ──
content.push(H1("1. Introducción"));
content.push(body(
  "iRealEstateMx es una plataforma integral para la gestión inmobiliaria que conecta a asesores, referidos, vendedores y compradores en un solo sistema. Automatiza procesos clave como la atención al cliente por WhatsApp, el registro de prospectos, la recolección de documentos y el seguimiento hasta la escrituración."
));
content.push(H3("¿Qué hace el sistema?"));
content.push(bullet("Responde automáticamente a clientes en WhatsApp las 24 horas."));
content.push(bullet("Agenda citas para conocer propiedades y desarrollos."));
content.push(bullet("Organiza toda la documentación del vendedor y comprador."));
content.push(bullet("Controla el avance de cada operación desde el primer contacto hasta el cierre."));
content.push(bullet("Calcula gastos de cierre y envía notificaciones automáticas."));
content.push(bullet("Mide el desempeño de agentes y referidos con KPIs en tiempo real."));

content.push(H3("¿A quién está dirigido este manual?"));
content.push(body(
  "Este manual está diseñado para que cualquier usuario del sistema — sin importar su nivel técnico — entienda cómo usar la plataforma según su rol. Si eres referido, vendedor, comprador, agente o administrador, aquí encontrarás tu sección específica."
));

content.push(H3("¿Cómo entrar al sistema?"));
content.push(number("Abre tu navegador (Chrome, Safari, Edge) y entra a irealestatemx.com."));
content.push(number("Haz clic en 'Iniciar sesión'."));
content.push(number("Escribe tu correo electrónico y contraseña."));
content.push(number("Si olvidaste tu contraseña, haz clic en '¿Olvidaste tu contraseña?' y sigue las instrucciones."));
content.push(body(
  "El sistema funciona también desde celular. No necesitas instalar nada; con el navegador basta."
));

// ── ROLES ──
content.push(H1("2. Roles del sistema"));
content.push(body(
  "El sistema tiene cinco roles. Cada usuario tiene UNO de estos roles y el menú cambia según lo que le corresponde hacer."
));

const rolesTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2000, 7360],
  rows: [
    new TableRow({
      children: [
        new TableCell({
          borders: bordersAll,
          width: { size: 2000, type: WidthType.DXA },
          shading: { fill: "C9A227", type: ShadingType.CLEAR },
          margins: { top: 100, bottom: 100, left: 120, right: 120 },
          children: [new Paragraph({ children: [new TextRun({ text: "Rol", bold: true, size: 22, color: "FFFFFF" })] })]
        }),
        new TableCell({
          borders: bordersAll,
          width: { size: 7360, type: WidthType.DXA },
          shading: { fill: "C9A227", type: ShadingType.CLEAR },
          margins: { top: 100, bottom: 100, left: 120, right: 120 },
          children: [new Paragraph({ children: [new TextRun({ text: "Descripción breve", bold: true, size: 22, color: "FFFFFF" })] })]
        })
      ]
    }),
    kvRow("Referido", "Persona externa que recomienda clientes a iRealEstateMx. Tiene un prefijo único (N, R, F, L, etc.) que identifica a sus referidos."),
    kvRow("Vendedor", "Dueño de una propiedad que quiere venderla a través de iRealEstateMx."),
    kvRow("Comprador", "Persona interesada en comprar una propiedad con nosotros."),
    kvRow("Agente", "Asesor inmobiliario del equipo. Gestiona propiedades, clientes y cierres."),
    kvRow("Admin", "Control total del sistema. Gestiona usuarios, desarrollos y configuración.")
  ]
});
content.push(rolesTable);

// ── REFERIDO ──
content.push(H1("3. Manual para Referidos"));
content.push(H3("¿Quién es un referido?"));
content.push(body(
  "Es una persona que recomienda clientes a iRealEstateMx. Cuando un cliente menciona tu prefijo al contactarnos por WhatsApp, el sistema lo asigna automáticamente como tu referido."
));

content.push(H3("¿Qué es tu prefijo?"));
content.push(body(
  "Es una letra o combinación única asignada por el administrador (ejemplo: N, R, F, L, SR, MC). Tus clientes deben mencionarlo en su primer mensaje de WhatsApp para que el sistema los vincule contigo."
));

content.push(H3("¿Qué puedes hacer?"));
content.push(bullet("Ver todos los prospectos que llegan con tu prefijo."));
content.push(bullet("Leer el mensaje original que envió cada cliente."));
content.push(bullet("Ver las notas que el agente ha ido agregando."));
content.push(bullet("Ver el estado actual de cada prospecto."));
content.push(bullet("Recibir un correo cuando uno de tus clientes agende una cita."));

content.push(H3("Pasos para usar 'Mis Prospectos'"));
content.push(number("Inicia sesión en irealestatemx.com."));
content.push(number("En el menú izquierdo, haz clic en 'Mis Prospectos'."));
content.push(number("Arriba verás los contadores: Total, Nuevos, Contactados, Citas, Negociación, Ventas."));
content.push(number("Cada prospecto aparece como una tarjeta con el nombre y estado."));
content.push(number("Haz clic en la tarjeta para ver el mensaje original y las notas del agente."));

content.push(H3("Estados de un prospecto"));
const estadosTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2400, 6960],
  rows: [
    kvRow("Nuevo", "Acaba de llegar por WhatsApp o formulario."),
    kvRow("Contactado", "El agente ya tuvo primer contacto."),
    kvRow("Cita agendada", "Se agendó visita."),
    kvRow("Cita asistió", "El cliente asistió a la visita."),
    kvRow("En negociación", "Se está negociando la operación."),
    kvRow("Venta cerrada", "La venta se concretó."),
    kvRow("Perdido", "El prospecto ya no avanzó.")
  ]
});
content.push(estadosTable);

content.push(body(""));
content.push(bold("Nota importante:"));
content.push(body(
  "Los referidos solo pueden consultar información; no pueden cambiar el estado de los prospectos. Esa acción la realiza el administrador o agente según avance el proceso."
));

// ── VENDEDOR ──
content.push(H1("4. Manual para Vendedores"));
content.push(H3("¿Quién es un vendedor?"));
content.push(body(
  "Es el dueño de una propiedad que desea venderla. El sistema te permite subir tus documentos personales y los de la propiedad para que el proceso avance hasta la escrituración."
));

content.push(H3("¿Qué puedes hacer?"));
content.push(bullet("Ver las propiedades donde estás asignado como vendedor."));
content.push(bullet("Seleccionar una propiedad existente que tu agente ya subió."));
content.push(bullet("Subir una propiedad nueva (solo datos básicos, sin fotos ni videos — el agente los agregará)."));
content.push(bullet("Subir tus documentos personales y los de la propiedad."));
content.push(bullet("Ver qué documentos faltan y cuáles ya están aprobados."));

content.push(H3("Pasos iniciales"));
content.push(number("Inicia sesión con el correo y contraseña que te compartió el agente."));
content.push(number("Si tu agente ya registró tu propiedad: ve a 'Seleccionar propiedad', elige la tuya y selecciona a tu agente."));
content.push(number("Si tu propiedad aún no está en el sistema: ve a 'Nueva propiedad' y llena solo los datos básicos (dirección, tipo, precio, recámaras, baños, metros)."));
content.push(number("Después ve a 'Mis propiedades' para empezar a subir documentos."));

content.push(H3("Documentos obligatorios del vendedor"));
content.push(bullet("INE (Identificación oficial)."));
content.push(bullet("CURP."));
content.push(bullet("Constancia de Situación Fiscal."));
content.push(bullet("Acta de Nacimiento."));
content.push(bullet("Acta de matrimonio o divorcio (opcional)."));
content.push(bullet("Escrituras de la propiedad."));
content.push(bullet("Boleta predial al corriente."));
content.push(bullet("Recibos de agua y luz recientes."));

content.push(H3("Cómo subir un documento"));
content.push(number("Entra a 'Mis propiedades' y haz clic en tu propiedad."));
content.push(number("Busca el documento en la lista (los obligatorios tienen un badge rojo)."));
content.push(number("Haz clic en 'Subir' y selecciona el archivo desde tu celular o computadora."));
content.push(number("Espera la confirmación. Recibirás una notificación por WhatsApp."));
content.push(number("El agente revisará cada documento y lo marcará como aprobado o rechazado."));

content.push(bold("Formatos válidos:"));
content.push(body("JPG, PNG, PDF, DOC, DOCX, WEBP. Tamaño máximo recomendado: 10 MB por archivo."));

// ── COMPRADOR ──
content.push(H1("5. Manual para Compradores"));
content.push(H3("¿Quién es un comprador?"));
content.push(body(
  "Es la persona interesada en comprar una propiedad. El sistema registra tu tipo de compra (contado, transferencia, crédito bancario, INFONAVIT o ISSEG) y te indica exactamente qué documentos necesitas subir."
));

content.push(H3("Tipos de compra"));
const tiposTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2800, 6560],
  rows: [
    kvRow("Contado", "Pago total con recurso propio."),
    kvRow("Transferencia", "Pago por transferencia bancaria directa."),
    kvRow("Crédito Bancario", "Financiamiento a través de un banco."),
    kvRow("Crédito Infonavit", "Crédito de vivienda Infonavit."),
    kvRow("Crédito ISSEG", "Crédito de vivienda ISSEG.")
  ]
});
content.push(tiposTable);

content.push(body(""));
content.push(H3("Documentos obligatorios base"));
content.push(bullet("INE (Identificación oficial)."));
content.push(bullet("CURP."));
content.push(bullet("Constancia de Situación Fiscal."));
content.push(bullet("Acta de Nacimiento."));
content.push(bullet("Acta de matrimonio (opcional)."));

content.push(body(""));
content.push(body("Según tu tipo de compra, se agregarán documentos adicionales (por ejemplo, precalificación para Infonavit, autorización bancaria, comprobante de ingresos, etc.). El sistema te los muestra automáticamente."));

content.push(H3("Pasos"));
content.push(number("Inicia sesión con el correo y contraseña que te compartió el agente."));
content.push(number("Ve a 'Seleccionar propiedad' y elige la que quieres comprar."));
content.push(number("En 'Mis propiedades' verás la lista de documentos a subir."));
content.push(number("Sube cada archivo y espera aprobación del agente."));
content.push(number("Cuando estén todos aprobados, el agente te dará fecha de escrituración y gastos de cierre."));

// ── AGENTE ──
content.push(H1("6. Manual para Agentes"));
content.push(H3("¿Quién es un agente?"));
content.push(body(
  "Asesor inmobiliario del equipo iRealEstateMx. Tiene acceso completo a propiedades, prospectos, seguimiento y al tablero Scrum (REstateFlow)."
));

content.push(H3("Tu menú principal"));
content.push(bullet("PROPIEDADES: Nueva propiedad, Mis propiedades."));
content.push(bullet("CRM: Prospectos, Seguimiento, REstateFlow."));
content.push(bullet("Puedes editar cualquier propiedad que sea tuya o de tu equipo."));

content.push(H3("Crear una nueva propiedad"));
content.push(number("Haz clic en 'Nueva propiedad' en el menú."));
content.push(number("Llena los datos básicos: tipo, operación (venta/renta), dirección, ciudad, precio, recámaras, baños, m²."));
content.push(number("Sube las fotos de la propiedad. Puedes marcar una como portada."));
content.push(number("Elige un desarrollo si pertenece a uno (Cárcamos, Privada del Fresno, etc.)."));
content.push(number("Haz clic en 'Generar'. La IA creará descripciones profesionales y texto para Instagram."));
content.push(number("La propiedad queda disponible en 'Mis propiedades'."));

content.push(H3("Asignar clientes a una propiedad"));
content.push(body("Entra a editar la propiedad y baja a 'Asignar clientes'. Ahí eliges vendedor y comprador de la lista."));
content.push(bullet("Puedes dejar vacíos los dos campos si aún no tienes clientes registrados."));
content.push(bullet("Puedes auto-asignarte como vendedor o comprador si el cliente no se quiere registrar (botón 'Asignarme')."));
content.push(bullet("Si quitas una asignación y ya había documentos subidos, el sistema te pedirá confirmación."));

content.push(H3("Seguimiento"));
content.push(body(
  "La sección 'Seguimiento' es el centro de control. Muestra todas las propiedades activas con:"
));
content.push(bullet("Qué documentos faltan (vendedor, comprador, propiedad)."));
content.push(bullet("Botones de WhatsApp para contactar rápido al cliente o al agente."));
content.push(bullet("Semáforo visual del avance."));

content.push(H3("Gestión de prospectos"));
content.push(number("Ve a 'Prospectos' en el menú CRM."));
content.push(number("Filtra por estado, fuente (chatbot, manual, referido) o referido específico."));
content.push(number("Haz clic en un prospecto para cambiar su estado y agregar notas."));
content.push(number("El estado que elijas actualiza el contador del referido (si lo tiene) y dispara notificaciones."));

content.push(H3("REstateFlow (metodología Scrum)"));
content.push(body(
  "REstateFlow adapta Scrum al ritmo inmobiliario. Cada semana se crea un Sprint y se asignan propiedades prioritarias al Kanban Board."
));
content.push(bullet("Dashboard: KPIs personales y del equipo, con semáforo de desempeño."));
content.push(bullet("Scrum Board: 5 columnas — Para esta semana, En progreso, Bloqueado, Por revisar, Completado."));
content.push(bullet("Daily Standup: responde cada día qué avanzaste, qué te bloquea, qué harás hoy."));
content.push(bullet("KPIs Referidos: ranking con estadísticas por referido."));
content.push(bullet("Sprint Review: reporte automático los viernes."));

// ── ADMIN ──
content.push(H1("7. Manual para Administradores"));
content.push(H3("¿Qué puede hacer el admin?"));
content.push(body("Todo lo que hace un agente, más:"));
content.push(bullet("Crear, editar y eliminar usuarios."));
content.push(bullet("Cambiar roles (referido, vendedor, comprador, agente, admin)."));
content.push(bullet("Asignar prefijos a referidos."));
content.push(bullet("Gestionar desarrollos (Cárcamos, Privada del Fresno, etc.)."));
content.push(bullet("Ver métricas globales del sistema."));
content.push(bullet("Configurar el chatbot (pausar, reactivar, bloquear números)."));
content.push(bullet("Cambiar estados de prospectos de forma masiva."));
content.push(bullet("Eliminar prospectos o propiedades."));

content.push(H3("Gestión de usuarios"));
content.push(number("Ve a 'Administrar' → 'Usuarios' en el menú."));
content.push(number("Haz clic en 'Nuevo usuario' para crear uno nuevo."));
content.push(number("Llena: nombre, correo, contraseña temporal, rol y teléfono."));
content.push(number("Si es referido, asigna un prefijo único (N, R, F, L, SR, etc.)."));
content.push(number("Comparte las credenciales con el usuario."));

content.push(H3("Gestión de desarrollos"));
content.push(body(
  "Los desarrollos son proyectos inmobiliarios que se promocionan al público (Cárcamos Residencial, Privada del Fresno, etc.). Desde 'Administrar → Desarrollos' puedes editar: nombre, descripción, precio desde, amenidades, fotos, brochure PDF."
));

// ── FASES DEL PROCESO ──
content.push(H1("8. Fases del proceso inmobiliario"));
content.push(body(
  "Todo cliente pasa por estas fases dentro del sistema. Cada fase dispara notificaciones automáticas a las personas correctas."
));

content.push(H3("Fase 1: Captación"));
content.push(bullet("El cliente contacta por WhatsApp mencionando un desarrollo o palabra clave."));
content.push(bullet("El chatbot lo detecta, responde automáticamente y lo registra como prospecto."));
content.push(bullet("Si menciona un prefijo, se vincula al referido correspondiente."));
content.push(bullet("Estado inicial: 'Nuevo'."));

content.push(H3("Fase 2: Conversación y agenda"));
content.push(bullet("El chatbot conversa con el cliente para entender su interés."));
content.push(bullet("Le comparte el brochure del desarrollo."));
content.push(bullet("Agenda una visita verificando disponibilidad del calendario."));
content.push(bullet("Crea un evento en Google Calendar."));
content.push(bullet("Envía correo al agente y al referido."));
content.push(bullet("Estado: 'Cita agendada'."));

content.push(H3("Fase 3: Visita"));
content.push(bullet("El agente realiza la visita."));
content.push(bullet("Marca la cita como 'asistió' o 'no asistió'."));
content.push(bullet("Estado: 'Cita asistió'."));

content.push(H3("Fase 4: Registro y documentación"));
content.push(bullet("Si el cliente quiere avanzar, se registra como vendedor o comprador."));
content.push(bullet("Se le asigna a una propiedad."));
content.push(bullet("El sistema le muestra qué documentos debe subir."));
content.push(bullet("El agente aprueba o rechaza cada documento."));

content.push(H3("Fase 5: Negociación"));
content.push(bullet("Definición de precio final y condiciones."));
content.push(bullet("Estado: 'En negociación'."));

content.push(H3("Fase 6: Cierre"));
content.push(bullet("Se agenda fecha de escrituración con notaría."));
content.push(bullet("El sistema calcula gastos de vendedor y comprador."));
content.push(bullet("Envía desglose por WhatsApp y correo."));
content.push(bullet("Estado: 'Venta cerrada'."));

content.push(H3("Fase 7: Post-venta"));
content.push(bullet("Propiedad marcada como vendida."));
content.push(bullet("El cliente queda en la base de datos para futuras operaciones."));

// ── MÓDULOS ──
content.push(H1("9. Módulos principales"));

content.push(H3("9.1 Chatbot de WhatsApp"));
content.push(body("Responde a clientes las 24 horas con inteligencia artificial, simulando ser el asesor Esteban Castellanos."));
content.push(bullet("Se activa solo cuando detecta palabras clave: 'casa', 'comprar', 'Cárcamos', 'Fresno', etc."));
content.push(bullet("Se pausa 24 horas cuando el admin o agente escribe manualmente."));
content.push(bullet("Agenda citas verificando calendario."));
content.push(bullet("Comparte el brochure del desarrollo."));
content.push(bullet("Registra automáticamente al prospecto."));

content.push(H3("9.2 Seguimiento"));
content.push(body("Tablero con todas las propiedades activas, documentos faltantes y contactos rápidos por WhatsApp. Ideal para el seguimiento diario del agente."));

content.push(H3("9.3 REstateFlow (Scrum)"));
content.push(body("Tablero de trabajo semanal basado en metodología Scrum adaptada a bienes raíces. Mide cumplimiento, bloqueos y ventas por agente y referido."));

content.push(H3("9.4 Documentos"));
content.push(body("Sistema de categorías: vendedor, comprador, propiedad, compra. Cada documento tiene tres estados: pendiente, aprobado, rechazado. Al cambiar estado se envía notificación por WhatsApp."));

content.push(H3("9.5 Citas"));
content.push(body("Agendadas por el chatbot o manualmente por el agente. Horario válido: 9:00 a 19:00 hrs. Se sincronizan con Google Calendar y notifican a referido por correo."));

content.push(H3("9.6 Gastos de cierre"));
content.push(body("Calcula gastos de vendedor (ISR, honorarios, cancelación de hipoteca, etc.) y comprador (avalúo, escrituración, impuestos, notaría, etc.). Envía desglose por WhatsApp y correo."));

// ── MANUAL TÉCNICO ──
content.push(H1("10. Manual Técnico"));
content.push(body(
  "Esta sección describe la arquitectura y herramientas del sistema. Está pensada para personal técnico, desarrolladores o administradores avanzados."
));

content.push(H3("10.1 Stack tecnológico principal"));
const techTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2800, 6560],
  rows: [
    kvRow("FastAPI (Python)", "Framework web de alto rendimiento. Maneja todas las rutas HTTP, autenticación y APIs."),
    kvRow("PostgreSQL", "Base de datos relacional donde viven usuarios, propiedades, prospectos, documentos y citas."),
    kvRow("databases (async)", "Driver asíncrono de Python para PostgreSQL. Permite manejar muchas conexiones sin bloquear."),
    kvRow("Jinja2", "Motor de plantillas HTML. Renderiza todas las pantallas del sistema en el servidor."),
    kvRow("bcrypt", "Hashing seguro de contraseñas. Las contraseñas nunca se guardan en texto plano."),
    kvRow("Docker", "Contenedorización del sistema para despliegue consistente en cualquier servidor.")
  ]
});
content.push(techTable);

content.push(body(""));
content.push(H3("10.2 Integraciones externas"));
const integTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2800, 6560],
  rows: [
    kvRow("WAHA", "Puente entre WhatsApp y el sistema. Recibe y envía mensajes vía HTTP API."),
    kvRow("n8n", "Automatizador de flujos. Orquesta el chatbot: recibe webhook de WAHA, llama al backend, llama a la IA y responde al cliente."),
    kvRow("OpenAI GPT", "Modelo de lenguaje que da inteligencia al chatbot. Genera respuestas naturales siguiendo el prompt del asesor."),
    kvRow("Google Calendar", "Crea eventos cuando el chatbot agenda una cita."),
    kvRow("Gmail SMTP", "Envía todas las notificaciones por correo electrónico."),
    kvRow("Kommo CRM", "Sistema alternativo donde se sincronizan leads para seguimiento comercial.")
  ]
});
content.push(integTable);

content.push(body(""));
content.push(H3("10.3 Endpoints API críticos"));
const apiTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [3600, 5760],
  rows: [
    kvRow("POST /api/whatsapp/debounce", "Recibe cada mensaje de WhatsApp desde n8n. Aplica anti-duplicados, keywords y debounce de 12 segundos."),
    kvRow("GET /api/chatbot/buscar", "Búsqueda de propiedades y desarrollos para el chatbot. Devuelve URLs absolutas de brochures."),
    kvRow("GET /api/citas/disponibilidad", "Verifica si un horario está libre (9–19 hrs)."),
    kvRow("POST /api/citas/registrar", "Registra una cita confirmada y notifica al referido si aplica."),
    kvRow("POST /api/chatbot/registrar-cita", "Endpoint alternativo que también crea prospecto si no existe."),
    kvRow("POST /api/prospectos/registrar", "Registra prospecto directamente desde un formulario o n8n."),
    kvRow("POST /api/whatsapp/pause", "Pausa el bot para un teléfono específico (24 horas)."),
    kvRow("POST /api/whatsapp/resume", "Reactiva el bot para un teléfono.")
  ]
});
content.push(apiTable);

content.push(body(""));
content.push(H3("10.4 Flujo completo del chatbot"));
content.push(number("El cliente envía un mensaje a WhatsApp."));
content.push(number("WAHA recibe el mensaje y dispara un webhook hacia n8n."));
content.push(number("n8n llama a POST /api/whatsapp/debounce con el teléfono, el mensaje, el nombre y el flag fromMe."));
content.push(number("El backend aplica filtros: teléfonos bloqueados, dedup de mensajes duplicados, cooldown de 30s post-respuesta, lock por teléfono."));
content.push(number("Si fromMe=true: se interpreta como que el admin escribió manualmente y pausa el bot 24 horas."));
content.push(number("Si no está pausado y tiene keyword: se activa la conversación y acumula mensajes por 12 segundos (debounce)."));
content.push(number("Al terminar el debounce, combina mensajes, registra el prospecto y devuelve process:true."));
content.push(number("n8n envía los datos al AI Agent con el prompt del asesor."));
content.push(number("La IA genera la respuesta. Si es cita confirmada, incluye un bloque especial JSON."));
content.push(number("n8n envía la respuesta al cliente por WAHA."));
content.push(number("Si hay cita: n8n llama a /api/citas/registrar y Google Calendar crea el evento."));
content.push(number("El sistema envía correo al admin y al referido (si aplica)."));

content.push(H3("10.5 Sistema de seguridad"));
content.push(bullet("Autenticación por sesión con cookies HTTP-only."));
content.push(bullet("Contraseñas hasheadas con bcrypt (nunca en texto plano)."));
content.push(bullet("Rate limiting por endpoint para prevenir abuso."));
content.push(bullet("Verificación de rol en cada acción crítica."));
content.push(bullet("Protección CSRF en formularios."));
content.push(bullet("Los agentes solo pueden editar propiedades propias; el admin tiene control total."));

content.push(H3("10.6 Base de datos — Tablas principales"));
const dbTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2800, 6560],
  rows: [
    kvRow("usuarios", "Cuentas de login. Contiene rol, prefijo (referido), teléfono y estado activo."),
    kvRow("propiedades", "Catálogo de propiedades con fotos, descripción, vendedor y comprador asignados."),
    kvRow("desarrollos", "Proyectos inmobiliarios con brochure PDF y amenidades."),
    kvRow("documentos", "Archivos subidos por vendedor y comprador con estado (pendiente, aprobado, rechazado)."),
    kvRow("prospectos", "Leads captados por chatbot o formulario. Incluye referido_id, estado y mensaje original."),
    kvRow("citas_chatbot", "Citas agendadas con fecha, hora, desarrollo y estado."),
    kvRow("sprints / sprint_items", "REstateFlow — sprints semanales y propiedades en el Kanban."),
    kvRow("respuestas_diarias", "Standups diarios por agente."),
    kvRow("bloqueos_historico", "Historial de bloqueos reportados y su resolución."),
    kvRow("historial_prospectos", "Historial de interacciones con cada prospecto (mensajes, notas, cambios de estado).")
  ]
});
content.push(dbTable);

content.push(body(""));
content.push(H3("10.7 Protecciones del chatbot"));
content.push(body("El chatbot tiene varias capas para evitar comportamientos incorrectos:"));
content.push(bullet("Dedup de mensaje exacto: si llega el mismo texto dos veces en menos de 15 segundos, se ignora."));
content.push(bullet("Cooldown post-respuesta: después de responder, no procesa nuevos mensajes del mismo teléfono por 30 segundos."));
content.push(bullet("Lock por teléfono: evita procesamiento concurrente cuando n8n reintenta."));
content.push(bullet("Pausa automática al escribir manualmente: 24 horas al detectar fromMe=true."));
content.push(bullet("Palabras clave obligatorias para activación inicial."));
content.push(bullet("Lista de teléfonos bloqueados (desarrolladores, proveedores) para los que nunca se activa."));

content.push(H3("10.8 Variables de entorno relevantes"));
const envTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [3200, 6160],
  rows: [
    kvRow("DATABASE_URL", "Conexión a PostgreSQL."),
    kvRow("SMTP_HOST / SMTP_USER / SMTP_PASS", "Credenciales de Gmail para envío de correos."),
    kvRow("WAHA_API_URL", "URL del servicio WAHA para enviar mensajes."),
    kvRow("ADMIN_EMAIL / ADMIN_NAME", "Correo del administrador para notificaciones."),
    kvRow("BOT_BLOCKED_PHONES", "Lista separada por comas de teléfonos que nunca activan el bot."),
    kvRow("OPENAI_API_KEY", "Clave de OpenAI (usada por n8n, no directamente por el backend).")
  ]
});
content.push(envTable);

// ── SOPORTE ──
content.push(H1("11. Soporte y contacto"));
content.push(body("Si encuentras un problema o tienes dudas sobre el sistema:"));
content.push(bullet("Contacta directamente al administrador del sistema."));
content.push(bullet("Reporta bugs o errores adjuntando captura de pantalla si es posible."));
content.push(bullet("Para solicitudes de usuarios nuevos, escribe al admin con: nombre, correo, teléfono y rol deseado."));

content.push(body(""));
content.push(body(""));
content.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  children: [new TextRun({ text: "iRealEstateMx — Plataforma de gestión inmobiliaria", italics: true, size: 20, color: "666666" })]
}));
content.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  children: [new TextRun({ text: "irealestatemx.com", size: 20, color: "C9A227", bold: true })]
}));

// ---------- DOCUMENT ----------
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: "C9A227" },
        paragraph: { spacing: { before: 400, after: 300 }, outlineLevel: 0 }
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 30, bold: true, font: "Arial", color: "1A1A1A" },
        paragraph: { spacing: { before: 300, after: 200 }, outlineLevel: 1 }
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Arial", color: "C9A227" },
        paragraph: { spacing: { before: 240, after: 160 }, outlineLevel: 2 }
      }
    ]
  },
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [
          {
            level: 0, format: LevelFormat.BULLET, text: "•",
            alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } }
          },
          {
            level: 1, format: LevelFormat.BULLET, text: "◦",
            alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 1440, hanging: 360 } } }
          }
        ]
      },
      {
        reference: "numbers",
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: "%1.",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } }
        }]
      }
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
      }
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          children: [new TextRun({ text: "iRealEstateMx — Manual Operativo", size: 18, color: "888888", italics: true })]
        })]
      })
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: "Página ", size: 18, color: "888888" }),
            new TextRun({ children: [PageNumber.CURRENT], size: 18, color: "888888" }),
            new TextRun({ text: " de ", size: 18, color: "888888" }),
            new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 18, color: "888888" })
          ]
        })]
      })
    },
    children: content
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("Manual_Operativo_iRealEstateMx.docx", buffer);
  console.log("OK: Manual_Operativo_iRealEstateMx.docx creado");
});
