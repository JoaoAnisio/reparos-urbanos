"""Zona silver: lê a versão vigente da bronze e devolve os chamados de tapa-buraco num schema fixo.

Regras:
- Escopo: lista explícita de serviços (SERVICOS_ESCOPO). Serviço com "buraco" fora da lista gera aviso.
- ler_trimestre não descarta nada: data ilegível vira NaT, status desconhecido vira nulo,
  canal desconhecido vira "outros", coordenada 0 vira nula.
- data_extracao é ESTIMADA pela maior data presente no arquivo (ver _data_extracao).
- validar separa válidos e rejeitados; o rejeitado guarda o PRIMEIRO motivo de REGRAS que se aplicar.
- A subprefeitura vem da tabela de referência (seed) REFERENCIA_SUBPREFEITURA, pelo distrito.
- gerar_silver grava chamados.parquet e rejeitados.parquet com escrita atômica, como a bronze,
  e o _manifest.json por último. Sem manifesto (ou com contagens diferentes) = silver incompleta.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.comum import MANIFESTO, ler_manifesto, normalizar
from src.ingest import BRONZE, RAIZ, versao_vigente

TAMANHO_BLOCO = 100_000
SILVER = RAIZ / "data" / "silver"
REFERENCIA_SUBPREFEITURA = RAIZ / "src" / "referencias" / "distrito_subprefeitura.csv"

# Retângulo que envolve o município (Perus ao norte, Marsilac ao sul). É uma aproximação:
# pontos de cidades vizinhas dentro do retângulo passam; o recorte exato exigiria o polígono.
LIMITES_SP = {"lat": (-24.01, -23.35), "lon": (-46.83, -46.36)}

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
SCHEMA_CHAMADOS = SCHEMA + ["subprefeitura", "zona", "flag_finalizado_sem_data", "flag_sem_subprefeitura"]
SCHEMA_REJEITADOS = SCHEMA_CHAMADOS + ["motivo"]

# Ordem importa: o primeiro motivo que se aplicar é o que fica.
REGRAS = [
    ("data de abertura inválida", lambda df: df["data_abertura"].isna()),
    ("finalização anterior à abertura", lambda df: df["data_finalizacao"] < df["data_abertura"]),
    # Só tem efeito com data de extração DECLARADA. Com a estimativa atual (maior data do próprio
    # arquivo) é sempre falsa; o teste com dados sintéticos garante que a lógica funciona.
    ("finalização no futuro", lambda df: df["data_finalizacao"] > df["data_extracao"]),
    ("status inválido", lambda df: df["status"].isna()),
    ("sem coordenada", lambda df: df["lat"].isna() | df["lon"].isna()),
    ("fora do município", lambda df: ~(df["lat"].between(*LIMITES_SP["lat"])
                                       & df["lon"].between(*LIMITES_SP["lon"]))),
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


def anexar_subprefeitura(df: pd.DataFrame, referencia: Path = REFERENCIA_SUBPREFEITURA) -> pd.DataFrame:
    """Acrescenta subprefeitura e zona pelo distrito. Distrito sem correspondência gera aviso."""
    ref = pd.read_csv(referencia, dtype="string")
    juntado = df.merge(ref, on="distrito", how="left", validate="many_to_one")
    sem_par = juntado.loc[juntado["distrito"].notna() & juntado["subprefeitura"].isna(), "distrito"]
    if not sem_par.empty:
        log.warning("Distritos ausentes em %s (%d chamados ficam sem subprefeitura): %s",
                    referencia.name, len(sem_par), sorted(sem_par.unique()))
    return juntado


def validar(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separa (válidos, rejeitados). Espera as colunas de SCHEMA mais subprefeitura e zona."""
    df = df.copy()
    condicoes = [regra(df).fillna(False).to_numpy(dtype=bool) for _, regra in REGRAS]
    motivo = np.select(condicoes, [nome for nome, _ in REGRAS], default="")
    df["flag_finalizado_sem_data"] = df["status"].eq("finalizado").fillna(False).astype(bool) \
        & df["data_finalizacao"].isna()
    # Sem subprefeitura por qualquer motivo: distrito nulo ou ausente da referência.
    df["flag_sem_subprefeitura"] = df["subprefeitura"].isna()

    rejeitado = motivo != ""
    validos = df.loc[~rejeitado, SCHEMA_CHAMADOS].reset_index(drop=True)
    rejeitados = df.loc[rejeitado].assign(motivo=pd.Series(motivo[rejeitado], dtype="string").values)
    return validos, rejeitados[SCHEMA_REJEITADOS].reset_index(drop=True)


def gerar_silver(trimestres: list[str] | None = None, saida: Path = SILVER,
                 bronze: Path = BRONZE) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lê os trimestres (todos, por padrão), valida, anexa a subprefeitura e grava os dois Parquet."""
    if trimestres is None:
        trimestres = sorted(p.name.split("=")[1] for p in bronze.glob("trimestre=*"))
    if not trimestres:
        raise FileNotFoundError(f"Nenhum trimestre na bronze ({bronze}). Rode a ingestão antes.")
    df = pd.concat([ler_trimestre(t, bronze=bronze) for t in trimestres], ignore_index=True)
    validos, rejeitados = validar(anexar_subprefeitura(df))
    manifesto = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "versoes_bronze": df.groupby("trimestre")["versao_bronze"].first().to_dict(),
        "linhas_validas": len(validos),
        "linhas_rejeitadas": len(rejeitados),
        "rejeitados_por_motivo": rejeitados["motivo"].value_counts().to_dict(),
    }
    caminho_manifesto = saida / MANIFESTO
    _gravar_atomico({saida / "chamados.parquet": validos, saida / "rejeitados.parquet": rejeitados},
                    invalidar=caminho_manifesto)
    # Por último: só existe manifesto quando os dois Parquet já são os desta geração.
    temporario = caminho_manifesto.with_name(f".tmp_{MANIFESTO}")
    temporario.write_text(json.dumps(manifesto, indent=2, ensure_ascii=False), encoding="utf-8")
    temporario.replace(caminho_manifesto)
    log.info("Silver gravada em %s: %d válidos, %d rejeitados", saida, len(validos), len(rejeitados))
    return validos, rejeitados


def ler_silver(saida: Path = SILVER, bronze: Path = BRONZE) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Lê (válidos, rejeitados, manifesto) e recusa uma silver incompleta ou inconsistente."""
    if not (saida / MANIFESTO).exists():
        raise FileNotFoundError(f"{saida} sem {MANIFESTO}: silver não gerada ou geração interrompida.")
    manifesto = ler_manifesto(saida)
    validos = pd.read_parquet(saida / "chamados.parquet")
    rejeitados = pd.read_parquet(saida / "rejeitados.parquet")
    obtido = (len(validos), len(rejeitados))
    esperado = (manifesto["linhas_validas"], manifesto["linhas_rejeitadas"])
    if obtido != esperado:
        raise ValueError(f"Silver inconsistente: Parquet com {obtido} linhas, manifesto diz {esperado}.")

    usadas = manifesto.get("versoes_bronze", {})  # manifesto antigo sem o campo: tudo conta como desatualizado
    atuais = {p.name.split("=")[1]: versao_vigente(p.name.split("=")[1], bronze=bronze).name.split("=")[1]
              for p in bronze.glob("trimestre=*")}
    desatualizados = sorted(t for t in atuais if usadas.get(t) != atuais[t])
    if desatualizados:
        log.warning("Silver desatualizada em relação à bronze nos trimestres %s. "
                    "Rode scripts.gerar_silver.", desatualizados)
    return validos, rejeitados, manifesto


def _gravar_atomico(tabelas: dict[Path, pd.DataFrame], invalidar: Path | None = None) -> None:
    """Grava cada tabela num temporário na mesma pasta e só então renomeia para o nome final.

    Os temporários são escritos antes de qualquer rename: se uma escrita falhar, nenhum arquivo
    final é tocado. O rename dentro da mesma pasta é atômico, então quem lê nunca vê um Parquet
    pela metade. `invalidar` (o manifesto) é apagado logo antes das trocas, para que um manifesto
    antigo nunca descreva Parquet novos.
    """
    temporarios = {}
    try:
        for destino, tabela in tabelas.items():
            destino.parent.mkdir(parents=True, exist_ok=True)
            temporario = destino.with_name(f".tmp_{destino.name}")
            tabela.to_parquet(temporario, index=False)
            temporarios[temporario] = destino
        if invalidar is not None:
            invalidar.unlink(missing_ok=True)
        for temporario, destino in temporarios.items():
            temporario.replace(destino)
    except Exception:
        for temporario in temporarios:
            temporario.unlink(missing_ok=True)
        raise


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
    # as_unit("ns"): Timestamp de texto nasce em segundos, que o Parquet não guarda (voltaria em ms).
    return max(datas).as_unit("ns")


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