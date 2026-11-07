from pathlib import Path
from src.ingestao import RAIZ, ingerir
import logging

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

for arquivo in sorted(Path(RAIZ / "data/raw").glob("*.csv")):
    try:
        resultado = ingerir(arquivo)
        print("OK      ", arquivo.name, "->", resultado.parent.name if resultado else "já ingerido")
    except Exception as e:
        print("FALHOU  ", arquivo.name, "->", e)