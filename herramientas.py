"""
Herramientas de Iris: funciones que el modelo puede pedir que se ejecuten.

El módulo se completa por etapas y tendrá cuatro partes:
1. Datos fijos.
2. Las funciones propiamente dichas, que consultan APIs externas.
3. Las declaraciones: la descripción de cada función en JSON Schema,
   que es lo único que el modelo ve de ellas (próxima etapa).
4. Un despachador que ejecuta la función pedida por el modelo (próxima etapa).
"""

import logging  # registro de eventos en la terminal
from datetime import date, datetime, timedelta, timezone  # manejo de fechas

import httpx  # cliente HTTP asíncrono (dependencia de python-telegram-bot)

logger = logging.getLogger("iris")  # mismo registrador que bot.py

# Tiempo máximo de espera de cada consulta HTTP, en segundos. Sin un límite,
# una API que no responde dejaría al usuario esperando indefinidamente.
TIEMPO_ESPERA = 10

# ---------------------------------------------------------------------------
# 1. Datos fijos
# ---------------------------------------------------------------------------

# API de ArgentinaDatos: devuelve los feriados de un año, sin clave ni registro.
# Ejemplo completo: https://api.argentinadatos.com/v1/feriados/2026
URL_FERIADOS = "https://api.argentinadatos.com/v1/feriados"

# Según su documentación, la API solo tiene datos de estos años.
ANIO_MINIMO = 2016
ANIO_MAXIMO = 2026

# Argentina usa UTC-3 todo el año (no tiene horario de verano). Se define la
# zona a mano para no depender de bases de zonas horarias, que Windows no trae.
ZONA_ARGENTINA = timezone(timedelta(hours=-3))


def _hoy() -> date:
    """Devuelve la fecha de hoy en Argentina."""
    return datetime.now(ZONA_ARGENTINA).date()


def _a_fecha(texto) -> date | None:
    """Convierte un texto 'AAAA-MM-DD' en fecha. Si no tiene ese formato, devuelve None."""
    try:
        return date.fromisoformat(str(texto))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 2. Funciones
# ---------------------------------------------------------------------------


async def obtener_feriados(
    anio: int | None = None, mes: int | None = None, solo_proximos: bool = False
) -> dict:
    """Devuelve los feriados nacionales de Argentina (API de ArgentinaDatos)."""

    hoy = _hoy()

    # Si el modelo no indica el año, se usa el actual.
    if anio is None:
        anio = hoy.year
    anio = int(anio)

    # Se valida antes de consultar: el modelo puede pedir un año que la API no tiene.
    # El error se devuelve como dato, no como excepción: así el modelo puede
    # explicárselo al usuario con naturalidad.
    if not ANIO_MINIMO <= anio <= ANIO_MAXIMO:
        return {
            "error": f"No hay datos de feriados para el año {anio}",
            "anios_disponibles": f"{ANIO_MINIMO} a {ANIO_MAXIMO}",
        }

    if mes is not None:
        mes = int(mes)
        if not 1 <= mes <= 12:
            return {"error": f"Mes inválido: {mes}", "meses_validos": "1 a 12"}

    # "async with" abre el cliente HTTP y lo cierra al terminar el bloque.
    async with httpx.AsyncClient(timeout=TIEMPO_ESPERA) as cliente_http:
        respuesta = await cliente_http.get(f"{URL_FERIADOS}/{anio}")
        respuesta.raise_for_status()  # convierte un código HTTP de error (4xx, 5xx) en excepción
        datos = respuesta.json()  # lista de diccionarios con fecha, tipo y nombre

    feriados = []
    for item in datos:
        fecha = _a_fecha(item.get("fecha"))

        # Filtro por mes (si se pidió). Si la fecha no se pudo interpretar,
        # el feriado se conserva en lugar de descartarlo en silencio.
        if mes is not None and fecha is not None and fecha.month != mes:
            continue
        # Filtro de próximos: descarta los feriados que ya pasaron.
        if solo_proximos and fecha is not None and fecha < hoy:
            continue

        # Se devuelven solo los campos útiles para el modelo.
        feriados.append(
            {
                "fecha": item.get("fecha"),
                "tipo": item.get("tipo"),
                "nombre": item.get("nombre"),
            }
        )

    # fecha_actual le dice al modelo qué día es hoy: sin ese dato no podría
    # responder "¿cuál es el próximo feriado?", porque no conoce el presente.
    return {
        "fecha_actual": hoy.isoformat(),
        "anio": anio,
        "cantidad": len(feriados),
        "feriados": feriados,
    }


# ---------------------------------------------------------------------------
# 3. Declaraciones para el modelo
# ---------------------------------------------------------------------------

# Esto es lo único que Gemini conoce de cada función: su nombre, para qué sirve
# y qué parámetros recibe, descriptos con JSON Schema. La calidad de las
# descripciones determina si el modelo elige bien la función y sus argumentos.
DECLARACIONES = [
    {
        "type": "function",
        "name": "obtener_feriados",
        "description": (
            "Obtiene los feriados nacionales y días no laborables de Argentina de un año, "
            "junto con la fecha de hoy. "
            "Usala cuando el usuario pregunte si un día es feriado, cuándo es el próximo "
            "feriado o fin de semana largo, o cuando un feriado pueda afectar una cursada, "
            "una entrega o un examen. "
            "No informa fechas de exámenes ni el calendario académico de la facultad. "
            "Los días de tipo 'puente' son días no laborables con fines turísticos, no "
            "feriados nacionales: aclará que conviene confirmar con la facultad si hay actividad."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "anio": {
                    "type": "integer",
                    "description": (
                        f"Año a consultar, entre {ANIO_MINIMO} y {ANIO_MAXIMO}. "
                        "Si no se indica, se usa el año actual."
                    ),
                },
                "mes": {
                    "type": "integer",
                    "description": "Mes de 1 a 12 para ver solo los feriados de ese mes. Omitilo para ver todo el año.",
                },
                "solo_proximos": {
                    "type": "boolean",
                    "description": (
                        "Poné true para listar solo los feriados que todavía no pasaron, "
                        "por ejemplo ante '¿cuál es el próximo feriado?'."
                    ),
                },
            },
            # No hay parámetros obligatorios: sin ninguno, devuelve el año actual.
        },
    },
]


# ---------------------------------------------------------------------------
# 4. Despachador
# ---------------------------------------------------------------------------

# Relaciona el nombre que usa el modelo con la función de Python que se ejecuta.
FUNCIONES = {
    "obtener_feriados": obtener_feriados,
}


async def ejecutar_funcion(nombre: str, argumentos: dict) -> dict:
    """Ejecuta la función pedida por el modelo y devuelve siempre un diccionario."""
    logger.info("El modelo pidió %s(%s)", nombre, argumentos)

    funcion = FUNCIONES.get(nombre)
    if funcion is None:  # el modelo pidió una función que no existe
        return {"error": f"Función desconocida: {nombre}"}

    try:
        # **argumentos desempaqueta el diccionario como parámetros con nombre:
        # {"mes": 12} se convierte en obtener_feriados(mes=12).
        return await funcion(**argumentos)
    except Exception as error:
        # Cualquier falla (API caída, argumentos inválidos, tiempo agotado) se
        # informa al modelo como dato, para que pueda responder al usuario.
        logger.exception("Falló la herramienta %s", nombre)
        return {"error": f"No se pudo obtener el dato: {type(error).__name__}"}
