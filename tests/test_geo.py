"""Testes do enriquecimento geográfico (src/geo.py), com dados sintéticos: rodam em qualquer clone."""
import h3
import pandas as pd
import pytest
import math

from src.geo import (CONFIANCA_MINIMA, LIMITE_REPETICAO_M, RESOLUCAO_REPETICAO, RESOLUCOES, adicionar_celulas,
                     distancia_m, enriquecer, k_para_raio, raio_garantido_m)

LAT, LON = -23.55, -46.63          # perto da Sé
METRO_LAT = 1 / 111_320            # graus de latitude por metro


def chamado(norte_m=0.0, dia=1, rua="Rua Teste", distrito="SE"):
    return {"lat": LAT + norte_m * METRO_LAT, "lon": LON, "logradouro": rua,
            "data_abertura": pd.Timestamp("2026-07-01") + pd.Timedelta(days=dia - 1), "distrito": distrito}


def tabela(*linhas):
    df = pd.DataFrame(linhas)
    return df.astype({"logradouro": "string", "distrito": "string"})


def test_celulas_nas_resolucoes_certas():
    df = adicionar_celulas(tabela(chamado()))
    for res in RESOLUCOES:
        assert h3.get_resolution(df.loc[0, f"celula_r{res}"]) == res


def test_distancia_m_confere_com_o_h3():
    calculada = distancia_m(LAT, LON, LAT + 100 * METRO_LAT, LON)
    # O h3 usa raio da Terra de 6.371,007 km: diferença de ~0,1 mm em 100 m.
    assert calculada == pytest.approx(h3.great_circle_distance((LAT, LON), (LAT + 100 * METRO_LAT, LON), unit="m"),
                                      rel=1e-5)
    assert calculada == pytest.approx(100, abs=1)


def test_busca_cobre_o_limite_de_repeticao():
    k = k_para_raio(LIMITE_REPETICAO_M, RESOLUCAO_REPETICAO)
    assert raio_garantido_m(RESOLUCAO_REPETICAO, k) >= LIMITE_REPETICAO_M


def test_distrito_inferido_por_unanimidade():
    eleitores = [chamado(norte_m=i, distrito="SE") for i in range(5)]
    df = enriquecer(tabela(*eleitores, chamado(norte_m=2, distrito=None)))
    alvo = df.iloc[-1]
    assert alvo["distrito_inferido"] == "SE" and alvo["confianca_distrito"] == 1.0
    assert not alvo["flag_distrito_divisa"] and not alvo["flag_sem_votos"]
    assert df["distrito_inferido"].iloc[:-1].isna().all(), "quem já tem distrito não recebe inferido"


def test_divisa_quando_o_vencedor_tem_menos_que_o_minimo():
    eleitores = [chamado(norte_m=i, distrito="SE") for i in range(3)] + \
                [chamado(norte_m=i, distrito="REPUBLICA") for i in range(2)]
    alvo = enriquecer(tabela(*eleitores, chamado(norte_m=1, distrito=None))).iloc[-1]
    assert alvo["distrito_inferido"] == "SE"
    assert alvo["confianca_distrito"] == pytest.approx(0.6) and 0.6 < CONFIANCA_MINIMA
    assert alvo["flag_distrito_divisa"]


def test_sem_votos_quando_nao_ha_eleitores_por_perto():
    longe = chamado(norte_m=20_000, distrito=None)          # 20 km: fora de qualquer nível da votação
    alvo = enriquecer(tabela(chamado(), longe)).iloc[-1]
    assert pd.isna(alvo["distrito_inferido"]) and alvo["flag_sem_votos"]


@pytest.mark.parametrize("vizinho, repete", [
    (chamado(norte_m=50, dia=3), True),                        # 50 m, 2 dias depois
    (chamado(norte_m=LIMITE_REPETICAO_M - 1), True),           # no limite
    (chamado(norte_m=LIMITE_REPETICAO_M + 15), False),         # passou do limite
    (chamado(norte_m=50, dia=20), False),                      # fora da janela de 7 dias
    (chamado(norte_m=10, rua="Rua Outra"), False),             # outra rua
    (chamado(norte_m=10, rua="RUA  TESTE"), True),             # mesma rua, grafia diferente
])
def test_repeticao(vizinho, repete):
    df = enriquecer(tabela(chamado(), vizinho))
    assert df["flag_repeticao"].tolist() == [repete, repete], "a flag marca os dois lados do par"


def test_nao_altera_o_dataframe_recebido():
    original = tabela(chamado(), chamado(norte_m=10))
    copia = original.copy()
    enriquecer(original)
    pd.testing.assert_frame_equal(original, copia)

@pytest.mark.parametrize("raio", [50, 80, 120])
def test_disco_cobre_o_raio_em_qualquer_direcao(raio):
    res = RESOLUCAO_REPETICAO
    k = k_para_raio(raio, res)
    lat0, lon0 = -23.55, -46.63
    for passo in range(2000):  # pontos de origem espalhados + 36 direções cada
        lat = lat0 + (passo % 50) * 0.00013
        lon = lon0 + (passo // 50) * 0.00013
        centro = h3.latlng_to_cell(lat, lon, res)
        disco = set(h3.grid_disk(centro, k))
        for grau in range(0, 360, 10):
            ang = math.radians(grau)
            dlat = raio * math.cos(ang) / 111_320
            dlon = raio * math.sin(ang) / (111_320 * math.cos(math.radians(lat)))
            assert h3.latlng_to_cell(lat + dlat, lon + dlon, res) in disco

def test_distrito_final_e_origem():
    eleitores = [chamado(norte_m=i, distrito="REPUBLICA") for i in range(5)]
    inferido = chamado(norte_m=2, distrito=None)
    sem_votos = chamado(norte_m=20_000, distrito=None)
    df = enriquecer(tabela(*eleitores, inferido, sem_votos))
    informado, inf, sem = df.iloc[0], df.iloc[-2], df.iloc[-1]

    assert (informado["distrito_final"], informado["origem_distrito"]) == ("REPUBLICA", "informado")
    assert pd.isna(informado["confianca_distrito"]) and pd.isna(informado["nivel_distrito"])
    assert (inf["distrito_final"], inf["origem_distrito"]) == ("REPUBLICA", "inferido")
    assert pd.isna(sem["distrito_final"]) and pd.isna(sem["origem_distrito"]) and sem["flag_sem_votos"]
    # A subprefeitura é refeita na silver (reanexar_por_distrito_final), não no geo
    assert "subprefeitura" not in df.columns


def test_coordenada_nula_quebra_com_mensagem():
    df = tabela(chamado(), {**chamado(), "lat": None})
    with pytest.raises(AssertionError, match="silver validada"):
        adicionar_celulas(df)


def test_divisa_entra_no_distrito_final_com_a_flag():
    """Decisão: a melhor estimativa fica, com a confiança; quem usa decide se a aceita."""
    eleitores = [chamado(norte_m=i, distrito="SE") for i in range(3)] + \
                [chamado(norte_m=i, distrito="REPUBLICA") for i in range(2)]
    alvo = enriquecer(tabela(*eleitores, chamado(norte_m=1, distrito=None))).iloc[-1]
    assert alvo["flag_distrito_divisa"]
    assert (alvo["distrito_final"], alvo["origem_distrito"]) == ("SE", "inferido")
