"""Testes da previsão (src/previsao.py) com séries sintéticas: rodam sem a gold."""
import duckdb
import numpy as np
import pandas as pd
import pytest

from src.previsao import backtest, erro_medio_absoluto, prever_ingenuo, prever_sazonal, serie_mensal

MESES = pd.period_range("2024-01", "2025-12", freq="M")


def serie(**colunas):
    return pd.DataFrame({nome: np.asarray(valores, dtype=float) for nome, valores in colunas.items()}, index=MESES)


def test_um_mes_a_frente_e_a_formula_original():
    s = serie(A=np.arange(1, 25) * 10)           # 10, 20, ..., 240
    origem = pd.Period("2025-06", freq="M")
    previsto = prever_sazonal(s, origem, 1).loc[pd.Period("2025-07", freq="M"), "A"]
    # valor de 07/2024 x (04 a 06/2025) / (04 a 06/2024)
    esperado = s.loc["2024-07", "A"] * s.loc["2025-04":"2025-06", "A"].sum() / s.loc["2024-04":"2024-06", "A"].sum()
    assert previsto == pytest.approx(esperado)


def test_horizontes_maiores_usam_a_razao_da_origem():
    s = serie(A=[100] * 12 + [200] * 12)         # o segundo ano tem o dobro do primeiro
    previsto = prever_sazonal(s, pd.Period("2025-06", freq="M"), 3)
    assert previsto["A"].tolist() == [200.0, 200.0, 200.0]


def test_sem_chamados_no_ano_anterior_a_razao_e_1():
    s = serie(A=[0] * 12 + [50] * 12)
    previsto = prever_sazonal(s, pd.Period("2025-06", freq="M"), 1)
    assert previsto["A"].tolist() == [0.0], "fica só a sazonalidade (o valor de um ano antes)"


def test_ingenuo_repete_o_ultimo_mes():
    s = serie(A=np.arange(24), B=np.arange(24) * 2)
    previsto = prever_ingenuo(s, pd.Period("2025-06", freq="M"), 3)
    assert previsto["A"].tolist() == [17.0] * 3 and previsto["B"].tolist() == [34.0] * 3


def test_erro_medio_absoluto():
    real = pd.DataFrame({"A": [10.0, 20.0], "B": [5.0, 5.0]})
    previsto = pd.DataFrame({"A": [12.0, 17.0], "B": [5.0, 9.0]})
    assert erro_medio_absoluto(real, previsto) == pytest.approx((2 + 3 + 0 + 4) / 4)


def test_backtest_nao_usa_dados_depois_da_origem():
    s = serie(A=[100] * 24)
    alterada = s.copy()
    alterada.loc["2025-07":, "A"] = 9999         # o "futuro" muda; as previsões não podem mudar
    origem = pd.Period("2025-06", freq="M")
    original, com_futuro = backtest(s, origem, 3), backtest(alterada, origem, 3)
    assert original["previsto_sazonal"].tolist() == com_futuro["previsto_sazonal"].tolist()
    assert original["previsto_ingenuo"].tolist() == com_futuro["previsto_ingenuo"].tolist()
    assert com_futuro["real"].tolist() == [9999.0] * 3


def test_serie_mensal_preenche_meses_sem_chamado():
    con = duckdb.connect()
    con.execute("create schema core")
    con.execute("create table core.dim_local as select * from (values ('SE', 'SE'), ('LAPA', 'LAPA')) t(distrito, subprefeitura)")
    con.execute("""create table core.fato_chamado as select * from (values
        (date '2026-01-10', 'SE'), (date '2026-01-20', 'SE'), (date '2026-03-05', 'SE'),
        (date '2026-03-06', 'LAPA'), (date '2026-02-01', null)) t(data_abertura, distrito_final)""")
    s = serie_mensal(con)
    assert [str(m) for m in s.index] == ["2026-01", "2026-02", "2026-03"]
    assert s["SE"].tolist() == [2.0, 0.0, 1.0] and s["LAPA"].tolist() == [0.0, 0.0, 1.0]
