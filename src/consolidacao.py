"""Consolidação dos chamados em ocorrências (o problema físico) e reincidências.

Regras:
- Ligação: dois chamados são do mesmo problema se estão na mesma rua, a até LIMITE_REPETICAO_M e
  (a) foram abertos com até JANELA_REPETICAO_DIAS de diferença, ou (b) o mais novo chegou antes
  de o mais antigo ser finalizado (o mais antigo está aberto, ou a finalização dele é posterior).
  Nenhuma ligação passa de LIGACAO_MAX_DIAS, para que um chamado "aberto" esquecido não junte
  anos de chamados no mesmo ponto.
- Ocorrência = componente conexo do grafo de ligações (A–B e B–C juntam A, B e C).
- id_ocorrencia é determinístico: hash do chamado mais antigo do componente.
- Reincidência: B tem antecessora A se algum chamado de A está a até LIMITE_REPETICAO_M de um de B
  na mesma rua, A está resolvida, A.fim < B.inicio e B.inicio - A.fim <= LIGACAO_MAX_DIAS.
  numero_reincidencia = maior cadeia de antecessoras.

Espera a saída do geo.enriquecer (celula_r10) e o índice sem repetição.
"""
import hashlib

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from src.comum import normalizar
from src.geo import JANELA_REPETICAO_DIAS, LIMITE_REPETICAO_M, RESOLUCAO_REPETICAO, distancia_m, pares_candidatos

LIGACAO_MAX_DIAS = 365

COLUNAS_CONSOLIDACAO = [
    "id_ocorrencia", "numero_reincidencia", "extensao_ocorrencia_m", "qtd_chamados_ocorrencia",
]


# ----------------------------------------------------------------- função pública
def consolidar(df: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta as COLUNAS_CONSOLIDACAO. Não altera o DataFrame recebido."""
    df = df.copy()
    pares = pares_candidatos(df, LIMITE_REPETICAO_M)
    rotulo = componentes(df, arestas(df, pares))
    df["id_ocorrencia"] = _ids_ocorrencia(df, rotulo)

    ocorrencias = tabela_ocorrencias(df)
    reincidencia = numero_reincidencia(ocorrencias, _antecessoras(df, ocorrencias, pares))

    df["numero_reincidencia"] = df["id_ocorrencia"].map(reincidencia).astype("int64")
    df["extensao_ocorrencia_m"] = df["id_ocorrencia"].map(ocorrencias["extensao_m"]).astype("float64")
    df["qtd_chamados_ocorrencia"] = df["id_ocorrencia"].map(ocorrencias["qtd_chamados"]).astype("int64")
    return df


# ----------------------------------------------------------------- etapas
def arestas(df: pd.DataFrame, pares: pd.DataFrame) -> pd.DataFrame:
    """Pares (cada um uma vez) que obedecem à regra de ligação."""
    p = pares[pares["id"] < pares["id_viz"]]
    a, b = df.loc[p["id"]], df.loc[p["id_viz"]]
    a_primeiro = a["data_abertura"].values <= b["data_abertura"].values
    ab_antigo = np.where(a_primeiro, a["data_abertura"].values, b["data_abertura"].values)
    ab_novo = np.where(a_primeiro, b["data_abertura"].values, a["data_abertura"].values)
    fim_antigo = np.where(a_primeiro, a["data_finalizacao"].values, b["data_finalizacao"].values)
    status_antigo = np.where(a_primeiro, a["status"].values, b["status"].values)
    dias = (ab_novo - ab_antigo) / np.timedelta64(1, "D")
    # "Ainda não finalizado" = status aberto. O finalizado SEM data (1.092 na silver) foi finalizado,
    # só não se sabe quando: tratá-lo como aberto criaria 4.356 ligações de até 365 dias.
    antes_do_reparo = (status_antigo == "aberto") | (ab_novo <= fim_antigo)
    liga = ((dias <= JANELA_REPETICAO_DIAS) | antes_do_reparo) & (dias <= LIGACAO_MAX_DIAS)
    return p[liga]


def componentes(df: pd.DataFrame, arestas: pd.DataFrame) -> np.ndarray:
    """Rótulo do componente conexo de cada linha de df (na ordem de df)."""
    idx = pd.Index(df.index)
    i, j = idx.get_indexer(arestas["id"]), idx.get_indexer(arestas["id_viz"])
    grafo = coo_matrix((np.ones(len(i)), (i, j)), shape=(len(df), len(df)))
    _, rotulo = connected_components(grafo, directed=False)
    return rotulo


def tabela_ocorrencias(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por id_ocorrencia: inicio, fim, qtd_chamados, situacao e extensao_m."""
    g = df.groupby("id_ocorrencia")
    ocorrencias = g.agg(
        inicio=("data_abertura", "min"),
        fim=("data_finalizacao", "max"),
        qtd_chamados=("data_abertura", "size"),
        lat_min=("lat", "min"), lat_max=("lat", "max"),
        lon_min=("lon", "min"), lon_max=("lon", "max"),
    )
    tem_aberto = g["status"].agg(lambda s: (s == "aberto").any())
    tem_finalizado = g["status"].agg(lambda s: (s == "finalizado").any())
    ocorrencias["situacao"] = np.select([tem_aberto, tem_finalizado], ["aberta", "resolvida"], default="cancelada")
    ocorrencias.loc[tem_aberto, "fim"] = pd.NaT                   # só tem fim quem não tem chamado aberto
    ocorrencias["extensao_m"] = distancia_m(ocorrencias["lat_min"], ocorrencias["lon_min"],
                                            ocorrencias["lat_max"], ocorrencias["lon_max"])
    return ocorrencias.drop(columns=["lat_min", "lat_max", "lon_min", "lon_max"])


def numero_reincidencia(ocorrencias: pd.DataFrame, antecessoras: dict) -> dict:
    """Maior cadeia de antecessoras de cada ocorrência (0 = sem antecessora)."""
    reinc = dict.fromkeys(ocorrencias.index, 0)
    for b in ocorrencias.sort_values("inicio").index:
        for a in antecessoras.get(b, []):
            reinc[b] = max(reinc[b], reinc[a] + 1)
    return reinc


# ----------------------------------------------------------------- auxiliares
def _ids_ocorrencia(df: pd.DataFrame, rotulo: np.ndarray) -> pd.Series:
    """sha1(celula_r10 | data_abertura | rua | lat | lon)[:16] do chamado mais antigo do componente.

    Sem lat/lon, 419 componentes colidiam: a célula r10 tem ~150 m de diâmetro, então dois
    problemas a mais de 80 m na mesma rua, no mesmo dia, ficavam com a mesma chave. Desempatar só
    por numeração faria o id de uma ocorrência mudar quando um chamado novo colidisse com ela; com
    lat/lon, o id depende só do próprio chamado mais antigo. O sufixo fica para o empate que sobra
    (linhas idênticas sem logradouro, que nunca se ligam): como são iguais, a ordem não importa.
    """
    celula = f"celula_r{RESOLUCAO_REPETICAO}"
    base = df[["data_abertura", "lat", "lon", celula, "logradouro"]].assign(componente=rotulo)
    primeiro = base.sort_values(["data_abertura", "lat", "lon"]).drop_duplicates("componente")
    ruas = {v: normalizar(v) for v in primeiro["logradouro"].dropna().unique()}
    chave = (primeiro[celula] + "|" + primeiro["data_abertura"].dt.strftime("%Y-%m-%d") + "|"
             + primeiro["logradouro"].map(ruas).fillna("") + "|"
             + primeiro["lat"].map("{:.6f}".format) + "|" + primeiro["lon"].map("{:.6f}".format))
    empate = chave.groupby(chave).cumcount()
    chave = chave.where(empate == 0, chave + "#" + empate.astype(str))
    ids = pd.Series([hashlib.sha1(c.encode("utf-8")).hexdigest()[:16] for c in chave],
                    index=primeiro["componente"].values)
    return pd.Series(ids.reindex(rotulo).values, index=df.index, dtype="string")


def _antecessoras(df: pd.DataFrame, ocorrencias: pd.DataFrame, pares: pd.DataFrame) -> dict:
    """{ocorrência B: [ocorrências A que a antecedem]}, a partir dos pares de chamados próximos."""
    a = df.loc[pares["id"], "id_ocorrencia"].values
    b = df.loc[pares["id_viz"], "id_ocorrencia"].values
    ligadas = pd.DataFrame({"a": a, "b": b}).query("a != b").drop_duplicates()
    ligadas = ligadas.join(ocorrencias[["situacao", "fim"]], on="a").join(ocorrencias[["inicio"]], on="b")
    intervalo = ligadas["inicio"] - ligadas["fim"]
    validas = ligadas[(ligadas["situacao"] == "resolvida") & (ligadas["fim"] < ligadas["inicio"])
                      & (intervalo <= pd.Timedelta(days=LIGACAO_MAX_DIAS))]
    return validas.groupby("b")["a"].agg(list).to_dict()
