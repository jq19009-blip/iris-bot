"""
RAG (Retrieval-Augmented Generation): búsqueda semántica en normativa del ITU.

Flujo:
  1. Indexación (una sola vez, con indexar_guia.py): el documento normativo se
     divide en fragmentos por sección (## ...) y cada uno se convierte en un
     vector (embedding) guardado en guia/indice.json.
  2. Búsqueda (en cada consulta): la pregunta se convierte en un vector y se
     recuperan los fragmentos más parecidos mediante similitud coseno.
"""

import json
import logging
import numpy as np
from google.genai import types

logger = logging.getLogger("iris")

RUTA_GUIA = "guia/reglamento_itu.md"
RUTA_INDICE = "guia/indice.json"
MODELO_EMBEDDINGS = "gemini-embedding-2"
DIMENSION = 768
UMBRAL_SIMILITUD = 0.35

_cliente = None
_fragmentos: list[dict] = []
_matriz: np.ndarray | None = None


def leer_fragmentos(ruta: str = RUTA_GUIA) -> list[dict]:
    """Divide la guía en fragmentos: uno por cada título de nivel 2 (## ...)."""
    with open(ruta, encoding="utf-8") as archivo:
        contenido = archivo.read()

    fragmentos = []
    for seccion in contenido.split("\n## ")[1:]:
        titulo, _, cuerpo = seccion.partition("\n")
        fragmentos.append({"titulo": titulo.strip(), "texto": cuerpo.strip()})
    return fragmentos


async def obtener_embedding(cliente, texto: str) -> list[float]:
    """Convierte un texto en un vector de DIMENSION números."""
    respuesta = await cliente.aio.models.embed_content(
        model=MODELO_EMBEDDINGS,
        contents=texto,
        config=types.EmbedContentConfig(output_dimensionality=DIMENSION),
    )
    return respuesta.embeddings[0].values


async def indexar(cliente) -> int:
    """Calcula el vector de cada fragmento y guarda el índice en JSON."""
    fragmentos = leer_fragmentos()
    for fragmento in fragmentos:
        texto = f"title: {fragmento['titulo']} | text: {fragmento['texto']}"
        fragmento["vector"] = await obtener_embedding(cliente, texto)
        logger.info("Indexado: %s", fragmento["titulo"])

    with open(RUTA_INDICE, "w", encoding="utf-8") as archivo:
        json.dump(fragmentos, archivo, ensure_ascii=False)
    return len(fragmentos)


def _normalizar_filas(matriz: np.ndarray) -> np.ndarray:
    """Divide cada vector por su norma L2 para que tengan longitud 1."""
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    return matriz / normas


def inicializar(cliente) -> None:
    """Carga el índice en memoria al arrancar el bot."""
    global _cliente, _fragmentos, _matriz
    _cliente = cliente
    try:
        with open(RUTA_INDICE, encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except FileNotFoundError:
        logger.warning("No existe %s: ejecutá python indexar_guia.py", RUTA_INDICE)
        return

    _fragmentos = [{"titulo": d["titulo"], "texto": d["texto"]} for d in datos]
    _matriz = _normalizar_filas(np.array([d["vector"] for d in datos]))
    logger.info("Guía normativa cargada: %d fragmentos.", len(_fragmentos))


async def buscar(consulta: str, cantidad: int = 3) -> list[dict]:
    """Devuelve los fragmentos normativos más parecidos a la consulta."""
    if _matriz is None:
        raise RuntimeError("La guía normativa no está indexada. Ejecutá python indexar_guia.py")

    vector = np.array(
        await obtener_embedding(_cliente, f"task: search result | query: {consulta}")
    )
    vector = vector / np.linalg.norm(vector)

    similitudes = _matriz @ vector
    mejores = np.argsort(similitudes)[::-1][:cantidad]

    logger.info(
        "Búsqueda RAG '%s': %s",
        consulta,
        [(_fragmentos[i]["titulo"], round(float(similitudes[i]), 2)) for i in mejores],
    )

    return [
        {**_fragmentos[i], "similitud": round(float(similitudes[i]), 3)}
        for i in mejores
        if similitudes[i] >= UMBRAL_SIMILITUD
    ]
