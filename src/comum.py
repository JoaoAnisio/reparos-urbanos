"""Funções compartilhadas entre as camadas (bronze, silver, scripts)."""
import json
import unicodedata
from pathlib import Path

MANIFESTO = "_manifest.json"


def normalizar(texto: str) -> str:
    """'Data de Finalização' -> 'data de finalizacao' (sem acento, minúsculo, espaços simples)."""
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def ler_manifesto(pasta: Path) -> dict:
    """Lê o _manifest.json de uma pasta de versão da bronze."""
    return json.loads((pasta / MANIFESTO).read_text(encoding="utf-8"))