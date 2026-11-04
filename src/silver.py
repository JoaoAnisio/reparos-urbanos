"""Zona silver: lê a versão vigente da bronze e devolve os chamados de tapa-buraco num schema fixo.

Regras:
- Escopo: lista explícita de serviços (SERVICOS_ESCOPO). Serviço com "buraco" fora da lista gera aviso.
- Nenhuma linha do escopo é descartada: data ilegível vira NaT, status desconhecido vira nulo,
  canal desconhecido vira "outros", coordenada 0 vira nula.
- data_extracao é ESTIMADA pela maior data presente no arquivo (ver _data_extracao).
- Validação (coordenada fora de SP, data inválida...) e subprefeitura ficam para a etapa 3c.
"""
import logging
from pathlib import Path

import pandas as pd

from src.comum import ler_manifesto, normalizar
from src.ingest import BRONZE, versao_vigente

TAMANHO_BLOCO = 100_000

# Comparados depois de normalizar (sem acento, minúsculo, espaços simples).
SERVICOS_ESCOPO = {
    "tapa-buraco",
    "tapa-buraco em faixa exclusiva ou corredor de onibus",
}
STATUS = {
    "aberto": "aberto",
    "aberta": "aberto",
    "em andamento": "aberto",
    "em aprovacao": "aberto",
    "finalizada": "finalizado",
    "finalizado": "finalizado",
    "cancelada": "cancelado",
    "cancelado": "cancelado",
    # Indeferido = o órgão recusou o pedido. Como no cancelado, o reparo não aconteceu.
    # Documentado no glossário, mas ainda não observado no escopo.
    "indeferido": "cancelado",
    "indeferida": "cancelado",
}
# Campos do manifesto que a silver usa. Manifesto antigo sem algum deles -> reingerir.
CAMPOS_MANIFESTO = ("formato_data", "encoding", "separador", "abertura_max")
CANAIS = {"portal": "portal", "mobile": "mobile", "crm": "central", "chatbot": "chatbot"}

# nome normalizado no arquivo -> nome intermediário (antes das regras de cada coluna)
COLUNAS_ORIGEM = {
    "data de abertura": "data_abertura",
    "data de finalizacao": "data_finalizacao",
    "meio de comunicacao": "canal",
    "servico": "servico",
    "status": "status_original",
    "orgao": "orgao",
    "logradouro": "logradouro",
    "latitude": "lat",
    "longitude": "lon",
    "distrito": "distrito",
}
SCHEMA = [
    "data_abertura", "data_finalizacao", "servico", "flag_corredor", "status", "status_original",
    "canal", "orgao", "logradouro", "lat", "lon", "distrito",
    "trimestre", "versao_bronze", "data_extracao",
]

log = logging.getLogger("silver")


# ----------------------------------------------------------------- funções públicas
def ler_trimestre(trimestre: str, bronze: Path = BRONZE) -> pd.DataFrame:
    """Lê a versão vigente do trimestre em blocos, filtra o escopo e devolve a tabela no SCHEMA."""
    versao = versao_vigente(trimestre, bronze=bronze)
    manifesto = ler_manifesto(versao)
    for chave in CAMPOS_MANIFESTO:
        if chave not in manifesto:
            raise ValueError(f"{trimestre}: manifesto de {versao.name} sem '{chave}'. Reingira o arquivo.")

    arquivo = versao / manifesto["arquivo"]
    opcoes = {"sep": manifesto["separador"], "encoding": manifesto["encoding"], "dtype": str}
    nomes = {normalizar(c): c for c in pd.read_csv(arquivo, nrows=0, **opcoes).columns}
    faltando = set(COLUNAS_ORIGEM) - set(nomes)
    if faltando:
        raise ValueError(f"{trimestre}: colunas ausentes no arquivo: {sorted(faltando)}")

    blocos, fora_da_lista = [], set()
    leitor = pd.read_csv(arquivo, usecols=[nomes[c] for c in COLUNAS_ORIGEM], chunksize=TAMANHO_BLOCO, **opcoes)
    for bloco in leitor:
        bloco = bloco.rename(columns={nomes[c]: novo for c, novo in COLUNAS_ORIGEM.items()})
        chave = _chave(bloco["servico"])
        no_escopo = chave.isin(SERVICOS_ESCOPO)
        parecidos = bloco.loc[~no_escopo & chave.str.contains("buraco", na=False), "servico"]
        fora_da_lista.update(parecidos.unique())
        blocos.append(bloco[no_escopo])

    if fora_da_lista:
        log.warning("%s: serviços com 'buraco' fora de SERVICOS_ESCOPO (ignorados): %s",
                    trimestre, sorted(fora_da_lista))
    bruto = pd.concat(blocos, ignore_index=True)
    return _transformar(bruto, manifesto)


# ----------------------------------------------------------------- regras por coluna
def _transformar(bruto: pd.DataFrame, manifesto: dict) -> pd.DataFrame:
    trimestre = manifesto["trimestre"]
    df = pd.DataFrame(index=bruto.index)

    df["data_abertura"] = _data(bruto["data_abertura"], manifesto["formato_data"], "data_abertura", trimestre)
    df["data_finalizacao"] = _data(bruto["data_finalizacao"], manifesto["formato_data"], "data_finalizacao", trimestre)

    df["servico"] = _espacos(bruto["servico"])
    df["flag_corredor"] = df["servico"].str.contains("corredor", case=False).fillna(False).astype(bool)

    chave_status = _chave(bruto["status_original"])
    df["status"] = chave_status.map(STATUS).astype("string")
    desconhecidos = bruto.loc[chave_status.notna() & df["status"].isna(), "status_original"].unique()
    if len(desconhecidos):
        log.warning("%s: status sem mapeamento (ficam nulos): %s", trimestre, sorted(desconhecidos))
    df["status_original"] = bruto["status_original"].astype("string")

    chave_canal = _chave(bruto["canal"])
    canal = chave_canal.map(CANAIS)
    canal[chave_canal.notna() & canal.isna()] = "outros"
    df["canal"] = canal.astype("string")

    df["orgao"] = _espacos(bruto["orgao"])
    df["logradouro"] = _espacos(bruto["logradouro"])
    df["lat"] = _coordenada(bruto["lat"])
    df["lon"] = _coordenada(bruto["lon"])
    df["distrito"] = _chave(bruto["distrito"]).str.upper()

    df["trimestre"] = pd.Series(trimestre, index=df.index, dtype="string")
    df["versao_bronze"] = pd.Series(manifesto["versao"], index=df.index, dtype="string")
    df["data_extracao"] = _data_extracao(manifesto)
    return df[SCHEMA]


def _data_extracao(manifesto: dict) -> pd.Timestamp:
    """Estimativa da data em que a prefeitura gerou o arquivo (sem fuso, como as outras datas).

    A data real é >= qualquer data contida no arquivo, então usamos a maior entre a última
    abertura e a última finalização (limite inferior). NÃO usar "ingerido_em": é quando NÓS
    rodamos a ingestão, e faria todo chamado aberto parecer mais antigo do que é.
    """
    candidatas = [manifesto.get("abertura_max"), manifesto.get("finalizacao_max")]
    datas = [pd.Timestamp(d) for d in candidatas if d]
    if not datas:
        raise ValueError(f"{manifesto['trimestre']}: manifesto sem datas para estimar a extração.")
    return max(datas)


def _data(serie: pd.Series, formato: str, coluna: str, trimestre: str) -> pd.Series:
    datas = pd.to_datetime(serie, format=formato, errors="coerce")
    invalidas = int((serie.notna() & datas.isna()).sum())
    if invalidas:
        log.warning("%s: %d valores ilegíveis em %s (viram NaT)", trimestre, invalidas, coluna)
    return datas


def _chave(serie: pd.Series) -> pd.Series:
    """Texto normalizado para comparação.

    Normaliza só os valores DISTINTOS (poucas centenas) e aplica via dicionário nas
    milhões de linhas: baixa cardinalidade. astype("string") porque coluna toda nula vira float.
    """
    mapa = {v: normalizar(v) for v in serie.dropna().unique()}
    return serie.map(mapa).astype("string")


def _espacos(serie: pd.Series) -> pd.Series:
    """Troca qualquer sequência de espaços por um só e apara as pontas; texto vazio vira nulo."""
    limpo = serie.astype("string").str.replace(r"\s+", " ", regex=True).str.strip()
    return limpo.replace("", pd.NA)


def _coordenada(serie: pd.Series) -> pd.Series:
    # Vírgula decimal é aceita por segurança: os arquivos latin-1/";" vêm de planilha.
    texto = serie.astype("string").str.replace(",", ".", regex=False)
    numeros = pd.to_numeric(texto, errors="coerce").astype("float64")
    return numeros.mask(numeros == 0)