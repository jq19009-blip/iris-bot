"""
Herramientas de Iris: funciones que Gemini puede pedir que se ejecuten.

Incluye:
- Consulta de feriados nacionales argentinos.
- Consulta del backend académico local de Spring Boot.
- Búsqueda semántica (RAG) en la normativa y planes de estudio del ITU UNCuyo.
"""

import logging
import os
from datetime import date, datetime, timedelta, timezone

import httpx
import rag

logger = logging.getLogger("iris")

TIEMPO_ESPERA = 10

URL_FERIADOS = "https://api.argentinadatos.com/v1/feriados"
ANIO_MINIMO = 2016
ANIO_MAXIMO = 2026

URL_API_ACADEMICA = os.getenv(
    "API_ACADEMICA_URL",
    "http://localhost:8080/api/estudiante",
)

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


async def buscar_en_normativa(consulta: str) -> dict:
    """Busca en la guía normativa del ITU los fragmentos relacionados con la consulta (RAG)."""
    resultados = await rag.buscar(consulta)
    if not resultados:
        return {
            "resultados": [],
            "aviso": "La documentación normativa cargada no contiene información sobre esta consulta.",
        }
    return {"resultados": resultados}


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


async def _consultar_api_academica(recurso: str = "") -> dict | list:
    url = f"{URL_API_ACADEMICA}/{recurso}" if recurso else URL_API_ACADEMICA
    async with httpx.AsyncClient(timeout=TIEMPO_ESPERA) as cliente_http:
        respuesta = await cliente_http.get(url)
        respuesta.raise_for_status()
        return respuesta.json()


async def obtener_datos_estudiante() -> dict:
    return await _consultar_api_academica()


async def obtener_materias_carrera() -> list:
    return await _consultar_api_academica("materias")


async def obtener_materias_inscriptas() -> list:
    return await _consultar_api_academica("inscriptas")


async def obtener_materias_aprobadas() -> list:
    return await _consultar_api_academica("aprobadas")


async def obtener_materias_desaprobadas() -> list:
    return await _consultar_api_academica("desaprobadas")


async def obtener_materias_pendientes() -> list:
    return await _consultar_api_academica("pendientes")


async def obtener_notas_academicas() -> list:
    return await _consultar_api_academica("notas")


async def obtener_historial_academico() -> list:
    return await _consultar_api_academica("historial")


async def obtener_examenes() -> list:
    return await _consultar_api_academica("examenes")


DECLARACIONES = [
    {
        "type": "function",
        "name": "buscar_en_normativa",
        "description": (
            "Busca en los documentos institucionales, planes de estudio y reglamentos "
            "del ITU UNCuyo información sobre regularidad, promoción directa, mesas de examen, "
            "escala de calificaciones, correlatividades, equivalencias, justificación de "
            "inasistencias, Práctica Profesional Supervisada (PPS) y constancias. "
            "Usala SIEMPRE que el usuario pregunte sobre reglas, requisitos, porcentajes "
            "de asistencia, notas mínimas o plan de estudios de la carrera."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "consulta": {
                    "type": "string",
                    "description": (
                        "Qué buscar en la normativa, en pocas palabras. "
                        "Por ejemplo: 'requisitos promoción directa' o 'correlatividades y PPS'."
                    ),
                },
            },
            "required": ["consulta"],
        },
    },
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
                    "description": "Mes de 1 a 12 para consultar solo los feriados de ese mes.",
                },
                "solo_proximos": {
                    "type": "boolean",
                    "description": "Usar true para consultar solamente los feriados futuros.",
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
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "obtener_materias_carrera",
        "description": "Obtiene todas las materias incluidas en el plan de estudios de la carrera del estudiante.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "obtener_materias_inscriptas",
        "description": "Obtiene las materias que el estudiante está cursando actualmente.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "obtener_materias_aprobadas",
        "description": "Obtiene las materias aprobadas por el estudiante, incluyendo notas finales y fechas de aprobación.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "obtener_materias_desaprobadas",
        "description": "Obtiene las materias desaprobadas por el estudiante, incluyendo notas finales y fechas de resultado.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "obtener_materias_pendientes",
        "description": "Obtiene las materias que el estudiante todavía no cursó ni aprobó.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "obtener_notas_academicas",
        "description": "Obtiene todas las notas finales registradas para el estudiante.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "obtener_historial_academico",
        "description": "Obtiene el historial académico completo: materias aprobadas, desaprobadas e inscriptas actualmente.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "obtener_examenes",
        "description": (
            "Obtiene los exámenes del estudiante ordenados por fecha y horario. "
            "Cada examen incluye materia, fecha, horario, tipo, estado y nota."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
]

FUNCIONES = {
    "buscar_en_normativa": buscar_en_normativa,
    "obtener_feriados": obtener_feriados,
    "obtener_datos_estudiante": obtener_datos_estudiante,
    "obtener_materias_carrera": obtener_materias_carrera,
    "obtener_materias_inscriptas": obtener_materias_inscriptas,
    "obtener_materias_aprobadas": obtener_materias_aprobadas,
    "obtener_materias_desaprobadas": obtener_materias_desaprobadas,
    "obtener_materias_pendientes": obtener_materias_pendientes,
    "obtener_notas_academicas": obtener_notas_academicas,
    "obtener_historial_academico": obtener_historial_academico,
    "obtener_examenes": obtener_examenes,
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
            "error": f"El backend académico respondió con un error HTTP {error.response.status_code}"
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
