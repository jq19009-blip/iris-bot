"""
Memoria y persistencia de Iris en SQLite:
- Historial de conversación (`mensajes`).
- Consultas académicas analizadas con salida estructurada (`consultas_estructuradas`).
- Solicitudes de constancia de alumno regular (`solicitudes_constancia`).
"""

import aiosqlite

RUTA_DB = "iris.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS mensajes (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    rol     TEXT NOT NULL CHECK (rol IN ('user', 'model')),
    texto   TEXT NOT NULL,
    fecha   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mensajes_usuario ON mensajes (user_id, id);

CREATE TABLE IF NOT EXISTS consultas_estructuradas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    categoria   TEXT    NOT NULL,
    urgencia    TEXT    NOT NULL,
    materia     TEXT    NOT NULL,
    resumen     TEXT    NOT NULL,
    creada      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS solicitudes_constancia (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    nombre_completo TEXT    NOT NULL,
    legajo          TEXT    NOT NULL,
    destinatario    TEXT    NOT NULL,
    fecha_entrega   TEXT    NOT NULL,
    creada          TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


async def inicializar() -> None:
    """Crea las tablas e índices si todavía no existen."""
    async with aiosqlite.connect(RUTA_DB) as db:
        await db.executescript(ESQUEMA)
        await db.commit()


async def guardar_intercambio(user_id: int, pregunta: str, respuesta: str) -> None:
    """Guarda en una sola operación el mensaje del usuario y la respuesta del modelo."""
    async with aiosqlite.connect(RUTA_DB) as db:
        await db.executemany(
            "INSERT INTO mensajes (user_id, rol, texto) VALUES (?, ?, ?)",
            [
                (user_id, "user", pregunta),
                (user_id, "model", respuesta),
            ],
        )
        await db.commit()


async def obtener_historial(user_id: int, limite: int) -> list[tuple[str, str]]:
    """Devuelve los últimos `limite` mensajes del usuario en orden cronológico."""
    async with aiosqlite.connect(RUTA_DB) as db:
        cursor = await db.execute(
            "SELECT rol, texto FROM mensajes WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, limite),
        )
        filas = await cursor.fetchall()
    return list(reversed(filas))


async def borrar_historial(user_id: int) -> int:
    """Borra la conversación de un usuario y devuelve cuántos mensajes eliminó."""
    async with aiosqlite.connect(RUTA_DB) as db:
        cursor = await db.execute("DELETE FROM mensajes WHERE user_id = ?", (user_id,))
        await db.commit()
        return cursor.rowcount


async def guardar_consulta_estructurada(
    user_id: int,
    categoria: str,
    urgencia: str,
    materia: str,
    resumen: str,
) -> int:
    """Guarda el análisis estructurado de una consulta y devuelve su ID."""
    async with aiosqlite.connect(RUTA_DB) as db:
        cursor = await db.execute(
            "INSERT INTO consultas_estructuradas (user_id, categoria, urgencia, materia, resumen) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, categoria, urgencia, materia, resumen),
        )
        await db.commit()
        return cursor.lastrowid


async def guardar_solicitud_constancia(
    user_id: int,
    nombre_completo: str,
    legajo: str,
    destinatario: str,
    fecha_entrega: str,
) -> int:
    """Guarda una solicitud confirmada de constancia y devuelve su número de trámite."""
    async with aiosqlite.connect(RUTA_DB) as db:
        cursor = await db.execute(
            "INSERT INTO solicitudes_constancia (user_id, nombre_completo, legajo, destinatario, fecha_entrega) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, nombre_completo, legajo, destinatario, fecha_entrega),
        )
        await db.commit()
        return cursor.lastrowid
