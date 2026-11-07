"""Testes da consolidação em ocorrências (src/consolidacao.py), com dados sintéticos."""
import pandas as pd
import pytest

from src.consolidacao import LIGACAO_MAX_DIAS, consolidar
from src.geo import adicionar_celulas

LAT, LON = -23.55, -46.63          # perto da Sé
METRO_LAT = 1 / 111_320            # graus de latitude por metro
DIA_0 = pd.Timestamp("2026-01-05")


def chamado(norte_m=0.0, dia=0, fim=None, status=None, rua="Rua Teste"):
    """fim: dias após DIA_0 em que foi finalizado (None = aberto)."""
    if status is None:
        status = "aberto" if fim is None else "finalizado"
    return {"lat": LAT + norte_m * METRO_LAT, "lon": LON, "logradouro": rua, "status": status,
            "data_abertura": DIA_0 + pd.Timedelta(days=dia),
            "data_finalizacao": DIA_0 + pd.Timedelta(days=fim) if fim is not None else pd.NaT}


def consolidado(*chamados):
    df = pd.DataFrame(chamados).astype({"logradouro": "string", "status": "string"})
    return consolidar(adicionar_celulas(df))


def test_dois_chamados_a_50m_e_3_dias_sao_uma_ocorrencia():
    df = consolidado(chamado(fim=10), chamado(norte_m=50, dia=3, fim=10))
    assert df["id_ocorrencia"].nunique() == 1
    assert df["qtd_chamados_ocorrencia"].tolist() == [2, 2]


def test_30_dias_com_o_primeiro_ainda_aberto_e_uma_ocorrencia():
    df = consolidado(chamado(), chamado(norte_m=50, dia=30))
    assert df["id_ocorrencia"].nunique() == 1
    assert df["numero_reincidencia"].tolist() == [0, 0]


def test_30_dias_com_o_primeiro_finalizado_antes_e_reincidencia():
    df = consolidado(chamado(fim=10), chamado(norte_m=50, dia=30, fim=40))
    assert df["id_ocorrencia"].nunique() == 2
    assert df["numero_reincidencia"].tolist() == [0, 1]


def test_reincidencia_encadeia_e_respeita_o_maximo_de_dias():
    df = consolidado(chamado(fim=10), chamado(dia=30, fim=40), chamado(dia=60, fim=70),
                     chamado(dia=70 + LIGACAO_MAX_DIAS + 5, fim=500))
    assert df["numero_reincidencia"].tolist() == [0, 1, 2, 0], "depois de 365 dias a cadeia recomeça"


def test_finalizado_sem_data_nao_conta_como_aberto():
    df = consolidado(chamado(status="finalizado"), chamado(norte_m=50, dia=30))
    assert df["id_ocorrencia"].nunique() == 2


def test_150m_e_1_dia_sao_duas_ocorrencias():
    df = consolidado(chamado(), chamado(norte_m=150, dia=1))
    assert df["id_ocorrencia"].nunique() == 2


def test_50m_e_1_dia_em_ruas_diferentes_sao_duas_ocorrencias():
    df = consolidado(chamado(), chamado(norte_m=50, dia=1, rua="Rua Outra"))
    assert df["id_ocorrencia"].nunique() == 2


def test_cadeia_a_b_c_com_70m_entre_vizinhos_e_uma_ocorrencia():
    df = consolidado(chamado(), chamado(norte_m=70, dia=1), chamado(norte_m=140, dia=2))
    assert df["id_ocorrencia"].nunique() == 1
    assert df["extensao_ocorrencia_m"].iloc[0] == pytest.approx(140, abs=1)


def test_soma_de_chamados_por_ocorrencia_e_o_total():
    df = consolidado(chamado(), chamado(norte_m=50, dia=3), chamado(norte_m=500),
                     chamado(norte_m=1000, fim=5), chamado(norte_m=1000, dia=40), chamado(rua=None))
    por_ocorrencia = df.groupby("id_ocorrencia")["qtd_chamados_ocorrencia"].first()
    assert por_ocorrencia.sum() == len(df)


def test_id_e_deterministico_e_nao_depende_da_ordem():
    chamados = [chamado(), chamado(norte_m=50, dia=3), chamado(norte_m=500, dia=1)]
    ida = consolidado(*chamados)["id_ocorrencia"].tolist()
    volta = consolidado(*reversed(chamados))["id_ocorrencia"].tolist()
    assert ida == list(reversed(volta))


def test_mesma_celula_dia_e_rua_mas_longe_nao_colide():
    """Dois problemas a mais de 80 m, no mesmo dia e rua, na MESMA célula r10: ids distintos."""
    import h3
    celula = h3.latlng_to_cell(LAT, LON, 10)
    (clat, clon), vertices = h3.cell_to_latlng(celula), h3.cell_to_boundary(celula)
    # Dois pontos a 90% do caminho entre o centro e vértices opostos do hexágono (~135 m entre si)
    perto = [(clat + 0.9 * (vlat - clat), clon + 0.9 * (vlon - clon)) for vlat, vlon in (vertices[0], vertices[3])]
    df = consolidado(*({**chamado(), "lat": lat, "lon": lon} for lat, lon in perto))
    assert df["celula_r10"].nunique() == 1, "o caso só testa a colisão se a célula for a mesma"
    assert h3.great_circle_distance(*perto, unit="m") > 80
    assert df["id_ocorrencia"].nunique() == 2
    # Estabilidade: a ocorrência que já existia não muda de id quando chega a vizinha que colidiria
    so_a_segunda = consolidado({**chamado(), "lat": perto[1][0], "lon": perto[1][1]})
    assert so_a_segunda["id_ocorrencia"].iloc[0] == df["id_ocorrencia"].iloc[1]


def test_linhas_identicas_sem_logradouro_ganham_ids_distintos():
    df = consolidado(chamado(rua=None), chamado(rua=None))
    assert df["id_ocorrencia"].nunique() == 2
