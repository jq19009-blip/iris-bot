"""
Indexa la guía normativa de Iris: calcula los embeddings de cada sección y
los guarda en guia/indice.json. Ejecutar una vez y cada vez que cambie la guía.
"""

import asyncio
import logging
import os

from dotenv import load_dotenv
from google import genai

import rag

load_dotenv()
logging.basicConfig(format="%(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

cliente = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

cantidad = asyncio.run(rag.indexar(cliente))
print(f"Listo: {cantidad} fragmentos guardados en {rag.RUTA_INDICE}")
