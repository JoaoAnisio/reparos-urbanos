"""Gera data/silver/chamados.parquet e data/silver/rejeitados.parquet e imprime o resumo.

Uso:  python -m scripts.gerar_silver
"""
import logging

import numpy as np
import pandas as pd

from src.consolidacao import tabela_ocorrencias
from src.silver import SILVER, gerar_silver


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
pd.set_option("display.width", 200)


def resumir_ocorrencias(validos: pd.DataFrame) -> None:
    """Chamados × ocorrências, e ocorrências por tamanho, situação e reincidência."""
    ocorrencias = tabela_ocorrencias(validos)
    reincidencia = validos.groupby("id_ocorrencia")["numero_reincidencia"].first()
    soma = int(ocorrencias["qtd_chamados"].sum())
    assert soma == len(validos), f"soma de chamados por ocorrência ({soma:,}) != válidos ({len(validos):,})"

    print(f"\nChamados: {len(validos):,} | Ocorrências: {len(ocorrencias):,} | "
          f"{len(validos) / len(ocorrencias):.2f} chamados por ocorrência | soma confere: {soma:,}")
    tamanho = pd.cut(ocorrencias["qtd_chamados"], [0, 1, 2, 5, np.inf], labels=["1", "2", "3–5", "6+"])
    tabela = pd.DataFrame({"ocorrências": tamanho.value_counts(sort=False),
                           "chamados": ocorrencias["qtd_chamados"].groupby(tamanho, observed=False).sum()})
    print("Ocorrências por número de chamados:")
    print(tabela.to_string())
    print("Ocorrências por situação:", ocorrencias["situacao"].value_counts().to_dict())
    print("Ocorrências por numero_reincidencia:", reincidencia.value_counts().sort_index().to_dict())


def executar() -> None:
    validos, rejeitados = gerar_silver()
    total = len(validos) + len(rejeitados)
    print(f"\nVálidos: {len(validos):,} | Rejeitados: {len(rejeitados):,} | Total: {total:,}")

    print("\nRejeitados por motivo e trimestre (inclui trimestres sem nenhum rejeitado):")
    trimestres = sorted(set(validos["trimestre"]) | set(rejeitados["trimestre"]))
    tabela = pd.crosstab(rejeitados["motivo"], rejeitados["trimestre"]).reindex(columns=trimestres, fill_value=0)
    tabela["total"] = tabela.sum(axis=1)
    tabela.loc["total"] = tabela.sum()
    print(tabela.to_string())

    print("\nFlags nos válidos:")
    for coluna in ["flag_finalizado_sem_data", "flag_sem_subprefeitura", "flag_corredor",
                 "flag_repeticao", "flag_distrito_divisa", "flag_sem_votos"]:
        print(f"  {coluna}: {int(validos[coluna].sum()):,}")

    print("\nOrigem do distrito_final:", validos["origem_distrito"].value_counts(dropna=False).to_dict())
    print("Nível da inferência:", validos["nivel_distrito"].value_counts().to_dict())
    sem_sub = validos["flag_sem_subprefeitura"]
    print(f"Válidos sem subprefeitura: {int(sem_sub.sum()):,} "
          f"(sem distrito_final: {int((sem_sub & validos['distrito_final'].isna()).sum()):,}, "
          f"distrito_final fora da referência: {int((sem_sub & validos['distrito_final'].notna()).sum()):,})")

    resumir_ocorrencias(validos)

    print("\nTipos depois de ler o Parquet de volta:")
    for nome, original in [("chamados", validos), ("rejeitados", rejeitados)]:
        lido = pd.read_parquet(SILVER / f"{nome}.parquet")
        diferentes = {c: (str(original[c].dtype), str(lido[c].dtype))
                      for c in original.columns if original[c].dtype != lido[c].dtype}
        print(f"  {nome}: {'preservados' if not diferentes else f'MUDARAM {diferentes}'}")
    print(pd.read_parquet(SILVER / "chamados.parquet").dtypes.to_string())


if __name__ == "__main__":
    executar()
