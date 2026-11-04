"""Ingestão na zona bronze: cópia fiel do arquivo + manifesto, particionada por trimestre.

Regras:
- O trimestre é detectado a partir das datas do próprio arquivo (nunca informado à mão).
- Arquivo idêntico à versão vigente -> ignorado (retorna None).
- Arquivo idêntico a uma versão ANTIGA -> recusado (evita "voltar no tempo").
- Arquivo com datas de mais de um trimestre -> recusado.
- Nova versão de um trimestre existente -> gravada ao lado das antigas e passa a ser a vigente.
"""
import hashlib
import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.comum import MANIFESTO, ler_manifesto, normalizar

RAIZ = Path(__file__).resolve().parent.parent
BRONZE = RAIZ / "data" / "bronze" / "sp156"
PADRAO_TRIMESTRE = re.compile(r"^\d{4}T[1-4]$")
FORMATO_VERSAO = "%Y%m%dT%H%M%S%fZ"   # MUDANÇA: microssegundos evitam colisão no mesmo segundo
# O formato muda entre publicações: 2026T3 usa mm/dd, arquivos anteriores usam dd/mm.
FORMATOS_DATA = ("%m/%d/%Y", "%d/%m/%Y")
MAX_DATAS_INVALIDAS = 0.01             # mais de 1% de datas ilegíveis -> recusa
COLUNA_ABERTURA = "data de abertura"
COLUNA_FINALIZACAO = "data de finalizacao"

log = logging.getLogger("ingest")


# ----------------------------------------------------------------- funções públicas
def ingerir(caminho_arquivo: Path, bronze: Path = BRONZE) -> Path | None:
    """Copia o arquivo para a bronze. Retorna a pasta da versão criada,
    ou None se o arquivo for idêntico à versão vigente."""
    caminho_arquivo = Path(caminho_arquivo)
    if not caminho_arquivo.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho_arquivo}")

    # MUDANÇA 1: o trimestre vem dos dados, não de quem chama a função
    perfil = _perfilar(caminho_arquivo)
    trimestre = perfil["trimestre"]
    sha256 = _sha256(caminho_arquivo)
    pasta_trimestre = bronze / f"trimestre={trimestre}"

    # MUDANÇA 2: compara com TODAS as versões do trimestre, não só com a vigente
    versoes = _versoes_validas(pasta_trimestre)
    if versoes:
        vigente = max(versoes, key=lambda p: p.name)
        for versao_existente in versoes:
            if ler_manifesto(versao_existente).get("sha256") != sha256:
                continue
            if versao_existente == vigente:
                log.info("Já ingerido: idêntico à versão vigente %s", vigente.name)
                return None
            raise ValueError(
                f"Arquivo idêntico a uma versão ANTIGA ({versao_existente.name}) do trimestre "
                f"{trimestre}. A vigente é {vigente.name}. Reingerir faria a pipeline voltar no tempo."
            )
        # Checagem extra: a "nova" versão deveria ter finalizações até uma data igual ou posterior
        anterior = ler_manifesto(vigente).get("finalizacao_max")
        if anterior and perfil["finalizacao_max"] and perfil["finalizacao_max"] < anterior:
            log.warning(
                "A nova versão tem última finalização (%s) anterior à da vigente (%s). "
                "Confira se este download é mesmo o mais recente.", perfil["finalizacao_max"], anterior)

    agora = datetime.now(timezone.utc)
    versao = agora.strftime(FORMATO_VERSAO)
    temporaria = pasta_trimestre / f".tmp_{versao}"
    destino = pasta_trimestre / f"versao={versao}"

    temporaria.mkdir(parents=True)
    try:
        shutil.copy2(caminho_arquivo, temporaria / caminho_arquivo.name)
        manifesto = {
            "trimestre": trimestre,
            "versao": versao,
            "arquivo": caminho_arquivo.name,   # MUDANÇA: sem caminho absoluto (expunha o usuário)
            "sha256": sha256,
            "tamanho_bytes": caminho_arquivo.stat().st_size,
            **{k: v for k, v in perfil.items() if k != "trimestre"},
            "ingerido_em": agora.isoformat(),
        }
        (temporaria / MANIFESTO).write_text(
            json.dumps(manifesto, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        temporaria.rename(destino)
    except Exception:
        shutil.rmtree(temporaria, ignore_errors=True)
        raise

    log.info("Ingerido %s -> %s/%s", caminho_arquivo.name, pasta_trimestre.name, destino.name)
    return destino


def versao_vigente(trimestre: str, bronze: Path = BRONZE) -> Path:
    """Retorna a pasta da versão mais recente de um trimestre (ex.: '2026T3')."""
    _validar_trimestre(trimestre)
    versoes = _versoes_validas(bronze / f"trimestre={trimestre}")
    if not versoes:
        raise FileNotFoundError(f"Nenhuma versão válida encontrada para o trimestre {trimestre!r}")
    return max(versoes, key=lambda p: p.name)


# ----------------------------------------------------------------- detecção do trimestre
def _perfilar(caminho: Path) -> dict:
    """Lê as colunas de data, serviço e status e devolve o trimestre e um resumo para o manifesto."""
    encoding, sep, cabecalho = _detectar_formato(caminho)
    nomes = {normalizar(c): c for c in cabecalho}

    if COLUNA_ABERTURA not in nomes:
        raise ValueError(f"Coluna 'Data de Abertura' não encontrada. Colunas: {cabecalho}")
    if "servico" not in nomes or "status" not in nomes:
        raise ValueError(f"Colunas 'Serviço' ou 'Status' não encontradas. Colunas: {cabecalho}")

    # Serviço e Status nunca são nulos em linhas reais (Etapa 1): servem para reconhecer enchimento.
    colunas = [nomes[COLUNA_ABERTURA], nomes["servico"], nomes["status"]]
    if COLUNA_FINALIZACAO in nomes:
        colunas.append(nomes[COLUNA_FINALIZACAO])

    df = pd.read_csv(caminho, sep=sep, encoding=encoding, usecols=colunas, dtype=str)

    # Linhas sem data, serviço e status são enchimento de planilha (ex.: 2025T1), não dados.
    vazia = df[[nomes[COLUNA_ABERTURA], nomes["servico"], nomes["status"]]].isna().all(axis=1)
    dados = df[~vazia]
    linhas_vazias = int(vazia.sum())
    if linhas_vazias:
        log.warning("%d linhas vazias (sem data, serviço e status) em %s", linhas_vazias, caminho.name)

    # Só é truncamento se as linhas COM dados batem no limite do Excel.
    if len(dados) == 1_048_575:
        raise ValueError("Arquivo com exatamente 1.048.575 linhas com dados: limite do Excel. "
                         "Provável truncamento.")

    formato, abertura, trimestre = _interpretar_datas(dados[nomes[COLUNA_ABERTURA]])

    finalizacao_max = None
    if COLUNA_FINALIZACAO in nomes:
        fim = pd.to_datetime(dados[nomes[COLUNA_FINALIZACAO]], format=formato, errors="coerce")
        if fim.notna().any():
            finalizacao_max = fim.max().date().isoformat()

    return {
        "trimestre": trimestre,
        "formato_data": formato,
        "linhas": len(dados),
        "linhas_vazias": linhas_vazias,
        "abertura_min": abertura.min().date().isoformat(),
        "abertura_max": abertura.max().date().isoformat(),
        "finalizacao_max": finalizacao_max,
        "datas_abertura_invalidas": int(abertura.isna().sum()),
        "encoding": encoding,
        "separador": sep,
    }


def _interpretar_datas(serie: pd.Series) -> tuple[str, pd.Series, str]:
    """Testa cada formato de data e fica com o único que gera datas válidas E um só trimestre."""
    preenchidas = serie.dropna()
    preenchidas = preenchidas[preenchidas.str.strip() != ""]
    if preenchidas.empty:
        raise ValueError("Coluna 'Data de Abertura' está vazia.")

    aprovados, diagnostico = [], []
    for formato in FORMATOS_DATA:
        datas = pd.to_datetime(serie, format=formato, errors="coerce")
        taxa_invalida = 1 - datas.notna().sum() / len(serie)
        trimestres = datas.dropna().dt.to_period("Q").astype(str).str.replace("Q", "T").unique()
        diagnostico.append(f"{formato}: {taxa_invalida:.1%} inválidas, trimestres {sorted(trimestres)}")
        if taxa_invalida <= MAX_DATAS_INVALIDAS and len(trimestres) == 1:
            aprovados.append((formato, datas, trimestres[0]))

    if len(aprovados) == 1:
        return aprovados[0]
    if len(aprovados) > 1:
        raise ValueError(f"Formato de data ambíguo (mais de um formato serve): {diagnostico}")
    raise ValueError("Nenhum formato de data produz um trimestre único com datas válidas. "
                     "Exemplo de valor: " + repr(preenchidas.iloc[0]) + ". " + " | ".join(diagnostico))


def _detectar_formato(caminho: Path) -> tuple[str, str, list[str]]:
    """Descobre codificação e separador olhando só a primeira linha."""
    with caminho.open("rb") as f:
        primeira = f.readline()
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            linha = primeira.decode(encoding).strip()
            break
        except UnicodeDecodeError:
            continue
    sep = ";" if linha.count(";") > linha.count(",") else ","
    cabecalho = [c.strip().strip('"') for c in linha.split(sep)]
    return encoding, sep, cabecalho


# ----------------------------------------------------------------- auxiliares
def _sha256(caminho: Path, bloco: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        while pedaco := f.read(bloco):
            h.update(pedaco)
    return h.hexdigest()


def _versoes_validas(pasta_trimestre: Path) -> list[Path]:
    return [p for p in pasta_trimestre.glob("versao=*") if _versao_valida(p)]


def _validar_trimestre(trimestre: str) -> None:
    if not PADRAO_TRIMESTRE.match(trimestre):
        raise ValueError(f"Trimestre inválido: {trimestre!r}. Use o formato 2026T3.")


def _versao_valida(pasta: Path) -> bool:
    manifesto = pasta / MANIFESTO
    if not manifesto.exists():
        return False
    try:
        dados = json.loads(manifesto.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    arquivo = pasta / dados.get("arquivo", "")
    return arquivo.is_file()