"""Enriquecimento geográfico dos chamados da silver com H3.

Regras (análise em notebooks/02_exploracao.ipynb):
- celula_r10 (aresta ~76 m) é a base da votação e da busca de repetições; celula_r8 (~531 m) é o
  último recurso da votação e serve para agregar em mapas.
- Distrito nulo é inferido por votação: o distrito mais comum entre os chamados COM distrito nas
  células de NIVEIS_VOTACAO, em ordem, até haver votos. A confiança é a proporção do vencedor.
- distrito_final = informado ou, na falta dele, inferido (origem_distrito diz qual). Subprefeitura
  e zona são reanexadas por ele no gerar_silver, e não aqui: o geo não depende da silver.
- Decisão: a divisa (confiança < CONFIANCA_MINIMA) também entra no distrito_final, com a flag.
  Regra geral: não jogar informação fora; guardar a melhor estimativa junto com a medida de
  confiança (confianca_distrito, flag_distrito_divisa) e deixar cada uso decidir se a aceita.
- Repetição: outro chamado na mesma rua, a até LIMITE_REPETICAO_M e aberto a até
  JANELA_REPETICAO_DIAS. A flag marca os dois lados do par; não decide qual descartar.

Premissa: recebe a silver validada (sem coordenada nula).

Limitação conhecida: "mesma rua" compara o logradouro normalizado, então esquinas (Rua dos
Piemonteses x Rua Agostinho de Azevedo) e apelidos de rodovia (Estrada do M'Boi Mirim x SP-214)
contam como ruas diferentes. Medido nos 244 mil chamados: dos pares a menos de 20 m em ±7 dias,
2,2% têm ruas diferentes, e só 2.630 chamados (1,1%) ficariam com flag_repeticao se a rua não
importasse. Abreviações não são o problema: os logradouros vêm por extenso, e expandir "Av.",
"R.", "Trav." recuperaria 4 chamados.
"""
import math

import h3
import numpy as np
import pandas as pd

from src.comum import normalizar

RESOLUCOES = (8, 10)

# Colunas que o enriquecer acrescenta. Subprefeitura, zona e flag_sem_subprefeitura não estão aqui:
# a silver as reanexa pelo distrito_final depois do enriquecer.
COLUNAS_GEO = [
    "celula_r8", "celula_r10",
    "distrito_inferido", "confianca_distrito", "nivel_distrito", "flag_distrito_divisa", "flag_sem_votos",
    "distrito_final", "origem_distrito",
    "dist_vizinho_m", "flag_repeticao",
]

# Ordem da votação: (resolução, k do grid_disk). Validação com 5.000 chamados com distrito,
# retirados dos eleitores: acerto de 97,3% em r10 (98,9% quando a confiança é >= 80%) e
# 88,6% em r8, por isso r8 só entra quando r10 com as vizinhas não tem nenhum voto.
NIVEIS_VOTACAO = ((10, 0), (10, 1), (8, 0))
# Abaixo de 80% de votos o acerto validado cai para ~62%: o caso vira "divisa".
CONFIANCA_MINIMA = 0.8

# Limite medido na análise de vizinhos (02_exploracao.ipynb, célula "controle 90–97 dias"): comparando a janela de
# ±7 dias com controles de 90 e 180 dias depois, até 80 m mais da metade dos vizinhos é excesso
# sobre o acaso (razão > 2); a partir daí o excesso cai abaixo da metade e some perto de 200 m.
LIMITE_REPETICAO_M = 80
JANELA_REPETICAO_DIAS = 7
RESOLUCAO_REPETICAO = 10
MARGEM_RAIO = 1.25  # o tamanho real das células varia em torno da média

RAIO_TERRA_M = 6_371_000


# ----------------------------------------------------------------- funções públicas
def enriquecer(chamados: pd.DataFrame) -> pd.DataFrame:
    """Aplica células, distrito inferido e final, e repetições. Não altera a entrada."""
    df = adicionar_celulas(chamados)
    df = inferir_distrito(df)
    return marcar_repeticoes(df)


def adicionar_celulas(chamados: pd.DataFrame) -> pd.DataFrame:
    assert chamados[["lat", "lon"]].notna().all().all(), "geo espera a silver validada"
    df = chamados.copy()
    for res in RESOLUCOES:
        df[f"celula_r{res}"] = pd.array(
            [h3.latlng_to_cell(lat, lon, res) for lat, lon in zip(df["lat"], df["lon"])], dtype="string")
    return df


def inferir_distrito(df: pd.DataFrame) -> pd.DataFrame:
    """Preenche distrito_inferido, confianca_distrito e nivel_distrito para quem não tem distrito
    (nulos para os informados) e monta distrito_final e origem_distrito.

    Os sem votos ficam com distrito_final e origem_distrito nulos.
    """
    df = df.copy()
    eleitores = df[df["distrito"].notna()]
    alvos = df[df["distrito"].isna()]
    resultado = pd.DataFrame(index=alvos.index, columns=["distrito_inferido", "confianca_distrito", "nivel_distrito"])
    for res, k in NIVEIS_VOTACAO:
        faltam = resultado["distrito_inferido"].isna()
        if not faltam.any():
            break
        votos = _votar(alvos.loc[faltam, f"celula_r{res}"], eleitores[f"celula_r{res}"], eleitores["distrito"], k)
        votos["nivel_distrito"] = f"r{res} k={k}"
        resultado.update(votos)

    df["distrito_inferido"] = resultado["distrito_inferido"].reindex(df.index).astype("string")
    df["confianca_distrito"] = resultado["confianca_distrito"].reindex(df.index).astype("float64")
    df["nivel_distrito"] = resultado["nivel_distrito"].reindex(df.index).astype("string")
    sem_distrito = df["distrito"].isna()
    df["flag_sem_votos"] = sem_distrito & df["distrito_inferido"].isna()  # provável erro de geocodificação
    df["flag_distrito_divisa"] = (df["confianca_distrito"] < CONFIANCA_MINIMA).fillna(False).astype(bool)

    df["distrito_final"] = df["distrito"].fillna(df["distrito_inferido"])
    df["origem_distrito"] = pd.Series(np.select(
        [df["distrito"].notna(), df["distrito_inferido"].notna()], ["informado", "inferido"], default=None),
        index=df.index, dtype="string")
    return df


def marcar_repeticoes(df: pd.DataFrame) -> pd.DataFrame:
    """dist_vizinho_m: distância ao chamado mais próximo na mesma rua em ±JANELA_REPETICAO_DIAS
    (nula se não houver nenhum no alcance da busca). flag_repeticao: esse vizinho está a até
    LIMITE_REPETICAO_M."""
    df = df.copy()
    coluna = f"celula_r{RESOLUCAO_REPETICAO}"
    k = k_para_raio(LIMITE_REPETICAO_M, RESOLUCAO_REPETICAO)
    base = df.loc[df["logradouro"].notna(), ["lat", "lon", "data_abertura", "logradouro", coluna]].copy()
    base["rua"] = base["logradouro"].map({v: normalizar(v) for v in base["logradouro"].unique()})
    base["id"] = base.index

    busca = base.assign(celula_busca=base[coluna].map(lambda c: list(h3.grid_disk(c, k)))).explode("celula_busca")
    pares = busca.merge(base, left_on=["celula_busca", "rua"], right_on=[coluna, "rua"], suffixes=("", "_viz"))
    dias = (pares["data_abertura"] - pares["data_abertura_viz"]).abs().dt.days
    pares = pares[(pares["id"] != pares["id_viz"]) & (dias <= JANELA_REPETICAO_DIAS)]
    distancia = distancia_m(pares["lat"], pares["lon"], pares["lat_viz"], pares["lon_viz"])

    df["dist_vizinho_m"] = distancia.groupby(pares["id"]).min().reindex(df.index).astype("float64")
    df["flag_repeticao"] = (df["dist_vizinho_m"] <= LIMITE_REPETICAO_M).fillna(False).astype(bool)
    return df


def distancia_m(lat1, lon1, lat2, lon2):
    """Haversine vetorizado, em metros."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * RAIO_TERRA_M * np.arcsin(np.sqrt(a))


def raio_garantido_m(res: int, k: int) -> float:
    """Distância que o grid_disk(k) cobre a partir de QUALQUER ponto da célula central.

    O pior caso é um ponto num vértice da célula: dali, a borda do disco fica a k arestas
    (as "reentrâncias" entre as células externas). Medido por simulação: com r10, k=1 cobre
    ~76 m sem perdas e k=2 cobre 160 m. Dividido por MARGEM_RAIO pela variação de tamanho.
    """
    return k * h3.average_hexagon_edge_length(res, unit="m") / MARGEM_RAIO


def k_para_raio(raio_m: float, res: int) -> int:
    """Menor k cujo disco cobre raio_m com folga (se LIMITE_REPETICAO_M mudar, a busca acompanha)."""
    k = 1
    while raio_garantido_m(res, k) < raio_m:
        k += 1
    return k


# ----------------------------------------------------------------- auxiliares
def _votar(celulas_alvo: pd.Series, celulas_eleitores: pd.Series, distritos: pd.Series, k: int) -> pd.DataFrame:
    """Vencedor e proporção de votos para cada alvo, no disco de raio k da sua célula."""
    votos = pd.DataFrame({"celula": celulas_eleitores, "distrito": distritos}) \
        .groupby(["celula", "distrito"]).size().rename("n").reset_index()
    disco = celulas_alvo.map(lambda c: list(h3.grid_disk(c, k))).explode().rename("celula")
    apuracao = (disco.rename_axis("alvo").reset_index()
                .merge(votos, on="celula")
                .groupby(["alvo", "distrito"])["n"].sum().reset_index())
    apuracao["confianca_distrito"] = apuracao["n"] / apuracao.groupby("alvo")["n"].transform("sum")
    vencedor = apuracao.sort_values("n", ascending=False).drop_duplicates("alvo").set_index("alvo")
    return vencedor.rename(columns={"distrito": "distrito_inferido"})[["distrito_inferido", "confianca_distrito"]]
