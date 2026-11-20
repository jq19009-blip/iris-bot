"""
Flujo guiado de solicitud de constancia de alumno regular (/constancia).

Un ConversationHandler conduce al estudiante paso a paso:
  1. DESTINATARIO: elección desde teclado.
  2. NOMBRE: nombre y apellido completo del estudiante.
  3. LEGAJO: número de legajo universitario (validación numérica).
  4. FECHA: fecha en la que necesita presentar la constancia (interpretada con IA + salida estructurada).
  5. CONFIRMACION: resumen y confirmación o cancelación.

En cualquier estado, /cancelar interrumpe el trámite.
"""

import logging
from datetime import date
from pydantic import BaseModel, Field, ValidationError
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ChatAction
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db

logger = logging.getLogger("iris")

DESTINATARIO, NOMBRE, LEGAJO, FECHA, CONFIRMACION = range(5)

DESTINATARIOS = [
    "Obra social",
    "Empleador / Trabajo",
    "Boleto estudiantil",
    "Asignación familiar / ANSES",
    "Otro organismo",
]

DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


class FechaInterpretada(BaseModel):
    """Resultado validado que devuelve el modelo al interpretar una fecha."""
    entendida: bool = Field(description="true si el texto indica una fecha concreta; false si no.")
    fecha: str = Field(description="La fecha en formato AAAA-MM-DD, o cadena vacía si no se entendió.")


async def interpretar_fecha(cliente, modelo: str, texto: str) -> date | None:
    """Convierte una fecha escrita en lenguaje natural en un objeto date, o None."""
    hoy = date.today()
    instrucciones = (
        f"Hoy es {DIAS_SEMANA[hoy.weekday()]} {hoy.isoformat()}. "
        "Convertí la fecha que menciona el usuario al formato AAAA-MM-DD. "
        "Si el texto no indica una fecha concreta, respondé entendida=false."
    )
    interaccion = await cliente.aio.interactions.create(
        model=modelo,
        system_instruction=instrucciones,
        input=texto,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": FechaInterpretada.model_json_schema(),
        },
        store=False,
    )
    resultado = FechaInterpretada.model_validate_json(interaccion.output_text)
    if not resultado.entendida:
        return None
    return date.fromisoformat(resultado.fecha)


async def inicio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 0 (/constancia): muestra los posibles destinatarios."""
    context.user_data["constancia"] = {}
    teclado = ReplyKeyboardMarkup([[opcion] for opcion in DESTINATARIOS], one_time_keyboard=True)
    await update.message.reply_text(
        "Vamos a gestionar tu solicitud de Constancia de Alumno Regular.\n"
        "¿Ante qué entidad o para qué trámite la necesitás presentar?\n"
        "(Podés cancelar en cualquier momento con /cancelar)",
        reply_markup=teclado,
    )
    return DESTINATARIO


async def recibir_destinatario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 1: valida el destinatario seleccionado."""
    eleccion = update.message.text.strip()
    if eleccion not in DESTINATARIOS:
        await update.message.reply_text("Por favor, elegí una de las opciones del teclado.")
        return DESTINATARIO

    context.user_data["constancia"]["destinatario"] = eleccion
    await update.message.reply_text(
        "Perfecto. Escribí tu nombre y apellido completo tal como figura en tu DNI:",
        reply_markup=ReplyKeyboardRemove(),
    )
    return NOMBRE


async def recibir_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 2: valida el nombre completo."""
    nombre = update.message.text.strip()
    partes = [p for p in nombre.split() if len(p) >= 2]
    if len(partes) < 2 or any(ch.isdigit() for ch in nombre):
        await update.message.reply_text(
            "Ingresá tu nombre y apellido completos (sin números, al menos dos palabras)."
        )
        return NOMBRE

    context.user_data["constancia"]["nombre_completo"] = nombre
    await update.message.reply_text("Ingresá tu número de legajo universitario (solo dígitos, entre 4 y 8 números):")
    return LEGAJO


async def recibir_legajo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 3: valida el número de legajo."""
    legajo = update.message.text.strip()
    if not legajo.isdigit() or not (4 <= len(legajo) <= 8):
        await update.message.reply_text("El legajo debe contener solo números (entre 4 y 8 dígitos). Probá de nuevo:")
        return LEGAJO

    context.user_data["constancia"]["legajo"] = legajo
    await update.message.reply_text(
        "¿Para qué fecha necesitás tener la constancia? Podés escribirlo como quieras "
        '(por ejemplo: "mañana", "el próximo lunes" o "25 de noviembre"):'
    )
    return FECHA


async def recibir_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 4: interpreta la fecha con IA y verifica que no sea pasada."""
    await update.message.chat.send_action(ChatAction.TYPING)
    cliente = context.bot_data["cliente_gemini"]
    modelo = context.bot_data["modelo"]

    try:
        fecha = await interpretar_fecha(cliente, modelo, update.message.text)
    except (ValidationError, ValueError):
        fecha = None
    except Exception:
        logger.exception("Error al interpretar la fecha en /constancia")
        await update.message.reply_text("No pude procesar la fecha en este momento. Probá de nuevo.")
        return FECHA

    if fecha is None:
        await update.message.reply_text('No entendí la fecha. Probá, por ejemplo, con "el viernes 27".')
        return FECHA

    if fecha < date.today():
        await update.message.reply_text("Esa fecha ya pasó. Indicá una fecha actual o futura:")
        return FECHA

    datos = context.user_data["constancia"]
    datos["fecha_entrega"] = fecha.isoformat()

    teclado = ReplyKeyboardMarkup([["Confirmar", "Cancelar"]], one_time_keyboard=True)
    await update.message.reply_text(
        "Revisá los datos de tu solicitud:\n\n"
        f"- Destinatario: {datos['destinatario']}\n"
        f"- Estudiante: {datos['nombre_completo']}\n"
        f"- Legajo: {datos['legajo']}\n"
        f"- Fecha requerida: {DIAS_SEMANA[fecha.weekday()]} {fecha.strftime('%d/%m/%Y')}\n\n"
        "¿Confirmás la solicitud?",
        reply_markup=teclado,
    )
    return CONFIRMACION


async def confirmar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 5: guarda la solicitud en SQLite o la cancela."""
    respuesta = update.message.text.strip()
    if respuesta not in ("Confirmar", "Cancelar"):
        await update.message.reply_text("Elegí 'Confirmar' o 'Cancelar' en el teclado.")
        return CONFIRMACION

    datos = context.user_data.pop("constancia", {})
    if respuesta != "Confirmar":
        await update.message.reply_text(
            "Solicitud cancelada. ¿En qué más te puedo ayudar?",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    numero_tramite = await db.guardar_solicitud_constancia(
        update.effective_user.id,
        datos["nombre_completo"],
        datos["legajo"],
        datos["destinatario"],
        datos["fecha_entrega"],
    )
    await update.message.reply_text(
        f"Listo, tu solicitud quedó registrada con el número de trámite #{numero_tramite}.\n"
        "Recordá que la constancia tiene 30 días corridos de validez una vez emitida por Secretaría.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/cancelar: interrumpe el trámite en cualquier paso."""
    context.user_data.pop("constancia", None)
    await update.message.reply_text(
        "Trámite de constancia cancelado. ¿En qué más te puedo ayudar?",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


def crear_manejador() -> ConversationHandler:
    """Arma el ConversationHandler para registrar en bot.py."""
    texto = filters.TEXT & ~filters.COMMAND
    return ConversationHandler(
        entry_points=[CommandHandler("constancia", inicio)],
        states={
            DESTINATARIO: [MessageHandler(texto, recibir_destinatario)],
            NOMBRE: [MessageHandler(texto, recibir_nombre)],
            LEGAJO: [MessageHandler(texto, recibir_legajo)],
            FECHA: [MessageHandler(texto, recibir_fecha)],
            CONFIRMACION: [MessageHandler(texto, confirmar)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )
