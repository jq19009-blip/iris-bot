"""
Iris v6 - Asistente académica en Telegram (Hito 4).

- Responde con Gemini (Interactions API sin estado) y el prompt de prompts.py.
- Guarda el historial de cada usuario en SQLite (db.py).
- Análisis estructurado con Pydantic (/analizar) guardado en SQLite.
- Módulo avanzado 1 (RAG): búsqueda semántica en normativa del ITU (rag.py).
- Módulo avanzado 2 (Flujo guiado): solicitud de constancia de alumno regular
  paso a paso con manejo de estados (/constancia, constancias.py).
"""

import json
import logging
import os
from typing import Literal

from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import constancias
import db
import rag
from herramientas import DECLARACIONES, ejecutar_funcion
from prompts import PROMPT_SISTEMA

# --------------------------------------------------------------------------
# 1. Configuración
# --------------------------------------------------------------------------

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

MAX_MENSAJES_HISTORIAL = 20
MAX_VUELTAS_HERRAMIENTAS = 5
LIMITE_TELEGRAM = 4096

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("iris")

# --------------------------------------------------------------------------
# 2. Conexión con Gemini y salida estructurada
# --------------------------------------------------------------------------

cliente_gemini = genai.Client(api_key=GEMINI_API_KEY)


class AnalisisConsulta(BaseModel):
    """Esquema validado con Pydantic para clasificar consultas académicas."""
    categoria: Literal[
        "examenes",
        "tramites",
        "normativa",
        "cursado_materias",
        "otro",
    ] = Field(description="Categoría principal de la consulta académica.")
    urgencia: Literal["alta", "media", "baja"] = Field(
        description="Nivel de urgencia detectado en el mensaje del estudiante."
    )
    materia: str = Field(
        description="Nombre de la materia mencionada, o 'General' si no menciona ninguna."
    )
    resumen: str = Field(
        description="Resumen breve en una oración del pedido o duda del estudiante."
    )


async def analizar_consulta_estructurada(texto: str) -> AnalisisConsulta:
    """Envía un texto a Gemini y devuelve un objeto AnalisisConsulta validado."""
    instrucciones = (
        "Sos un clasificador académico del ITU UNCuyo. Analizá el mensaje del "
        "estudiante y devolvé su categoría, urgencia, materia involucrada y un "
        "resumen breve en español."
    )
    interaccion = await cliente_gemini.aio.interactions.create(
        model=GEMINI_MODEL,
        system_instruction=instrucciones,
        input=texto,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": AnalisisConsulta.model_json_schema(),
        },
        store=False,
    )
    return AnalisisConsulta.model_validate_json(interaccion.output_text)


# --------------------------------------------------------------------------
# 3. Preparación de entrada y ciclo de function calling
# --------------------------------------------------------------------------

def armar_entrada(
    historial: list[tuple[str, str]],
    contenido_nuevo: list[dict],
) -> list[dict]:
    """
    Convierte el historial guardado en la lista de pasos (steps) que espera
    la Interactions API y agrega al final el contenido nuevo en bloques.
    """
    tipo_de_paso = {"user": "user_input", "model": "model_output"}
    pasos = [
        {"type": tipo_de_paso[rol], "content": [{"type": "text", "text": texto}]}
        for rol, texto in historial
    ]
    pasos.append({"type": "user_input", "content": contenido_nuevo})
    return pasos


async def consultar_gemini(
    historial: list[tuple[str, str]],
    contenido_nuevo: list[dict],
    registro: list[str] | None = None,
) -> str:
    """
    Envía la conversación a Gemini y resuelve el ciclo de function calling.
    Si se pasa una lista en `registro`, anota allí cada herramienta pedida.
    """
    entrada = armar_entrada(historial, contenido_nuevo)

    for vuelta in range(MAX_VUELTAS_HERRAMIENTAS):
        interaccion = await cliente_gemini.aio.interactions.create(
            model=GEMINI_MODEL,
            system_instruction=PROMPT_SISTEMA,
            input=entrada,
            tools=DECLARACIONES,
            store=False,
        )

        pasos_modelo = interaccion.steps or []
        llamadas = [paso for paso in pasos_modelo if paso.type == "function_call"]

        if not llamadas:
            return interaccion.output_text or "No se me ocurrió nada para responder 🤔"

        for paso in pasos_modelo:
            entrada.append(paso.model_dump())

        for llamada in llamadas:
            if registro is not None:
                registro.append(llamada.name)
            resultado = await ejecutar_funcion(llamada.name, llamada.arguments)
            entrada.append(
                {
                    "type": "function_result",
                    "call_id": llamada.id,
                    "name": llamada.name,
                    "result": [
                        {"type": "text", "text": json.dumps(resultado, ensure_ascii=False)}
                    ],
                }
            )

    logger.warning(
        "Se alcanzó el máximo de %d vueltas de herramientas", MAX_VUELTAS_HERRAMIENTAS
    )
    return "No pude completar la consulta. ¿Podés reformular la pregunta? 🙏"


def describir_error(error: Exception) -> str:
    """Traduce un error de la API a un mensaje comprensible para el usuario."""
    codigo = getattr(error, "status_code", None)
    if codigo == 429:
        return "Estoy recibiendo demasiadas consultas. Probá de nuevo en un minuto, por favor. ⏳"
    if codigo in (401, 403):
        return "Tengo un problema de configuración. Avisale a quien me administra. 🔧"
    return "Tuve un problema para pensar la respuesta. ¿Me lo preguntás de nuevo? 🙏"


# --------------------------------------------------------------------------
# 4. Handlers
# --------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /start."""
    try:
        datos = await ejecutar_funcion("obtener_datos_estudiante", {})
        nombre = datos.get("nombre", "estudiante") if isinstance(datos, dict) else "estudiante"
        logger.info("Nuevo /start de %s (Telegram ID: %s)", nombre, update.effective_user.id)
        await update.message.reply_text(
            f"¡Hola, {nombre}! Soy Iris, tu asistente académica. 🎓\n\n"
            "Contame qué necesitás saber: normativa del ITU, plan de estudios, "
            "exámenes, feriados o solicitud de constancia de alumno regular.\n\n"
            "Escribí /help para ver todo lo que sé hacer."
        )
    except Exception:
        logger.exception("Error al obtener los datos del estudiante")
        await update.message.reply_text(
            "¡Hola! Soy Iris, tu asistente académica. 🎓\n\n"
            "Contame qué necesitás saber. Escribí /help para ver mis comandos."
        )


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /help."""
    await update.message.reply_text(
        "Estos son mis comandos:\n\n"
        "/start - Presentación de Iris\n"
        "/help - Esta ayuda\n"
        "/constancia - Solicitar constancia de alumno regular paso a paso\n"
        "/cancelar - Cancelar una solicitud de constancia en curso\n"
        "/analizar <consulta> - Clasificar y registrar una consulta académica\n"
        "/olvidar - Borra nuestra conversación y empezamos de cero\n\n"
        "También podés preguntarme en texto libre sobre el reglamento del ITU, "
        "correlatividades, mesas de examen, feriados o tu estado académico."
    )


async def olvidar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /olvidar: borra el historial del usuario."""
    borrados = await db.borrar_historial(update.effective_user.id)
    logger.info("Usuario %s borró %d mensajes", update.effective_user.id, borrados)
    await update.message.reply_text("Listo, empezamos de cero. ¿En qué te puedo ayudar? 🙂")


async def analizar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Comando /analizar <texto>: usa salida estructurada con Pydantic para
    clasificar la consulta académica, guardarla en SQLite y mostrar el resultado.
    """
    texto = " ".join(context.args).strip()
    if not texto:
        await update.message.reply_text(
            "Escribí el mensaje que querés analizar después del comando.\n"
            "Ejemplo: /analizar Necesito saber si promociono Programación III con 7"
        )
        return

    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        resultado = await analizar_consulta_estructurada(texto)
    except Exception as error:
        logger.exception("Error en análisis estructurado (/analizar)")
        await update.message.reply_text(describir_error(error))
        return

    registro_id = await db.guardar_consulta_estructurada(
        update.effective_user.id,
        resultado.categoria,
        resultado.urgencia,
        resultado.materia,
        resultado.resumen,
    )

    logger.info(
        "Análisis estructurado #%d guardado | categoria=%s | urgencia=%s | materia=%s",
        registro_id,
        resultado.categoria,
        resultado.urgencia,
        resultado.materia,
    )

    await update.message.reply_text(
        f"Análisis académico registrado (#{registro_id}):\n\n"
        f"- Categoría: {resultado.categoria}\n"
        f"- Urgencia: {resultado.urgencia}\n"
        f"- Materia: {resultado.materia}\n"
        f"- Resumen: {resultado.resumen}"
    )


async def procesar_mensaje(
    update: Update,
    contenido: list[dict],
    texto_para_historial: str,
) -> None:
    """Pasos comunes: recupera historial, consulta Gemini, guarda y responde."""
    user_id = update.effective_user.id
    await update.message.chat.send_action(ChatAction.TYPING)

    historial = await db.obtener_historial(user_id, MAX_MENSAJES_HISTORIAL)

    try:
        respuesta = await consultar_gemini(historial, contenido)
    except Exception as error:
        logger.exception("Error al consultar a Gemini")
        await update.message.reply_text(describir_error(error))
        return

    await db.guardar_intercambio(user_id, texto_para_historial, respuesta)

    for inicio in range(0, len(respuesta), LIMITE_TELEGRAM):
        await update.message.reply_text(respuesta[inicio : inicio + LIMITE_TELEGRAM])


async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde un mensaje de texto libre."""
    texto = update.message.text
    logger.info("Mensaje de %s: %s", update.effective_user.id, texto)
    await procesar_mensaje(update, [{"type": "text", "text": texto}], texto)


async def manejar_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registra en la terminal los errores no previstos."""
    logger.error("Error no previsto", exc_info=context.error)


# --------------------------------------------------------------------------
# 5. Arranque
# --------------------------------------------------------------------------

async def al_iniciar(app: Application) -> None:
    """Se ejecuta una sola vez antes de comenzar a recibir mensajes."""
    await db.inicializar()
    logger.info("Base de datos lista (%s).", db.RUTA_DB)
    rag.inicializar(cliente_gemini)


def main() -> None:
    faltantes = [
        nombre
        for nombre, valor in [
            ("TELEGRAM_TOKEN", TELEGRAM_TOKEN),
            ("GEMINI_API_KEY", GEMINI_API_KEY),
        ]
        if not valor
    ]
    if faltantes:
        raise SystemExit(f"Faltan variables en el .env: {', '.join(faltantes)}")

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(al_iniciar).build()

    app.bot_data["cliente_gemini"] = cliente_gemini
    app.bot_data["modelo"] = GEMINI_MODEL

    # 1. Flujo guiado PRIMERO para capturar las respuestas paso a paso.
    app.add_handler(constancias.crear_manejador())

    # 2. Comandos generales.
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", ayuda))
    app.add_handler(CommandHandler("olvidar", olvidar))
    app.add_handler(CommandHandler("analizar", analizar))

    # 3. Texto libre al final.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    app.add_error_handler(manejar_error)

    logger.info("Iris v6 en línea con el modelo %s.", GEMINI_MODEL)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
