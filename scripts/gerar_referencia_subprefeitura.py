"""Gera a tabela de referência (seed) distrito -> subprefeitura -> zona a partir da bronze.

Uso:  python -m scripts.gerar_referencia_subprefeitura

Para cada distrito, fica a subprefeitura mais frequente na coluna "Prefeitura Operacional",
contando TODOS os chamados (a relação é geográfica, não depende do serviço). Rode uma vez,
ou quando a prefeitura mudar a divisão, revise o CSV à mão e faça commit.
"""
import pandas as pd

from src.comum import ler_manifesto, normalizar
from src.ingestao import BRONZE, versao_vigente
from src.silver import REFERENCIA_SUBPREFEITURA

TAMANHO_BLOCO = 500_000
DOMINANCIA_MINIMA = 0.8  # distritos abaixo disso são listados para revisão

# Nomes antigos -> atuais (levantamento do escopo, pergunta 5).
RENOMEACOES = {
    "PERUS": "PERUS-ANHANGUERA",
    "CASA VERDE-CACHOEIRINHA": "CASA VERDE-LIMAO-CACHOEIRINHA",
}

# As 32 subprefeituras e a zona de cada uma. Qualquer outro valor de "Prefeitura Operacional"
# (Superintendencia das Usinas de Asfalto, "Prefeitura Regional nao encontrada", DAEE...) é ignorado.
ZONAS = {
    "SE": "Centro",
    "PERUS-ANHANGUERA": "Norte",
    "PIRITUBA-JARAGUA": "Norte",
    "FREGUESIA-BRASILANDIA": "Norte",
    "CASA VERDE-LIMAO-CACHOEIRINHA": "Norte",
    "SANTANA-TUCURUVI": "Norte",
    "JACANA-TREMEMBE": "Norte",
    "VILA MARIA-VILA GUILHERME": "Norte",
    "LAPA": "Oeste",
    "BUTANTA": "Oeste",
    "PINHEIROS": "Oeste",
    "SANTO AMARO": "Sul",
    "JABAQUARA": "Sul",
    "VILA MARIANA": "Sul",
    "IPIRANGA": "Sul",
    "CIDADE ADEMAR": "Sul",
    "CAMPO LIMPO": "Sul",
    "M BOI MIRIM": "Sul",
    "CAPELA DO SOCORRO": "Sul",
    "PARELHEIROS": "Sul",
    "MOOCA": "Leste",
    "PENHA": "Leste",
    "ERMELINO MATARAZZO": "Leste",
    "SAO MIGUEL": "Leste",
    "ITAIM PAULISTA": "Leste",
    "GUAIANASES": "Leste",
    "ITAQUERA": "Leste",
    "CIDADE TIRADENTES": "Leste",
    "SAO MATEUS": "Leste",
    "ARICANDUVA-FORMOSA-CARRAO": "Leste",
    "VILA PRUDENTE": "Leste",
    "SAPOPEMBA": "Leste",
}


def contar_pares() -> pd.DataFrame:
    """Conta (prefeitura operacional, distrito) em todas as versões vigentes, lendo em blocos."""
    partes = []
    for pasta in sorted(BRONZE.glob("trimestre=*")):
        versao = versao_vigente(pasta.name.split("=")[1])
        man = ler_manifesto(versao)
        opcoes = {"sep": man["separador"], "encoding": man["encoding"], "dtype": str}
        nomes = {normalizar(c): c for c in pd.read_csv(versao / man["arquivo"], nrows=0, **opcoes).columns}
        colunas = [nomes["prefeitura operacional"], nomes["distrito"]]
        for bloco in pd.read_csv(versao / man["arquivo"], usecols=colunas, chunksize=TAMANHO_BLOCO, **opcoes):
            bloco = bloco[colunas].dropna()
            bloco.columns = ["prefeitura", "distrito"]
            partes.append(bloco.value_counts().rename("n").reset_index())
    pares = pd.concat(partes).groupby(["prefeitura", "distrito"])["n"].sum().reset_index()
    # Mesma normalização da silver (maiúsculas, sem acento), para o merge bater.
    pares["prefeitura"] = pares["prefeitura"].map(lambda s: normalizar(s).upper()).replace(RENOMEACOES)
    pares["distrito"] = pares["distrito"].map(lambda s: normalizar(s).upper())
    return pares.groupby(["prefeitura", "distrito"])["n"].sum().reset_index()


def executar() -> None:
    pares = contar_pares()

    codigos = pares["distrito"].str.fullmatch(r"\d+")
    print(f"Distritos numéricos ignorados (códigos, não nomes): {pares.loc[codigos, 'distrito'].nunique()} "
          f"valores, {pares.loc[codigos, 'n'].sum():,} chamados")
    pares = pares[~codigos]

    ignoradas = pares[~pares["prefeitura"].isin(ZONAS)].groupby("prefeitura")["n"].sum()
    print("Valores de 'Prefeitura Operacional' que não são subprefeitura (ignorados):")
    print(ignoradas.sort_values(ascending=False).to_string(), "\n")
    pares = pares[pares["prefeitura"].isin(ZONAS)]

    total = pares.groupby("distrito")["n"].sum()
    dominante = pares.sort_values("n", ascending=False).drop_duplicates("distrito").set_index("distrito")
    tabela_ref = pd.DataFrame({
        "distrito": dominante.index,
        "subprefeitura": dominante["prefeitura"].values,
        "zona": dominante["prefeitura"].map(ZONAS).values,
    }).sort_values("distrito").reset_index(drop=True)
    dominancia = (dominante["n"] / total).reindex(tabela_ref["distrito"])

    faltando = set(ZONAS) - set(tabela_ref["subprefeitura"])
    assert not faltando, f"subprefeituras sem nenhum distrito: {sorted(faltando)}"
    assert len(tabela_ref) == 96, f"esperados 96 distritos, encontrados {len(tabela_ref)}"

    REFERENCIA_SUBPREFEITURA.parent.mkdir(parents=True, exist_ok=True)
    tabela_ref.to_csv(REFERENCIA_SUBPREFEITURA, index=False, encoding="utf-8")
    print(f"Gravado {REFERENCIA_SUBPREFEITURA.relative_to(REFERENCIA_SUBPREFEITURA.parents[2])}: {len(tabela_ref)} distritos\n")

    print("Para revisar à mão — distritos por subprefeitura:")
    for (zona, sub), grupo in tabela_ref.groupby(["zona", "subprefeitura"]):
        print(f"  {zona:6s} {sub:30s} {len(grupo)}: {', '.join(grupo['distrito'])}")
    baixos = dominancia[dominancia < DOMINANCIA_MINIMA]
    print(f"\nDistritos com subprefeitura dominante abaixo de {DOMINANCIA_MINIMA:.0%}:",
          ", ".join(f"{d} ({v:.0%})" for d, v in baixos.items()) or "nenhum")
    print(f"Menor dominância: {dominancia.idxmin()} ({dominancia.min():.1%})")


if __name__ == "__main__":
    executar()
