"""Previsão mensal de chamados por subprefeitura: baseline sazonal, com backtest contra o ingênuo.

    previsão(M) = valor de M - 12 meses
                  x (soma dos 3 meses até a origem / soma dos mesmos 3 meses um ano antes)

A origem é o último mês observado. Para M = origem + 1, os 3 meses até a origem são os 3 meses
anteriores a M, como na fórmula original. Para horizontes maiores, esses meses ainda não são
conhecidos, então a razão fica fixa na origem (é o mesmo nível para os 3 meses previstos).

Referência ingênua: repetir o valor do último mês observado. O baseline só vale a pena se errar
menos que ela no backtest.

Uso:  python -m scripts.prever   (lê data/gold/reparos.duckdb, grava em marts)
"""
import duckdb
import numpy as np
import pandas as pd

from src.ingestao import RAIZ

GOLD = RAIZ / "data" / "gold" / "reparos.duckdb"
MESES_NIVEL = 3


def serie_mensal(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Chamados por mês de abertura (linhas) e subprefeitura (colunas), com 0 nos meses sem chamado."""
    longa = con.execute("""
        select date_trunc('month', c.data_abertura) as mes, l.subprefeitura, count(*) as chamados
        from core.fato_chamado as c
        join core.dim_local as l on l.distrito = c.distrito_final
        group by all
    """).df()
    serie = longa.pivot(index="mes", columns="subprefeitura", values="chamados")
    meses = pd.period_range(serie.index.min(), serie.index.max(), freq="M")
    serie.index = pd.PeriodIndex(serie.index, freq="M")
    return serie.reindex(meses).fillna(0).astype(float)


def prever_sazonal(serie: pd.DataFrame, origem: pd.Period, horizonte: int) -> pd.DataFrame:
    """Previsões para origem+1 ... origem+horizonte (linhas) por subprefeitura (colunas)."""
    recentes = serie.loc[origem - (MESES_NIVEL - 1):origem].sum()
    ano_antes = serie.loc[origem - (MESES_NIVEL - 1) - 12:origem - 12].sum()
    # Sem chamados no ano anterior não há razão a calcular: fica 1 (só a sazonalidade)
    razao = (recentes / ano_antes.replace(0, np.nan)).fillna(1.0)
    meses = [origem + h for h in range(1, horizonte + 1)]
    return pd.DataFrame([serie.loc[m - 12] * razao for m in meses], index=pd.PeriodIndex(meses, freq="M"))


def prever_ingenuo(serie: pd.DataFrame, origem: pd.Period, horizonte: int) -> pd.DataFrame:
    meses = [origem + h for h in range(1, horizonte + 1)]
    return pd.DataFrame([serie.loc[origem]] * horizonte, index=pd.PeriodIndex(meses, freq="M"))


def erro_medio_absoluto(real: pd.DataFrame, previsto: pd.DataFrame) -> float:
    return float((real - previsto).abs().to_numpy().mean())


def backtest(serie: pd.DataFrame, origem: pd.Period, horizonte: int) -> pd.DataFrame:
    """Uma linha por (mês, subprefeitura) com o real e as duas previsões feitas a partir da origem."""
    meses = pd.PeriodIndex([origem + h for h in range(1, horizonte + 1)], freq="M")
    partes = {"real": serie.loc[meses], "previsto_sazonal": prever_sazonal(serie, origem, horizonte),
              "previsto_ingenuo": prever_ingenuo(serie, origem, horizonte)}
    return _longa(partes)


def gravar(con: duckdb.DuckDBPyConnection, nome: str, tabela: pd.DataFrame) -> None:
    con.execute("create schema if not exists marts")
    con.register("tabela_nova", tabela)
    con.execute(f"create or replace table marts.{nome} as select * from tabela_nova")
    con.unregister("tabela_nova")


def _longa(partes: dict[str, pd.DataFrame]) -> pd.DataFrame:
    longas = [df.rename_axis(index="mes", columns="subprefeitura").stack().rename(nome) for nome, df in partes.items()]
    tabela = pd.concat(longas, axis=1).reset_index()
    tabela["mes"] = tabela["mes"].dt.to_timestamp().dt.date
    return tabela
