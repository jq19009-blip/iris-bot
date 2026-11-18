"""
Herramientas de Iris: funciones que Gemini puede pedir que se ejecuten.

Incluye:
- Consulta de feriados nacionales argentinos.
- Consulta del backend académico local de Spring Boot.
"""

import logging
import os
from datetime import date, datetime, timedelta, timezone

import httpx

logger = logging.getLogger("iris")

# Tiempo máximo de espera de cada consulta HTTP, en segundos.
TIEMPO_ESPERA = 10

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

# API pública de feriados.
URL_FERIADOS = "https://api.argentinadatos.com/v1/feriados"
ANIO_MINIMO = 2016
ANIO_MAXIMO = 2026

# URL base del backend Spring Boot.
# Puede configurarse desde .env sin cambiar este archivo.
URL_API_ACADEMICA = os.getenv(
    "API_ACADEMICA_URL",
    "http://localhost:8080/api/estudiante",
)

# Argentina utiliza UTC-3.
ZONA_ARGENTINA = timezone(timedelta(hours=-3))


def _hoy() -> date:
    """Devuelve la fecha actual en Argentina."""
    return datetime.now(ZONA_ARGENTINA).date()


def _a_fecha(texto) -> date | None:
    """Convierte un texto AAAA-MM-DD a date o devuelve None si es inválido."""
    try:
        return date.fromisoformat(str(texto))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Herramienta: feriados
# ---------------------------------------------------------------------------

async def obtener_feriados(
    anio: int | None = None,
    mes: int | None = None,
    solo_proximos: bool = False,
) -> dict:
    """Devuelve los feriados nacionales de Argentina."""

    hoy = _hoy()

    if anio is None:
        anio = hoy.year

    anio = int(anio)

    if not ANIO_MINIMO <= anio <= ANIO_MAXIMO:
        return {
            "error": f"No hay datos de feriados para el año {anio}",
            "anios_disponibles": f"{ANIO_MINIMO} a {ANIO_MAXIMO}",
        }

    if mes is not None:
        mes = int(mes)

        if not 1 <= mes <= 12:
            return {
                "error": f"Mes inválido: {mes}",
                "meses_validos": "1 a 12",
            }

    async with httpx.AsyncClient(timeout=TIEMPO_ESPERA) as cliente_http:
        respuesta = await cliente_http.get(f"{URL_FERIADOS}/{anio}")
        respuesta.raise_for_status()
        datos = respuesta.json()

    feriados = []

    for item in datos:
        fecha = _a_fecha(item.get("fecha"))

        if mes is not None and fecha is not None and fecha.month != mes:
            continue

        if solo_proximos and fecha is not None and fecha < hoy:
            continue

        feriados.append(
            {
                "fecha": item.get("fecha"),
                "tipo": item.get("tipo"),
                "nombre": item.get("nombre"),
            }
        )

    return {
        "fecha_actual": hoy.isoformat(),
        "anio": anio,
        "cantidad": len(feriados),
        "feriados": feriados,
    }


# ---------------------------------------------------------------------------
# Herramientas: backend académico
# ---------------------------------------------------------------------------

async def _consultar_api_academica(recurso: str = "") -> dict | list:
    """
    Consulta un endpoint del backend académico.

    recurso vacío consulta los datos personales.
    Ejemplos: aprobadas, pendientes, historial.
    """
    url = f"{URL_API_ACADEMICA}/{recurso}" if recurso else URL_API_ACADEMICA

    async with httpx.AsyncClient(timeout=TIEMPO_ESPERA) as cliente_http:
        respuesta = await cliente_http.get(url)
        respuesta.raise_for_status()
        return respuesta.json()


async def obtener_datos_estudiante() -> dict:
    """Devuelve nombre, DNI, legajo, carrera e institución del estudiante."""
    return await _consultar_api_academica()


async def obtener_materias_carrera() -> list:
    """Devuelve todas las materias previstas en la carrera."""
    return await _consultar_api_academica("materias")


async def obtener_materias_inscriptas() -> list:
    """Devuelve las materias que el estudiante está cursando actualmente."""
    return await _consultar_api_academica("inscriptas")


async def obtener_materias_aprobadas() -> list:
    """Devuelve materias aprobadas, notas y fechas de aprobación."""
    return await _consultar_api_academica("aprobadas")


async def obtener_materias_desaprobadas() -> list:
    """Devuelve materias desaprobadas, notas y fechas de resultado."""
    return await _consultar_api_academica("desaprobadas")


async def obtener_materias_pendientes() -> list:
    """Devuelve materias pendientes que aún no fueron cursadas."""
    return await _consultar_api_academica("pendientes")


async def obtener_notas_academicas() -> list:
    """Devuelve todas las materias que tienen una nota final."""
    return await _consultar_api_academica("notas")


async def obtener_historial_academico() -> list:
    """Devuelve el historial académico completo del estudiante."""
    return await _consultar_api_academica("historial")


# ---------------------------------------------------------------------------
# Declaraciones de herramientas para Gemini
# ---------------------------------------------------------------------------

DECLARACIONES = [
    {
        "type": "function",
        "name": "obtener_feriados",
        "description": (
            "Obtiene los feriados nacionales y días no laborables de Argentina "
            "de un año, junto con la fecha de hoy. Usala cuando el usuario "
            "pregunte si un día es feriado, cuándo es el próximo feriado o "
            "cuándo hay un fin de semana largo. No informa fechas de exámenes "
            "ni calendario académico de la facultad."
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
                    "description": (
                        "Mes de 1 a 12 para consultar solo los feriados de ese mes."
                    ),
                },
                "solo_proximos": {
                    "type": "boolean",
                    "description": (
                        "Usar true para consultar solamente los feriados futuros."
                    ),
                },
            },
        },
    },
    {
        "type": "function",
        "name": "obtener_datos_estudiante",
        "description": (
            "Obtiene los datos personales y académicos generales del estudiante: "
            "nombre, apellido, DNI, legajo, carrera e institución."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "type": "function",
        "name": "obtener_materias_carrera",
        "description": (
            "Obtiene todas las materias incluidas en el plan de estudios "
            "de la carrera del estudiante."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "type": "function",
        "name": "obtener_materias_inscriptas",
        "description": (
            "Obtiene las materias que el estudiante está cursando actualmente."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "type": "function",
        "name": "obtener_materias_aprobadas",
        "description": (
            "Obtiene las materias aprobadas por el estudiante, incluyendo "
            "notas finales y fechas de aprobación."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "type": "function",
        "name": "obtener_materias_desaprobadas",
        "description": (
            "Obtiene las materias desaprobadas por el estudiante, incluyendo "
            "notas finales y fechas de resultado."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "type": "function",
        "name": "obtener_materias_pendientes",
        "description": (
            "Obtiene las materias que el estudiante todavía no cursó "
            "ni aprobó."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "type": "function",
        "name": "obtener_notas_academicas",
        "description": (
            "Obtiene todas las notas finales registradas para el estudiante."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "type": "function",
        "name": "obtener_historial_academico",
        "description": (
            "Obtiene el historial académico completo: materias aprobadas, "
            "desaprobadas e inscriptas actualmente."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
]


# ---------------------------------------------------------------------------
# Despachador
# ---------------------------------------------------------------------------

FUNCIONES = {
    "obtener_feriados": obtener_feriados,
    "obtener_datos_estudiante": obtener_datos_estudiante,
    "obtener_materias_carrera": obtener_materias_carrera,
    "obtener_materias_inscriptas": obtener_materias_inscriptas,
    "obtener_materias_aprobadas": obtener_materias_aprobadas,
    "obtener_materias_desaprobadas": obtener_materias_desaprobadas,
    "obtener_materias_pendientes": obtener_materias_pendientes,
    "obtener_notas_academicas": obtener_notas_academicas,
    "obtener_historial_academico": obtener_historial_academico,
}


async def ejecutar_funcion(nombre: str, argumentos: dict) -> dict | list:
    """Ejecuta la herramienta solicitada por Gemini."""
    logger.info("El modelo pidió %s(%s)", nombre, argumentos)

    funcion = FUNCIONES.get(nombre)

    if funcion is None:
        return {"error": f"Función desconocida: {nombre}"}

    try:
        return await funcion(**argumentos)

    except httpx.HTTPStatusError as error:
        logger.exception("El backend respondió con error")
        return {
            "error": (
                "El backend académico respondió con un error "
                f"HTTP {error.response.status_code}"
            )
        }

    except httpx.RequestError:
        logger.exception("No se pudo conectar con el backend académico")
        return {
            "error": (
                "No se pudo conectar con el backend académico. "
                "Verificá que Spring Boot esté iniciado."
            )
        }

    except Exception as error:
        logger.exception("Falló la herramienta %s", nombre)
        return {"error": f"No se pudo obtener el dato: {type(error).__name__}"}