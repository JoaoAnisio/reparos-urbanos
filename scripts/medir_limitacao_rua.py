"""Mede o custo da regra "mesma rua" da flag_repeticao (limitação registrada no README).

Uso:  python -m scripts.medir_limitacao_rua

Mesma busca do 02_exploracao.ipynb, mas SEM o filtro de rua: todos os pares a menos de
DISTANCIA_M e em ±JANELA_REPETICAO_DIAS, separados entre mesma rua e ruas diferentes. Os
pares de ruas diferentes são esquinas, apelidos de rodovia ou grafias diferentes da mesma rua.
Lê a silver gravada (rode antes python -m scripts.gerar_silver).
"""
import h3
import pandas as pd

from src.comum import normalizar
from src.geo import JANELA_REPETICAO_DIAS, RESOLUCAO_REPETICAO, distancia_m, k_para_raio
from src.silver import ler_silver

DISTANCIA_M = 20

pd.set_option("display.width", 200)


def pares_proximos(chamados: pd.DataFrame) -> pd.DataFrame:
    """Pares (sem repetir a ordem) a menos de DISTANCIA_M e em ±JANELA_REPETICAO_DIAS, de qualquer rua."""
    coluna = f"celula_r{RESOLUCAO_REPETICAO}"
    k = k_para_raio(DISTANCIA_M, RESOLUCAO_REPETICAO)
    base = chamados.loc[chamados["logradouro"].notna(), ["lat", "lon", "data_abertura", "logradouro", coluna]].copy()
    base["rua"] = base["logradouro"].map({v: normalizar(v) for v in base["logradouro"].unique()})
    base["id"] = base.index

    busca = base.assign(celula_busca=base[coluna].map(lambda c: list(h3.grid_disk(c, k)))).explode("celula_busca")
    pares = busca.merge(base, left_on="celula_busca", right_on=coluna, suffixes=("", "_viz"))
    dias = (pares["data_abertura"] - pares["data_abertura_viz"]).abs().dt.days
    pares = pares[(pares["id"] < pares["id_viz"]) & (dias <= JANELA_REPETICAO_DIAS)]
    pares = pares[distancia_m(pares["lat"], pares["lon"], pares["lat_viz"], pares["lon_viz"]) < DISTANCIA_M]
    return pares.assign(mesma_rua=pares["rua"] == pares["rua_viz"])


def executar() -> None:
    chamados, _, _ = ler_silver()
    pares = pares_proximos(chamados)
    diferentes = pares[~pares["mesma_rua"]]
    print(f"Pares a menos de {DISTANCIA_M} m em ±{JANELA_REPETICAO_DIAS} dias: {len(pares):,}")
    print(f"  mesma rua:        {int(pares['mesma_rua'].sum()):,}")
    print(f"  ruas diferentes:  {len(diferentes):,} ({len(diferentes) / len(pares):.1%})")

    # Custo em chamados: sem flag_repeticao, mas com vizinho a menos de DISTANCIA_M em outra rua
    ids = pd.unique(pd.concat([diferentes["id"], diferentes["id_viz"]]))
    perdidos = int((~chamados.loc[ids, "flag_repeticao"]).sum())
    print(f"Chamados sem flag_repeticao que a teriam sem a regra de mesma rua: {perdidos:,} "
          f"({perdidos / len(chamados):.1%} de {len(chamados):,})")

    print("\nPares de ruas diferentes mais frequentes:")
    pares_de_rua = diferentes.groupby(["logradouro", "logradouro_viz"]).size().sort_values(ascending=False)
    print(pares_de_rua.head(10).to_string())


if __name__ == "__main__":
    executar()
