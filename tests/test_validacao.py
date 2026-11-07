"""Testes das regras de validação e da referência de subprefeitura, com dados sintéticos.

Não dependem da bronze: rodam em qualquer clone.  Uso:  pytest tests/test_validacao.py -v
"""
import json
import logging

import pandas as pd
import pytest

from src.comum import MANIFESTO
from src.silver import (REFERENCIA_SUBPREFEITURA, REGRAS, ESQUEMA, _gravar_atomico, anexar_subprefeitura,
                        ler_silver, reanexar_por_distrito_final, validar)

BASE = {
    "data_abertura": pd.Timestamp("2026-07-10"),
    "data_finalizacao": pd.Timestamp("2026-07-20"),
    "servico": "Tapa-buraco",
    "flag_corredor": False,
    "status": "finalizado",
    "status_original": "Finalizada",
    "canal": "mobile",
    "orgao": "SMSUB",
    "logradouro": "Rua Teste",
    "lat": -23.55,
    "lon": -46.63,
    "distrito": "SE",
    "trimestre": "2026T3",
    "versao_bronze": "20261103T000000000000Z",
    "data_extracao": pd.Timestamp("2026-10-08"),
    "subprefeitura": "SE",
    "zona": "Centro",
}


def chamados(*alteracoes: dict) -> pd.DataFrame:
    """Uma linha por dicionário de alterações sobre BASE."""
    df = pd.DataFrame([{**BASE, **a} for a in alteracoes])
    for coluna in ["data_abertura", "data_finalizacao", "data_extracao"]:
        df[coluna] = pd.to_datetime(df[coluna])
    texto = [c for c in ESQUEMA + ["subprefeitura", "zona"] if df[c].dtype == object]
    return df.astype({c: "string" for c in texto})


@pytest.mark.parametrize("alteracao, motivo", [
    ({"data_abertura": None}, "data de abertura inválida"),
    ({"data_finalizacao": pd.Timestamp("2026-07-01")}, "finalização anterior à abertura"),
    ({"data_finalizacao": pd.Timestamp("2026-11-01")}, "finalização no futuro"),
    ({"status": None}, "status inválido"),
    ({"lat": None}, "sem coordenada"),
    ({"lon": None}, "sem coordenada"),
    ({"lat": -22.9, "lon": -43.2}, "fora do município"),  # Rio de Janeiro
])
def test_cada_regra_rejeita_com_seu_motivo(alteracao, motivo):
    validos, rejeitados = validar(chamados(alteracao))
    assert validos.empty
    assert rejeitados["motivo"].tolist() == [motivo]


def test_fica_o_primeiro_motivo_na_ordem_das_regras():
    _, rejeitados = validar(chamados({"status": None, "lat": None, "data_abertura": None}))
    assert rejeitados["motivo"].tolist() == ["data de abertura inválida"]
    assert REGRAS[0][0] == "data de abertura inválida"


def test_linha_correta_passa_sem_flags():
    validos, rejeitados = validar(chamados({}))
    assert rejeitados.empty and len(validos) == 1
    assert not validos.loc[0, "flag_finalizado_sem_data"] and not validos.loc[0, "flag_sem_subprefeitura"]


def test_flags_mantem_a_linha():
    validos, rejeitados = validar(chamados(
        {"data_finalizacao": None},                                # finalizado sem data
        {"distrito": None, "subprefeitura": None, "zona": None},   # distrito nulo
        {"distrito": "35", "subprefeitura": None, "zona": None},   # distrito fora da referência
        {"status": "aberto", "data_finalizacao": None},            # aberto sem data: normal, sem flag
    ))
    assert rejeitados.empty and len(validos) == 4
    assert validos["flag_finalizado_sem_data"].tolist() == [True, False, False, False]
    assert validos["flag_sem_subprefeitura"].tolist() == [False, True, True, False]


def test_valido_mais_rejeitado_soma_a_entrada():
    df = chamados({}, {"lat": None}, {"data_abertura": None}, {"distrito": None})
    validos, rejeitados = validar(df)
    assert len(validos) + len(rejeitados) == len(df)


def test_referencia_tem_96_distritos_unicos():
    tabela_ref = pd.read_csv(REFERENCIA_SUBPREFEITURA)
    assert list(tabela_ref.columns) == ["distrito", "subprefeitura", "zona"]
    assert len(tabela_ref) == 96 and tabela_ref["distrito"].is_unique
    assert tabela_ref["subprefeitura"].nunique() == 32
    assert set(tabela_ref["zona"]) == {"Centro", "Norte", "Sul", "Leste", "Oeste"}


def test_distrito_sem_par_na_referencia_gera_aviso(caplog):
    df = chamados({}, {"distrito": "DISTRITO INVENTADO"}).drop(columns=["subprefeitura", "zona"])
    with caplog.at_level(logging.WARNING, logger="silver"):
        juntado = anexar_subprefeitura(df)
    assert juntado["subprefeitura"].tolist()[0] == "SE"
    assert pd.isna(juntado["subprefeitura"].tolist()[1])
    assert "DISTRITO INVENTADO" in caplog.text


def _silver_falsa(pasta, validas: int, rejeitadas: int, manifesto: dict | None) -> None:
    pd.DataFrame({"x": range(validas)}).to_parquet(pasta / "chamados.parquet")
    pd.DataFrame({"x": range(rejeitadas)}).to_parquet(pasta / "rejeitados.parquet")
    if manifesto is not None:
        (pasta / MANIFESTO).write_text(json.dumps(manifesto), encoding="utf-8")


def test_ler_silver_aceita_silver_consistente(tmp_path):
    _silver_falsa(tmp_path, 3, 1, {"linhas_validas": 3, "linhas_rejeitadas": 1, "versoes_bronze": {}})
    validos, rejeitados, _ = ler_silver(tmp_path, bronze=tmp_path)  # bronze vazia: não depende dos dados reais
    assert (len(validos), len(rejeitados)) == (3, 1)


def test_ler_silver_recusa_sem_manifesto(tmp_path):
    _silver_falsa(tmp_path, 3, 1, manifesto=None)
    with pytest.raises(FileNotFoundError, match="geração interrompida"):
        ler_silver(tmp_path, bronze=tmp_path)


def test_ler_silver_recusa_contagem_diferente(tmp_path):
    _silver_falsa(tmp_path, 3, 1, {"linhas_validas": 5, "linhas_rejeitadas": 1})
    with pytest.raises(ValueError, match="inconsistente"):
        ler_silver(tmp_path, bronze=tmp_path)


def test_gravacao_apaga_o_manifesto_antigo_antes_de_trocar(tmp_path):
    """Manifesto antigo com as MESMAS contagens não pode sobreviver à troca dos Parquet."""
    _silver_falsa(tmp_path, 1, 1, {"linhas_validas": 1, "linhas_rejeitadas": 1})
    novos = {tmp_path / "chamados.parquet": pd.DataFrame({"x": [9]}),
             tmp_path / "rejeitados.parquet": pd.DataFrame({"x": [9]})}
    _gravar_atomico(novos, invalidar=tmp_path / MANIFESTO)
    assert not (tmp_path / MANIFESTO).exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["chamados.parquet", "rejeitados.parquet"]


def _bronze_falsa(pasta, trimestre: str, versao: str):
    """Uma versão válida da bronze: pasta versao=..., manifesto e o arquivo citado nele."""
    destino = pasta / f"trimestre={trimestre}" / f"versao={versao}"
    destino.mkdir(parents=True)
    (destino / "dados.csv").write_text("x\n1\n", encoding="utf-8")
    (destino / MANIFESTO).write_text(json.dumps({"arquivo": "dados.csv"}), encoding="utf-8")
    return pasta


def test_ler_silver_avisa_quando_a_bronze_tem_versao_mais_nova(tmp_path, caplog):
    silver, bronze = tmp_path / "silver", _bronze_falsa(tmp_path / "bronze", "2026T3", "20261201T000000000000Z")
    silver.mkdir()
    _silver_falsa(silver, 3, 1, {"linhas_validas": 3, "linhas_rejeitadas": 1,
                                 "versoes_bronze": {"2026T3": "20261101T000000000000Z"}})
    with caplog.at_level(logging.WARNING, logger="silver"):
        ler_silver(silver, bronze=bronze)
    assert "desatualizada" in caplog.text and "2026T3" in caplog.text


def test_ler_silver_tolera_manifesto_antigo_sem_versoes(tmp_path, caplog):
    silver, bronze = tmp_path / "silver", _bronze_falsa(tmp_path / "bronze", "2026T3", "20261201T000000000000Z")
    silver.mkdir()
    _silver_falsa(silver, 3, 1, {"linhas_validas": 3, "linhas_rejeitadas": 1})   # sem "versoes_bronze"
    with caplog.at_level(logging.WARNING, logger="silver"):
        validos, _, _ = ler_silver(silver, bronze=bronze)
    assert len(validos) == 3 and "2026T3" in caplog.text


def test_reanexa_subprefeitura_pelo_distrito_final():
    """O distrito inferido também ganha subprefeitura; a flag passa a medir o distrito_final."""
    df = pd.DataFrame({
        "distrito":       pd.array(["REPUBLICA", None, None], dtype="string"),
        "distrito_final": pd.array(["REPUBLICA", "BUTANTA", None], dtype="string"),   # inferido, sem votos
        "subprefeitura":  pd.array(["SE", None, None], dtype="string"),             # feita pelo distrito informado
        "zona":           pd.array(["Centro", None, None], dtype="string"),
        "flag_sem_subprefeitura": [False, True, True],
    }, index=[10, 20, 30])
    resultado = reanexar_por_distrito_final(df)
    assert resultado.index.tolist() == [10, 20, 30], "o índice original precisa voltar"
    assert resultado["subprefeitura"].tolist()[:2] == ["SE", "BUTANTA"]
    assert resultado["zona"].tolist()[:2] == ["Centro", "Oeste"]
    assert resultado["flag_sem_subprefeitura"].tolist() == [False, False, True]
    assert list(resultado.columns).count("subprefeitura") == 1, "não pode duplicar a coluna no merge"


def test_seed_do_dbt_e_igual_a_referencia_da_silver():
    """O seed é uma cópia: se só um dos dois for atualizado, silver e gold usam divisões diferentes."""
    seed = REFERENCIA_SUBPREFEITURA.parents[2] / "dbt_reparos" / "seeds" / "distrito_subprefeitura.csv"
    assert seed.read_bytes() == REFERENCIA_SUBPREFEITURA.read_bytes(), \
        "copie src/referencias/distrito_subprefeitura.csv para dbt_reparos/seeds/ e rode dbt seed"
