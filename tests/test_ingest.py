"""Roda os 6 testes da ingestão numa bronze TEMPORÁRIA (não toca em data/bronze).

Uso:  python -m tests.test_ingest data/raw/arquivo-final-3-trim-26.csv


As variações (republicação, trimestre misturado, outro trimestre) são geradas
automaticamente a partir do seu arquivo real.
"""
import logging
import re
import sys
import tempfile
from pathlib import Path

from src.ingest import ingerir, versao_vigente  # noqa: E402

logging.basicConfig(level=logging.INFO, format="   [%(levelname)s] %(message)s")
DATA_NO_INICIO = re.compile(r'^("?)(\d{2})/(\d{2})/(\d{4})')


def trocar_mes(linha: str, mes: str) -> str:
    """Troca o mês da primeira data da linha (a coluna Data de Abertura)."""
    return DATA_NO_INICIO.sub(lambda m: f"{m[1]}{mes}/{m[3]}/{m[4]}", linha, count=1)


def main(original: Path) -> None:
    # A pasta temporária (com várias cópias do CSV) é apagada ao sair do with, mesmo se algo falhar.
    with tempfile.TemporaryDirectory(prefix="teste_ingestao_") as pasta:
        _rodar_cenarios(original, Path(pasta))


def _rodar_cenarios(original: Path, tmp: Path) -> None:
    bronze = tmp / "bronze"
    linhas = original.read_text(encoding="utf-8").splitlines(keepends=True)
    cabecalho, dados = linhas[0], linhas[1:]
    ano = DATA_NO_INICIO.match(dados[0])[4]

    # v2 = republicação: o portal acrescenta um chamado (como os "rascunhos" do glossário)
    v2 = tmp / "v2" / original.name
    v2.parent.mkdir()
    v2.write_text("".join(linhas) + dados[-1], encoding="utf-8")

    misto = tmp / "misto.csv"
    misto.write_text(cabecalho + trocar_mes(dados[0], "04") + "".join(dados[1:]), encoding="utf-8")

    # Amostra espalhada pelo arquivo: precisa de dias > 12, senão mm/dd e dd/mm ficam ambíguos.
    # Mês 05 (e não 04) porque a amostra tem dia 31, que não existe em abril.
    outro_tri = tmp / "outro_trimestre.csv"
    outro_tri.write_text(cabecalho + "".join(trocar_mes(l, "05") for l in dados[::100]), encoding="utf-8")

    def rodar(nome, arquivo, esperado):
        print(f"\n{nome}")
        try:
            r = ingerir(arquivo, bronze=bronze)
            resultado = "None (já ingerido)" if r is None else f"versão criada: {r.parent.name}/{r.name}"
        except ValueError as e:
            resultado = f"RECUSADO: {e}"
        print(f"   resultado: {resultado}\n   esperado:  {esperado}")

    rodar("1) Primeira ingestão", original, "versão criada em trimestre=…")
    rodar("2) Mesmo arquivo de novo", original, "None (já ingerido)")
    rodar("3) Republicação (v2)", v2, "segunda versão no mesmo trimestre")
    vig = versao_vigente(_trimestre(dados[0]), bronze=bronze)
    print(f"   vigente agora: {vig.name}  (deve ser a do teste 3)")
    rodar("4) Outro trimestre", outro_tri, f"versão criada em trimestre={ano}T2")
    rodar("5) Arquivo antigo (v1) de novo", original, "RECUSADO: idêntico a uma versão ANTIGA")
    rodar("6) Trimestres misturados", misto, "RECUSADO: mistura trimestres")

    print(f"\nEstrutura gerada em {bronze} (apagada ao final):")
    for p in sorted(bronze.rglob("*")):
        print("   ", p.relative_to(bronze))


def _trimestre(linha: str) -> str:
    m = DATA_NO_INICIO.match(linha)
    return f"{m[4]}T{(int(m[2]) - 1) // 3 + 1}"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: python test_ingest.py caminho/do/arquivo.csv")
    main(Path(sys.argv[1]))