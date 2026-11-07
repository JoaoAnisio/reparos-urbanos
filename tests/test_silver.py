"""Verificações da silver contra o levantamento do escopo (lê a bronze real).

Uso:  python -m pytest tests/test_silver.py -v

Sem bronze (ex.: CI), o arquivo inteiro é pulado. Os testes "contrato" verificam premissas sobre a
fonte: não tratam registros (isso é papel das REGRAS da silver), avisam quando a fonte muda.
"""
import pandas as pd
import pytest
from pandas.api.types import is_datetime64_any_dtype, is_float_dtype

from src.comum import ler_manifesto
from src.ingestao import BRONZE, versao_vigente
from src.silver import SILVER, _data_extracao, ler_silver, ler_trimestre

# Contagens da pergunta 3 de scripts/levantamento_escopo.py
ESPERADO = {
    "2024T3": 23279, "2024T4": 21431,
    "2025T1": 33384, "2025T2": 32494, "2025T3": 26693, "2025T4": 23297,
    "2026T1": 30720, "2026T2": 23220, "2026T3": 29962,
}
STATUS_VALIDOS = {"aberto", "finalizado", "cancelado"}
CANAIS_VALIDOS = {"portal", "mobile", "central", "chatbot", "outros"}
DATAS = ["data_abertura", "data_finalizacao", "data_extracao"]

pytestmark = pytest.mark.skipif(not any(BRONZE.glob("trimestre=*")),
                                reason="bronze ausente (ex.: CI); rode a ingestão para testar")


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    """Lê os 9 trimestres UMA vez e compartilha com todos os testes do arquivo."""
    trimestres = sorted(p.name.split("=")[1] for p in BRONZE.glob("trimestre=*"))
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


def test_contrato_aberto_sem_finalizacao(df):
    """Na fonte, chamado aberto (ou em andamento) nunca traz data de finalização."""
    com_data = df.loc[(df["status"] == "aberto") & df["data_finalizacao"].notna(), "trimestre"]
    assert com_data.empty, f"abertos com finalização por trimestre: {com_data.value_counts().to_dict()}"


def test_contrato_cancelado_com_finalizacao(df):
    """Na fonte, o cancelamento sempre é registrado com data de finalização."""
    sem_data = df.loc[(df["status"] == "cancelado") & df["data_finalizacao"].isna(), "trimestre"]
    assert sem_data.empty, f"cancelados sem finalização por trimestre: {sem_data.value_counts().to_dict()}"


def test_extracao_anterior_a_ingestao():
    """Ninguém ingere um arquivo antes de ele existir."""
    for pasta in BRONZE.glob("trimestre=*"):
        man = ler_manifesto(versao_vigente(pasta.name.split("=")[1]))
        ingerido = pd.Timestamp(man["ingerido_em"]).tz_localize(None)
        estimada = _data_extracao(man)  # a regra real da silver, não uma cópia dela
        assert estimada <= ingerido, f"{man['trimestre']}: extração {estimada} depois da ingestão {ingerido}"


def test_parquet_gravado_reconcilia():
    """Confere o que gerar_silver GRAVOU (não só o que ler_trimestre lê), via manifesto da silver."""
    if not (SILVER / "chamados.parquet").exists():
        pytest.skip("silver ainda não gerada: rode python -m scripts.gerar_silver")
    validos, rejeitados, manifesto = ler_silver()  # recusa silver sem manifesto ou inconsistente
    assert len(validos) + len(rejeitados) == sum(ESPERADO.values())
    assert sum(manifesto["rejeitados_por_motivo"].values()) == len(rejeitados)
    assert set(manifesto["versoes_bronze"]) == set(ESPERADO), "silver gerada com outros trimestres"
    vigentes = {t: versao_vigente(t).name.split("=")[1] for t in ESPERADO}
    assert manifesto["versoes_bronze"] == vigentes, "silver desatualizada: rode python -m scripts.gerar_silver"

def test_silver_gravada_inclui_o_geo_e_seus_parametros():
    """O gerar_silver grava as colunas do geo e registra na linhagem os parâmetros usados."""
    from src import consolidacao, geo
    from src.silver import ESQUEMA_VALIDADO

    if not (SILVER / "chamados.parquet").exists():
        pytest.skip("silver ainda não gerada: rode python -m scripts.gerar_silver")
    validos, _, manifesto = ler_silver()
    assert list(validos.columns) == ESQUEMA_VALIDADO + geo.COLUNAS_GEO + consolidacao.COLUNAS_CONSOLIDACAO
    # JSON grava tuplas como listas: compara depois de converter
    assert manifesto["parametros_geo"] == {
        "limite_repeticao_m": geo.LIMITE_REPETICAO_M,
        "janela_repeticao_dias": geo.JANELA_REPETICAO_DIAS,
        "niveis_votacao": [list(n) for n in geo.NIVEIS_VOTACAO],
        "confianca_minima": geo.CONFIANCA_MINIMA,
        "ligacao_max_dias": consolidacao.LIGACAO_MAX_DIAS,
    }, "silver gerada com outros parâmetros do geo: rode python -m scripts.gerar_silver"
    # Só o distrito_final sem valor fica sem subprefeitura; o inferido ganha subprefeitura
    assert (validos["flag_sem_subprefeitura"] == validos["distrito_final"].isna()).all()
    assert validos.loc[validos["origem_distrito"] == "inferido", "subprefeitura"].notna().all()


def test_ocorrencias_somam_os_validos():
    """Cada válido está em exatamente uma ocorrência, e qtd_chamados_ocorrencia conta os seus chamados."""
    if not (SILVER / "chamados.parquet").exists():
        pytest.skip("silver ainda não gerada: rode python -m scripts.gerar_silver")
    validos, _, _ = ler_silver()
    assert validos["id_ocorrencia"].notna().all()
    por_ocorrencia = validos.groupby("id_ocorrencia")["qtd_chamados_ocorrencia"].agg(["first", "size"])
    assert (por_ocorrencia["first"] == por_ocorrencia["size"]).all()
    assert por_ocorrencia["first"].sum() == len(validos) == 244_426
