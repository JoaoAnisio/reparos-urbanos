"""Backtest do baseline sazonal e previsão dos próximos meses por subprefeitura.

Uso:  python -m scripts.prever     (depois do dbt build)

Grava no DuckDB da gold:
- marts.previsao_backtest: origem em 06/2026, previsto x real de 07 a 09/2026
- marts.previsao_subprefeitura: (mes, subprefeitura, previsto) para os 3 meses depois do último
  mês observado, pelo método que errou menos no backtest
"""
import duckdb
import pandas as pd

from src.previsao import (GOLD, backtest, erro_medio_absoluto, gravar, prever_ingenuo, prever_sazonal,
                          serie_mensal)

ORIGEM_BACKTEST = pd.Period("2026-06", freq="M")
HORIZONTE = 3

pd.set_option("display.width", 200)


def executar() -> None:
    with duckdb.connect(str(GOLD)) as con:
        serie = serie_mensal(con)
        print(f"Série: {serie.index.min()} a {serie.index.max()}, {serie.shape[1]} subprefeituras")

        teste = backtest(serie, ORIGEM_BACKTEST, HORIZONTE)
        erro_sazonal = erro_medio_absoluto(teste["real"], teste["previsto_sazonal"])
        erro_ingenuo = erro_medio_absoluto(teste["real"], teste["previsto_ingenuo"])
        print(f"\nBacktest (treino até {ORIGEM_BACKTEST}, previsão de {HORIZONTE} meses):")
        print(f"  erro médio absoluto  sazonal: {erro_sazonal:6.1f} chamados por subprefeitura e mês")
        print(f"  erro médio absoluto  ingênuo: {erro_ingenuo:6.1f}")
        por_mes = teste.assign(erro_sazonal=(teste["real"] - teste["previsto_sazonal"]).abs(),
                               erro_ingenuo=(teste["real"] - teste["previsto_ingenuo"]).abs()) \
                       .groupby("mes")[["real", "erro_sazonal", "erro_ingenuo"]].mean().round(1)
        print(por_mes.to_string())
        vence = "sazonal" if erro_sazonal < erro_ingenuo else "ingenuo"
        print(f"  -> {'o baseline sazonal vale a pena' if vence == 'sazonal' else 'o baseline NÃO vale a pena: usar o ingênuo'}")
        gravar(con, "previsao_backtest", teste)

        origem = serie.index.max()
        prever = prever_sazonal if vence == "sazonal" else prever_ingenuo
        futuro = prever(serie, origem, HORIZONTE).rename_axis(index="mes", columns="subprefeitura") \
                                                 .stack().rename("previsto").reset_index()
        futuro["mes"] = futuro["mes"].dt.to_timestamp().dt.date
        gravar(con, "previsao_subprefeitura", futuro)
        print(f"\nmarts.previsao_subprefeitura: {len(futuro)} linhas, {origem + 1} a {origem + HORIZONTE}, "
              f"método {vence}; total previsto por mês:")
        print(futuro.groupby("mes")["previsto"].sum().round(0).to_string())


if __name__ == "__main__":
    executar()
