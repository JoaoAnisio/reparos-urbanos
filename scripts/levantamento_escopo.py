"""Levantamento do escopo (serviços com "buraco") nas versões vigentes da bronze.

Responde às perguntas que guiaram o desenho da silver:
1. Colunas: os arquivos têm as mesmas colunas depois de normalizar?
2. Serviços: quais nomes contêm "buraco"? Algum serviço do mesmo assunto foi renomeado?
3. Volume: quantos chamados no escopo por trimestre e por mês?
4. Status e canal: quais valores aparecem em cada trimestre?
5. Subprefeitura e distrito: grafias diferentes, renomeações e órgãos que não são subprefeitura.

Uso:  python -m scripts.levantamento_escopo
Só imprime agregados: nenhuma linha com endereço é gravada ou exibida.
"""
import re
from collections import Counter

import pandas as pd

from src.comum import ler_manifesto, normalizar
from src.ingestao import BRONZE, versao_vigente

TAMANHO_BLOCO = 100_000
COLUNAS_ESCOPO = ["data de abertura", "servico", "status", "meio de comunicacao",
                  "prefeitura operacional", "distrito"]
DIAS_NO_TRIMESTRE = {"T1": 90, "T2": 91, "T3": 92, "T4": 92}  # ignora ano bissexto

pd.set_option("display.width", 260)
pd.set_option("display.max_rows", 400)
pd.set_option("display.max_colwidth", 70)


def ler_bronze():
    """Uma passada por trimestre: cabeçalhos, manifestos, linhas do escopo e contagem de serviços."""
    cabecalhos, manifestos, escopo, servicos = {}, {}, [], []
    for pasta in sorted(BRONZE.glob("trimestre=*")):
        tri = pasta.name.split("=")[1]
        versao = versao_vigente(tri)
        man = ler_manifesto(versao)
        manifestos[tri] = man
        leitor = pd.read_csv(versao / man["arquivo"], sep=man["separador"], encoding=man["encoding"],
                             dtype=str, chunksize=TAMANHO_BLOCO)
        partes = []
        for bloco in leitor:
            bloco.columns = [normalizar(c) for c in bloco.columns]
            cabecalhos.setdefault(tri, list(bloco.columns))
            contagem = bloco.groupby(["assunto", "servico"]).size().rename("n").reset_index()
            contagem["trimestre"] = tri
            servicos.append(contagem)
            no_escopo = bloco["servico"].astype("string").str.contains("buraco", case=False, regex=False)
            partes.append(bloco.loc[no_escopo.fillna(False), COLUNAS_ESCOPO])
        df = pd.concat(partes, ignore_index=True)
        df["abertura"] = pd.to_datetime(df["data de abertura"], format=man["formato_data"], errors="coerce")
        df.insert(0, "trimestre", tri)
        escopo.append(df)
        print(f"lido {tri}: {man['linhas']:,} chamados, {len(df):,} no escopo", flush=True)
    servicos = pd.concat(servicos).groupby(["trimestre", "assunto", "servico"])["n"].sum().reset_index()
    return cabecalhos, manifestos, pd.concat(escopo, ignore_index=True), servicos


def por_trimestre(df: pd.DataFrame, coluna: str, tris: list[str]) -> pd.DataFrame:
    """Tabela valor x trimestre, com o total e em quantos trimestres o valor aparece."""
    t = df.groupby([coluna, "trimestre"]).size().unstack("trimestre").reindex(columns=tris).fillna(0).astype(int)
    t["presente_em"] = (t[tris] > 0).sum(axis=1)
    t["total"] = t[tris].sum(axis=1)
    return t.sort_values(["presente_em", "total"], ascending=[True, False])


def titulo(texto: str) -> None:
    print(f"\n{'=' * 100}\n{texto}\n{'=' * 100}")


def q1_colunas(cabecalhos: dict) -> None:
    titulo("1. Colunas (normalizadas) por trimestre")
    tris = list(cabecalhos)
    presenca = Counter(c for t in tris for c in set(cabecalhos[t]))
    print("Em todos os", len(tris), "arquivos:", sorted(c for c, n in presenca.items() if n == len(tris)))
    so_alguns = {c: [t for t in tris if c in cabecalhos[t]] for c, n in presenca.items() if n < len(tris)}
    print("Só em alguns:", so_alguns or "nenhuma")


def q2_servicos(escopo: pd.DataFrame, servicos: pd.DataFrame, tris: list[str]) -> None:
    titulo("2. Serviços com 'buraco' por trimestre")
    print(por_trimestre(escopo, "servico", tris).to_string())
    print("\nTodos os serviços dos assuntos desses chamados (um nome novo sem 'buraco' apareceria aqui):")
    assuntos = escopo.merge(servicos[["assunto", "servico"]].drop_duplicates(), on="servico")["assunto"].unique()
    mesmo_assunto = servicos[servicos["assunto"].isin(assuntos)]
    tabela = mesmo_assunto.pivot_table(index=["assunto", "servico"], columns="trimestre", values="n", aggfunc="sum")
    print(tabela.reindex(columns=tris).fillna(0).astype(int).to_string())
    duplos = [a for a in assuntos if re.search(r"\s{2,}", a)]
    if duplos:
        print("\nAssuntos com espaços duplicados:", [repr(a) for a in duplos])


def q3_volume(escopo: pd.DataFrame, manifestos: dict, tris: list[str]) -> None:
    titulo("3. Volume do escopo por trimestre")
    res = pd.DataFrame(index=tris)
    res["escopo"] = escopo.groupby("trimestre").size()
    for servico, n in escopo.groupby(["trimestre", "servico"]).size().unstack("servico").items():
        res[servico] = n
    res["todos_chamados"] = [manifestos[t]["linhas"] for t in tris]
    res["% do total"] = (res["escopo"] / res["todos_chamados"] * 100).round(1)
    res["por dia"] = [round(res.loc[t, "escopo"] / DIAS_NO_TRIMESTRE[t[-2:]]) for t in tris]
    res["formato_data"] = [manifestos[t]["formato_data"] for t in tris]
    print(res.fillna(0).to_string())
    print("\nPor mês de abertura:")
    print(escopo.groupby(escopo["abertura"].dt.to_period("M")).size().to_string())
    print("Datas de abertura ilegíveis:", int(escopo["abertura"].isna().sum()))


def q4_status_canal(escopo: pd.DataFrame, tris: list[str]) -> None:
    for coluna in ["status", "meio de comunicacao"]:
        titulo(f"4. {coluna} por trimestre (presente_em < {len(tris)} = não aparece em todos)")
        print(por_trimestre(escopo, coluna, tris).to_string())


def q5_territorio(escopo: pd.DataFrame, tris: list[str]) -> None:
    titulo("5. Prefeitura operacional e distrito")
    geo = escopo.dropna(subset=["prefeitura operacional", "distrito"])
    for coluna in ["prefeitura operacional", "distrito"]:
        chave = geo[coluna].map(lambda s: re.sub(r"[^a-z0-9]+", "", normalizar(s)))
        grafias = geo.groupby(chave)[coluna].unique()
        variantes = grafias[grafias.map(len) > 1]
        print(f"{coluna}: {geo[coluna].nunique()} valores; "
              f"grafias diferentes para o mesmo nome: {variantes.tolist() or 'nenhuma'}")

    tabela = por_trimestre(geo, "prefeitura operacional", tris)
    print("\nValores por trimestre:")
    print(tabela.to_string())

    parciais = tabela.index[tabela["presente_em"] < len(tris)]
    print("\nValores que não aparecem em todos os trimestres, com os distritos que atendem "
          "(mesmos distritos sob nomes diferentes = renomeação):")
    for nome in parciais:
        distritos = geo.loc[geo["prefeitura operacional"] == nome, "distrito"].value_counts().head(4)
        print(f"  {nome}: " + ", ".join(f"{d} ({n})" for d, n in distritos.items()))

    nao_sub = geo.loc[geo["prefeitura operacional"].str.contains("[a-z]"), "prefeitura operacional"]
    print("\nValores que não são subprefeitura (escritos com minúsculas):")
    print(nao_sub.value_counts().to_string())

    contagem = geo.groupby(["distrito", "prefeitura operacional"]).size()
    dominante = contagem.groupby("distrito").max().sum() / contagem.sum()
    print(f"\nLinhas na prefeitura mais frequente do próprio distrito: {dominante:.1%}")


def executar() -> None:
    cabecalhos, manifestos, escopo, servicos = ler_bronze()
    tris = list(cabecalhos)
    print(f"\nTotal no escopo: {len(escopo):,} chamados em {len(tris)} trimestres")
    q1_colunas(cabecalhos)
    q2_servicos(escopo, servicos, tris)
    q3_volume(escopo, manifestos, tris)
    q4_status_canal(escopo, tris)
    q5_territorio(escopo, tris)


if __name__ == "__main__":
    executar()