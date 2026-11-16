"""
Iris v3 - Asistente académica en Telegram.

- Responde con Gemini (Interactions API sin estado) y el prompt de prompts.py.
- Guarda el historial de cada usuario en SQLite (db.py) y se lo envía al
  modelo en cada consulta, de modo que la conversación tiene memoria.
- Comandos: /start, /help y /olvidar (borra la conversación del usuario).
"""

import logging  # registro de eventos en la terminal
import os  # acceso a las variables de entorno

from dotenv import load_dotenv  # lee el archivo .env
from google import genai  # SDK oficial de Gemini
from telegram import Update  # representa cada novedad recibida de Telegram
from telegram.constants import ChatAction  # acciones de chat, como "escribiendo..."
from telegram.ext import (
    Application,  # motor del bot: recibe y distribuye updates
    CommandHandler,  # handler para comandos (/start, /help, /olvidar)
    ContextTypes,  # tipo del parámetro context de los handlers
    MessageHandler,  # handler para mensajes que no son comandos
    filters,  # filtros para seleccionar qué mensajes atender
)

import db  # módulo propio: acceso a la base SQLite
from prompts import PROMPT_SISTEMA  # prompt de sistema definido en prompts.py

# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------

# Carga en el entorno las variables del archivo .env.
load_dotenv()

# Lectura de las variables. os.getenv devuelve None si la variable no existe.
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Leer el modelo del .env permite cambiarlo sin modificar el código.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Cantidad de mensajes anteriores que se envían al modelo en cada consulta
# (20 mensajes = 10 preguntas y sus respuestas).
MAX_MENSAJES_HISTORIAL = 20

# Longitud máxima de un mensaje de Telegram, en caracteres.
LIMITE_TELEGRAM = 4096

# Formato de cada línea de registro: fecha y hora | nivel | origen | mensaje.
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
# httpx registra cada consulta HTTP, y esas líneas incluyen el token del bot.
# Se limita a advertencias para no saturar la consola ni exponer el token.
logging.getLogger("httpx").setLevel(logging.WARNING)

# Registrador propio del bot; sus mensajes aparecen con el nombre "iris".
logger = logging.getLogger("iris")

# --------------------------------------------------------------------------
# Conexión con Gemini
# --------------------------------------------------------------------------

# Se crea un único cliente para todo el programa. Guarda la clave de API y
# administra las conexiones HTTP con los servidores de Google.
cliente_gemini = genai.Client(api_key=GEMINI_API_KEY)


def armar_entrada(historial: list[tuple[str, str]], mensaje_nuevo: str) -> list[dict]:
    """
    Convierte el historial guardado en la lista de pasos (steps) que espera
    la Interactions API y agrega al final el mensaje nuevo del usuario.
    """
    # Equivalencia entre el rol guardado en la base y el tipo de paso de la API.
    tipo_de_paso = {"user": "user_input", "model": "model_output"}

    # Un diccionario por cada fila del historial. El contenido es una lista
    # de bloques; aquí, un único bloque de texto.
    pasos = [
        {"type": tipo_de_paso[rol], "content": [{"type": "text", "text": texto}]}
        for rol, texto in historial
    ]

    # El último paso es siempre el mensaje que el usuario acaba de enviar.
    pasos.append(
        {"type": "user_input", "content": [{"type": "text", "text": mensaje_nuevo}]}
    )
    return pasos


async def consultar_gemini(historial: list[tuple[str, str]], mensaje: str) -> str:
    """Envía a Gemini la conversación completa y devuelve el texto de la respuesta."""
    # .aio accede a la versión asíncrona del cliente; por eso lleva await.
    # Mientras se espera la respuesta, el bot puede atender a otros usuarios.
    interaccion = await cliente_gemini.aio.interactions.create(
        model=GEMINI_MODEL,  # nombre del modelo, leído del .env
        system_instruction=PROMPT_SISTEMA,  # personalidad y reglas de Iris
        input=armar_entrada(historial, mensaje),  # conversación completa
        store=False,  # la memoria la administra el bot, no Google
    )
    # Si el texto llega vacío, se devuelve un mensaje alternativo para que
    # el bot nunca envíe una respuesta en blanco.
    return interaccion.output_text or "No se me ocurrió nada para responder 🤔"


def describir_error(error: Exception) -> str:
    """Traduce un error de la API a un mensaje comprensible para el usuario."""
    # Los errores HTTP de la API traen el código en el atributo status_code.
    # getattr devuelve None si el error no tiene ese atributo.
    codigo = getattr(error, "status_code", None)

    if codigo == 429:  # se superó la cuota de consultas
        return "Estoy recibiendo demasiadas consultas. Probá de nuevo en un minuto, por favor. ⏳"
    if codigo in (401, 403):  # clave inválida o sin permiso
        return "Tengo un problema de configuración. Avisale a quien me administra. 🔧"
    # Cualquier otro caso: falla de red, error del servicio, modelo inexistente.
    return "Tuve un problema para pensar la respuesta. ¿Me lo preguntás de nuevo? 🙏"


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /start."""
    nombre = update.effective_user.first_name or "estudiante"
    logger.info("Nuevo /start de %s (id %s)", nombre, update.effective_user.id)
    await update.message.reply_text(
        f"¡Hola, {nombre}! Soy Iris, tu asistente académica. 🎓\n\n"
        "Contame qué necesitás saber: fechas de entrega, exámenes, "
        "calendario académico o trámites de la facultad.\n\n"
        "Escribí /help para ver lo que sé hacer."
    )


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /help."""
    await update.message.reply_text(
        "Estos son mis comandos:\n\n"
        "/start - Presentación de Iris\n"
        "/help - Esta ayuda\n"
        "/olvidar - Borra nuestra conversación y empezamos de cero\n\n"
        "Y, sobre todo, podés escribirme tus consultas sobre la vida "
        "académica de la facultad. Me acuerdo de lo que hablamos."
    )


async def olvidar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /olvidar: borra el historial del usuario."""
    borrados = await db.borrar_historial(update.effective_user.id)
    logger.info("Usuario %s borró %d mensajes", update.effective_user.id, borrados)
    await update.message.reply_text("Listo, empezamos de cero. ¿En qué te puedo ayudar? 🙂")


async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde con Gemini, teniendo en cuenta la conversación previa."""
    user_id = update.effective_user.id  # identifica de quién es la conversación
    texto = update.message.text
    logger.info("Mensaje de %s: %s", user_id, texto)

    # Muestra "escribiendo..." en el chat mientras se prepara la respuesta.
    await update.message.chat.send_action(ChatAction.TYPING)

    # Paso 1: recuperar lo que ya se habló con este usuario.
    historial = await db.obtener_historial(user_id, MAX_MENSAJES_HISTORIAL)

    # Paso 2: consultar al modelo con el historial más el mensaje nuevo.
    try:
        respuesta = await consultar_gemini(historial, texto)
    except Exception as error:
        logger.error("Error al consultar a Gemini: %s", error)
        await update.message.reply_text(describir_error(error))
        # Si la consulta falló, no se guarda nada: así el historial nunca
        # queda con una pregunta sin su respuesta.
        return

    # Paso 3: guardar la pregunta y la respuesta para la próxima consulta.
    await db.guardar_intercambio(user_id, texto, respuesta)

    # Si la respuesta supera el límite de Telegram, se envía en partes.
    for inicio in range(0, len(respuesta), LIMITE_TELEGRAM):
        await update.message.reply_text(respuesta[inicio : inicio + LIMITE_TELEGRAM])


async def manejar_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registra en la terminal los errores no previstos."""
    logger.error("Error no previsto", exc_info=context.error)


# --------------------------------------------------------------------------
# Arranque
# --------------------------------------------------------------------------


async def al_iniciar(app: Application) -> None:
    """Se ejecuta una sola vez, antes de comenzar a recibir mensajes."""
    # Es una corrutina porque inicializar la base requiere await; por eso
    # no puede llamarse directamente desde main(), que es síncrona.
    await db.inicializar()
    logger.info("Base de datos lista (%s).", db.RUTA_DB)


def main() -> None:
    # Lista con los nombres de las variables obligatorias que faltan en el .env.
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

    # post_init registra una corrutina que se ejecuta al arrancar, dentro del
    # bucle de eventos, antes de procesar el primer mensaje.
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(al_iniciar).build()

    # Registro de handlers. El orden importa: se usa el primero que coincide.
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", ayuda))
    app.add_handler(CommandHandler("olvidar", olvidar))
    # Texto que no sea comando: lo atiende responder.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    app.add_error_handler(manejar_error)

    logger.info("Iris v3 en línea con el modelo %s.", GEMINI_MODEL)
    # Polling: el bot consulta a Telegram de forma continua si hay mensajes nuevos.
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
