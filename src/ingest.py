import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BRONZE = RAIZ / "data" / "bronze" / "sp156"
PADRAO_TRIMESTRE = re.compile(r"^\d{4}T[1-4]$")
FORMATO_VERSAO = "%Y%m%dT%H%M%SZ"
MANIFESTO = "_manifest.json"


def _sha256(caminho: Path, bloco: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        while pedaco := f.read(bloco):
            h.update(pedaco)
    return h.hexdigest()


def ingerir(caminho_arquivo: Path, trimestre: str) -> Path | None:
    """Copia o arquivo para a bronze. Retorna a pasta da versão criada,
    ou None se um arquivo idêntico já tiver sido ingerido."""
    caminho_arquivo = Path(caminho_arquivo)
    _validar_trimestre(trimestre)
    if not caminho_arquivo.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho_arquivo}")

    sha256 = _sha256(caminho_arquivo)

    try:
        vigente = versao_vigente(trimestre)
    except FileNotFoundError:
        vigente = None  # primeira ingestão deste trimestre
    if vigente is not None:
        manifesto_vigente = json.loads((vigente / MANIFESTO).read_text(encoding="utf-8"))
        if manifesto_vigente.get("sha256") == sha256:
            return None

    agora = datetime.now(timezone.utc)
    versao = agora.strftime(FORMATO_VERSAO)
    pasta_trimestre = BRONZE / f"trimestre={trimestre}"
    temporaria = pasta_trimestre / f".tmp_{versao}"
    destino = pasta_trimestre / f"versao={versao}"

    temporaria.mkdir(parents=True)
    try:
        shutil.copy2(caminho_arquivo, temporaria / caminho_arquivo.name)
        manifesto = {
            "trimestre": trimestre,
            "versao": versao,
            "arquivo": caminho_arquivo.name,
            "arquivo_origem": str(caminho_arquivo.resolve()),
            "sha256": sha256,
            "tamanho_bytes": caminho_arquivo.stat().st_size,
            "ingerido_em": agora.isoformat(),
        }
        (temporaria / MANIFESTO).write_text(
            json.dumps(manifesto, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        temporaria.rename(destino)
    except Exception:
        shutil.rmtree(temporaria, ignore_errors=True)
        raise

    return destino


def versao_vigente(trimestre: str) -> Path:
    """Retorna a pasta da versão mais recente de um trimestre (ex.: '2026T3')."""
    _validar_trimestre(trimestre)
    pasta_trimestre = BRONZE / f"trimestre={trimestre}"
    validas = [p for p in pasta_trimestre.glob("versao=*") if _versao_valida(p)]
    if not validas:
        raise FileNotFoundError(
            f"Nenhuma versão válida encontrada para o trimestre {trimestre!r}"
        )
    return max(validas, key=lambda p: p.name)




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

