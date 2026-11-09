"""Painel de reparos urbanos (tapa-buraco, SP156).

Uso:  make painel     (ou: streamlit run dashboard/app.py)

Lê apenas tabelas do schema marts da gold, numa conexão somente leitura. Rode a pipeline antes.
Com o painel aberto, a pipeline não consegue gravar no DuckDB: feche-o antes de rodar make pipeline.
"""
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import pydeck as pdk
import streamlit as st

GOLD = Path(__file__).resolve().parent.parent / "data" / "gold" / "reparos.duckdb"
# As únicas tabelas que o painel pode ler: todas do schema marts.
MARTS = {
    "mart_indicadores", "mart_mapa_calor", "mart_fila_prioridade", "mart_verificacao_campo",
    "mart_serie_mensal", "mart_equidade", "previsao_subprefeitura", "previsao_backtest",
}
NOME_METODO = {"ingenuo": "repetição do último mês", "sazonal": "baseline sazonal"}
COMPONENTES = {
    "componente_espera": "espera (30%)",
    "componente_via": "via (25%)",
    "componente_demanda": "demanda (15%)",
    "componente_reincidencia": "reincidência (15%)",
    "componente_equidade": "equidade (15%)",
}


@st.cache_data
def ler(tabela: str) -> pd.DataFrame:
    if tabela not in MARTS:
        raise ValueError(f"O painel só lê marts: {tabela!r} não está em MARTS")
    with duckdb.connect(str(GOLD), read_only=True) as con:
        return con.execute(f"select * from marts.{tabela}").df()


def filtrar(df: pd.DataFrame, zona: str, corredor: str | None = None) -> pd.DataFrame:
    if zona != "Todas":
        df = df[df["zona"] == zona]
    if corredor is not None and corredor != "todos" and "flag_corredor" in df:
        df = df[df["flag_corredor"] == (corredor == "sim")]
    elif corredor is not None and corredor != "todos" and "corredor" in df:
        df = df[df["corredor"] == corredor]
    return df


st.set_page_config(page_title="Reparos urbanos", layout="wide")
st.title("Tapa-buraco em São Paulo")

if not GOLD.exists():
    st.error("A gold ainda não existe. Rode `make pipeline` antes de abrir o painel.")
    st.stop()

indicadores = ler("mart_indicadores")
referencia = pd.to_datetime(indicadores["data_referencia"].iloc[0]).date()
st.caption(f"Chamados do SP156 (dados abertos, CC0). Referência: extração de {referencia:%d/%m/%Y}.")

# ---------------------------------------------------------------- filtros
with st.sidebar:
    st.header("Filtros")
    zona = st.selectbox("Zona", ["Todas", "Centro", "Norte", "Sul", "Leste", "Oeste"])
    corredor = st.radio("Corredor de ônibus", ["todos", "sim", "não"], horizontal=True)
    st.caption("O mapa e a tabela de equidade não se dividem por corredor: o mapa perderia o "
               "k-anonimato (3+ chamados por célula), e a equidade é por subprefeitura.")

# ---------------------------------------------------------------- indicadores
linha = indicadores[(indicadores["zona"] == zona) & (indicadores["corredor"] == corredor)].iloc[0]
milhar = lambda n: f"{int(n):,}".replace(",", ".")
janela = f"iniciadas de {linha['janela_inicio']:%m/%Y} a {linha['janela_fim']:%m/%Y}"
c1, c2, c3, c4 = st.columns(4)
c1.metric("Ocorrências abertas", milhar(linha["ocorrencias_abertas"]),
          help=f"{milhar(linha['abertas_na_fila'])} na fila de despacho (até 180 dias) e "
               f"{milhar(linha['abertas_verificar_campo'])} a verificar em campo (mais de 180 dias).")
c2.metric("Tempo mediano de reparo (90 dias)", f"{linha['tempo_mediano_reparo_90d_dias']:.0f} dias",
          help="Ocorrências resolvidas nos 90 dias antes da extração, do primeiro chamado ao fim.")
c3.metric("Taxa de resolução", f"{linha['taxa_resolucao_janela']:.0%}",
          help=f"Ocorrências {janela} (de 15 a 3 meses antes da extração) que já foram resolvidas. "
               "As dos últimos 3 meses ficam de fora: ainda não tiveram tempo de ser resolvidas.")
c4.metric("Perto de problema encerrado", f"{linha['pct_reincidencia_janela']:.0%}",
          help=f"Ocorrências {janela} que surgem a até 80 m, na mesma rua, de uma ocorrência encerrada "
               "no ano anterior. Não é o mesmo buraco: comparando com a faixa de 80 a 160 m, só cerca "
               "de 10 pontos percentuais são atribuíveis ao mesmo ponto (ver README).")

# ---------------------------------------------------------------- mapa e fila
col_mapa, col_fila = st.columns([3, 2])

with col_mapa:
    st.subheader("Onde estão os chamados (últimos 12 meses)")
    mapa = filtrar(ler("mart_mapa_calor"), zona).copy()
    maximo = max(mapa["chamados"].max(), 1)
    mapa["cor"] = [[255, int(220 * (1 - n / maximo)), 0, 170] for n in mapa["chamados"]]
    camada = pdk.Layer(
        "H3HexagonLayer", mapa, get_hexagon="celula_r8", get_fill_color="cor",
        pickable=True, stroked=False, extruded=False,
    )
    vista = pdk.ViewState(latitude=-23.60, longitude=-46.63, zoom=9.3)
    st.pydeck_chart(pdk.Deck(layers=[camada], initial_view_state=vista,
                             tooltip={"text": "{chamados} chamados\n{ocorrencias_abertas} abertas"}))
    st.caption(f"{len(mapa):,} células H3 r8 (~530 m). Só células com 3 ou mais chamados.".replace(",", "."))

with col_fila:
    st.subheader("Fila de despacho: top 10")
    fila = filtrar(ler("mart_fila_prioridade"), zona, corredor).sort_values("posicao_fila").head(10)
    st.dataframe(
        fila[["posicao_fila", "score", "logradouro", "subprefeitura", "dias_em_aberto", "qtd_chamados"]],
        hide_index=True,
        column_config={"posicao_fila": "posição", "dias_em_aberto": "dias", "qtd_chamados": "chamados"},
    )
    st.caption("Só abertas há até 180 dias. As mais antigas estão em \"Verificar em campo\", abaixo.")
    with st.expander("Por que essa ordem?"):
        st.write("Score = 10 × soma ponderada de 5 componentes entre 0 e 1. Em caso de empate, "
                 "a ocorrência mais antiga vem primeiro.")
        st.dataframe(fila[["posicao_fila", "score", *COMPONENTES]].rename(columns=COMPONENTES).round(2),
                     hide_index=True)

    st.subheader("Verificar em campo")
    verificar = filtrar(ler("mart_verificacao_campo"), zona, corredor).sort_values("posicao_verificacao")
    st.write(f"{milhar(len(verificar))} ocorrências abertas há mais de 180 dias. O status pode estar "
             "desatualizado: antes de despachar, confirmar se o buraco ainda existe.")
    with st.expander("As 10 mais antigas"):
        st.dataframe(verificar.head(10)[["dias_em_aberto", "logradouro", "subprefeitura", "qtd_chamados"]],
                     hide_index=True, column_config={"dias_em_aberto": "dias", "qtd_chamados": "chamados"})

# ---------------------------------------------------------------- série e previsão
st.subheader("Chamados por mês")
serie = filtrar(ler("mart_serie_mensal"), zona, corredor).groupby("mes", as_index=False) \
    .agg(chamados=("chamados", "sum"), chuvoso=("flag_periodo_chuvoso", "first"))
serie["mes"] = pd.to_datetime(serie["mes"])
serie["tipo"] = "real"

camadas = []
chuva = serie.loc[serie["chuvoso"], ["mes"]].assign(fim=lambda d: d["mes"] + pd.offsets.MonthBegin(1))
camadas.append(alt.Chart(chuva).mark_rect(opacity=0.15, color="#4c78a8").encode(x="mes:T", x2="fim:T"))

if corredor == "todos":
    previsao = ler("previsao_subprefeitura").merge(ler("mart_equidade")[["subprefeitura", "zona"]], on="subprefeitura")
    previsao = filtrar(previsao, zona).groupby("mes", as_index=False)["previsto"].sum()
    previsao = previsao.rename(columns={"previsto": "chamados"}).assign(tipo="previsão")
    previsao["mes"] = pd.to_datetime(previsao["mes"])
    # liga a previsão ao último mês real para a linha não ficar solta
    linhas = pd.concat([serie[["mes", "chamados", "tipo"]],
                        serie.tail(1)[["mes", "chamados"]].assign(tipo="previsão"), previsao])
    teste = ler("previsao_backtest")
    erro = {m: (teste["real"] - teste[f"previsto_{m}"]).abs().mean() for m in NOME_METODO}
    metodo = ler("previsao_subprefeitura")["metodo"].iloc[0]
    outro = "sazonal" if metodo == "ingenuo" else "ingenuo"
    nota = (f"Previsão dos próximos 3 meses: {NOME_METODO[metodo]}, o método que errou menos no backtest "
            f"(erro médio de {erro[metodo]:.0f} contra {erro[outro]:.0f} chamados por subprefeitura e mês).")
else:
    linhas = serie[["mes", "chamados", "tipo"]]
    nota = "A previsão é por subprefeitura, sem divisão por corredor: escolha 'todos' para vê-la."

camadas.append(alt.Chart(linhas).mark_line(point=True).encode(
    x=alt.X("mes:T", title=None), y=alt.Y("chamados:Q", title="chamados"),
    color=alt.Color("tipo:N", title=None, scale=alt.Scale(domain=["real", "previsão"], range=["#e45756", "#888888"])),
    strokeDash=alt.StrokeDash("tipo:N", legend=None, scale=alt.Scale(domain=["real", "previsão"], range=[[1, 0], [6, 4]])),
))
st.altair_chart(alt.layer(*camadas), use_container_width=True)
st.caption(f"Faixas azuis: período chuvoso (dezembro a março). {nota}")

# ---------------------------------------------------------------- equidade
st.subheader("Equidade por subprefeitura")
equidade = filtrar(ler("mart_equidade"), zona).sort_values("tempo_reparo_mediano_dias", ascending=False)
st.dataframe(
    equidade[["subprefeitura", "zona", "chamados", "pct_canais_digitais", "tempo_reparo_mediano_dias",
              "tempo_reparo_p90_dias", "ocorrencias_abertas", "pct_abertas_mais_90_dias"]],
    hide_index=True,
    column_config={
        "pct_canais_digitais": st.column_config.NumberColumn("canais digitais", format="percent"),
        "tempo_reparo_mediano_dias": st.column_config.NumberColumn("reparo, mediana (dias)", format="%.0f"),
        "tempo_reparo_p90_dias": st.column_config.NumberColumn("reparo, p90 (dias)", format="%.0f"),
        "ocorrencias_abertas": "abertas",
        "pct_abertas_mais_90_dias": st.column_config.NumberColumn("abertas há 90+ dias", format="percent"),
    },
)
st.caption("O painel não mostra chamados individuais, endereço com número nem coordenada exata (LGPD).")
