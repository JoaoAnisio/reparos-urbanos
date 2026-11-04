"""Verificações da silver contra o levantamento do escopo (lê a bronze real).

Uso:  python -m pytest tests/test_silver.py -v
"""
import pandas as pd
import pytest
from pandas.api.types import is_datetime64_any_dtype, is_float_dtype

from src.comum import ler_manifesto
from src.ingest import BRONZE, versao_vigente
from src.silver import _data_extracao, ler_trimestre

# Contagens da pergunta 3 de scripts/levantamento_escopo.py
ESPERADO = {
    "2024T3": 23279, "2024T4": 21431,
    "2025T1": 33384, "2025T2": 32494, "2025T3": 26693, "2025T4": 23297,
    "2026T1": 30720, "2026T2": 23220, "2026T3": 29962,
}
STATUS_VALIDOS = {"aberto", "finalizado", "cancelado"}
CANAIS_VALIDOS = {"portal", "mobile", "central", "chatbot", "outros"}
DATAS = ["data_abertura", "data_finalizacao", "data_extracao"]


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    """Lê os 9 trimestres UMA vez e compartilha com todos os testes do arquivo."""
    trimestres = sorted(p.name.split("=")[1] for p in BRONZE.glob("trimestre=*"))
    if not trimestres:
        pytest.skip("bronze vazia: rode python -m scripts.ingest_all antes")
    return pd.concat([ler_trimestre(t) for t in trimestres], ignore_index=True)


def test_reconciliacao_total(df):
    total = sum(ESPERADO.values())
    assert len(df) == total, f"total {len(df):,} != esperado {total:,}"


def test_contagem_por_trimestre(df):
    contagem = df["trimestre"].value_counts().to_dict()
    assert set(contagem) == set(ESPERADO), f"trimestres diferentes: {set(contagem) ^ set(ESPERADO)}"
    diferencas = {t: (contagem[t], n) for t, n in ESPERADO.items() if contagem[t] != n}
    assert not diferencas, f"divergências (obtido, esperado): {diferencas}"


def test_dominio_status_e_canal(df):
    assert df["status"].notna().all(), (
        f"{df['status'].isna().sum()} status nulos; brutos: {df.loc[df['status'].isna(), 'status_original'].unique()}")
    assert set(df["status"]) <= STATUS_VALIDOS, f"status inesperados: {set(df['status']) - STATUS_VALIDOS}"
    assert df["canal"].notna().all(), f"{df['canal'].isna().sum()} canais nulos"
    assert set(df["canal"]) <= CANAIS_VALIDOS, f"canais inesperados: {set(df['canal']) - CANAIS_VALIDOS}"


def test_tipos(df):
    for coluna in DATAS:
        assert is_datetime64_any_dtype(df[coluna]), f"{coluna} é {df[coluna].dtype}, esperado datetime"
    for coluna in ["lat", "lon"]:
        assert is_float_dtype(df[coluna]), f"{coluna} é {df[coluna].dtype}, esperado float"


def test_datas_sem_fuso(df):
    """Todas as datas no mesmo 'tipo' de tempo: misturar com e sem fuso quebra subtrações."""
    com_fuso = [c for c in DATAS if df[c].dt.tz is not None]
    assert not com_fuso, f"colunas com fuso horário: {com_fuso}"


def test_extracao_posterior_as_datas_do_arquivo(df):
    """A estimativa da extração é um limite inferior: nenhuma data do arquivo pode passar dela."""
    assert (df["data_abertura"] <= df["data_extracao"]).all(), "abertura posterior à extração"
    fim = df["data_finalizacao"].notna()
    assert (df.loc[fim, "data_finalizacao"] <= df.loc[fim, "data_extracao"]).all(), "finalização posterior à extração"


def test_extracao_anterior_a_ingestao():
    """Ninguém ingere um arquivo antes de ele existir."""
    pastas = list(BRONZE.glob("trimestre=*"))
    if not pastas:
        pytest.skip("bronze vazia: rode python -m scripts.ingest_all antes")
    for pasta in pastas:
        man = ler_manifesto(versao_vigente(pasta.name.split("=")[1]))
        ingerido = pd.Timestamp(man["ingerido_em"]).tz_localize(None)
        estimada = _data_extracao(man)  # a regra real da silver, não uma cópia dela
        assert estimada <= ingerido, f"{man['trimestre']}: extração {estimada} depois da ingestão {ingerido}"