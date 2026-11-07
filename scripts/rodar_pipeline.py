"""Roda a pipeline inteira com um comando: bronze -> silver -> gold (dbt) -> previsão.

Uso:  python -m scripts.rodar_pipeline      (ou: make pipeline)

Cada etapa registra início, fim, duração e as contagens. Qualquer falha interrompe a pipeline:
uma etapa nunca roda sobre o resultado incompleto da anterior.
"""
import json
import logging
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from scripts import prever
from src.ingestao import RAIZ, ingerir
from src.silver import gerar_silver

DBT = RAIZ / "dbt_reparos"
GOLD = RAIZ / "data" / "gold"

log = logging.getLogger("pipeline")


@contextmanager
def etapa(nome: str):
    log.info("▶ %s: início", nome)
    inicio = time.perf_counter()
    yield
    log.info("✔ %s: fim (%.1f s)", nome, time.perf_counter() - inicio)


def ingerir_raw() -> None:
    arquivos = sorted((RAIZ / "data" / "raw").glob("*.csv"))
    if not arquivos:
        raise FileNotFoundError("Nenhum CSV em data/raw/ (ver data/README.md).")
    criadas = 0
    for arquivo in arquivos:
        if ingerir(arquivo) is not None:   # ValueError (versão antiga, trimestres misturados) interrompe
            criadas += 1
    log.info("  %d arquivos: %d versões novas, %d já ingeridos", len(arquivos), criadas, len(arquivos) - criadas)


def rodar_dbt(*argumentos: str) -> None:
    GOLD.mkdir(parents=True, exist_ok=True)          # o DuckDB não cria a pasta do banco
    dbt = Path(sys.executable).with_name("dbt")       # o dbt do mesmo ambiente virtual
    subprocess.run([str(dbt), *argumentos, "--profiles-dir", "."], cwd=DBT, check=True)
    resultados = json.loads((DBT / "target" / "run_results.json").read_text(encoding="utf-8"))["results"]
    contagem = {}
    for r in resultados:
        contagem[r["status"]] = contagem.get(r["status"], 0) + 1
    log.info("  dbt %s: %s", argumentos[0], contagem)


def executar() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
    inicio = time.perf_counter()
    with etapa("bronze (ingestão de data/raw/)"):
        ingerir_raw()
    with etapa("silver (validação, geo, consolidação)"):
        validos, rejeitados = gerar_silver()
        log.info("  %d válidos, %d rejeitados, %d ocorrências",
                 len(validos), len(rejeitados), validos["id_ocorrencia"].nunique())
    with etapa("gold (dbt seed + dbt build)"):
        rodar_dbt("seed")
        rodar_dbt("build")
    with etapa("previsão"):
        prever.executar()
    log.info("Pipeline concluída em %.1f s", time.perf_counter() - inicio)


if __name__ == "__main__":
    executar()
