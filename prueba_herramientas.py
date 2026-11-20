"""
Prueba aislada de las herramientas, sin Telegram ni Gemini.
Llama a cada función directamente y muestra lo que devuelve.
"""

import asyncio  # permite ejecutar corrutinas desde un script
import json  # para mostrar los resultados con formato legible

from herramientas import ejecutar_funcion, obtener_feriados


async def main():
    # Casos normales: consultan la API real.
    print("--- Feriados de diciembre de 2026 ---")
    print(json.dumps(await obtener_feriados(2026, 12), ensure_ascii=False, indent=2))

    print("--- Próximos feriados del año ---")
    print(json.dumps(await obtener_feriados(solo_proximos=True), ensure_ascii=False, indent=2))

    # Casos de error: deben devolver un diccionario con la clave "error", no fallar.
    print("--- Año sin datos ---")
    print(await obtener_feriados(2030))
    print("--- Mes inválido ---")
    print(await obtener_feriados(2026, 13))

    # Despachador: debe devolver siempre un diccionario, incluso ante pedidos incorrectos.
    print("--- Despachador: pedido normal ---")
    print(await ejecutar_funcion("obtener_feriados", {"anio": 2026, "mes": 11}))
    print("--- Despachador: función que no existe ---")
    print(await ejecutar_funcion("funcion_inexistente", {}))
    print("--- Despachador: argumentos incorrectos ---")
    print(await ejecutar_funcion("obtener_feriados", {"anio": "abc"}))


asyncio.run(main())  # pone en marcha el bucle de eventos
