"""Municípios e estações da mesorregião Sul/Sudoeste de Minas (IBGE 3110)."""

from __future__ import annotations

import json
import unicodedata

import pandas as pd
import requests

from . import DADOS

MESORREGIAO = 3110
MUNICIPIO_PADRAO = 3164704  # São Sebastião do Paraíso

URL_IBGE_MUNICIPIOS = f"https://servicodados.ibge.gov.br/api/v1/localidades/mesorregioes/{MESORREGIAO}/municipios"
URL_IBGE_MALHA = f"https://servicodados.ibge.gov.br/api/v3/malhas/mesorregioes/{MESORREGIAO}"
# Coordenadas das sedes municipais (base aberta derivada do IBGE)
URL_SEDES = "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv"

ARQ_MUNICIPIOS = DADOS / "municipios_ssm.csv"
ARQ_MALHA = DADOS / "municipios_ssm.geojson"
ARQ_ESTACOES = DADOS / "estacoes_inmet_ssm.csv"


def municipios() -> pd.DataFrame:
    return pd.read_csv(ARQ_MUNICIPIOS)


def _sem_acento(txt: str) -> str:
    return unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode().upper()


def rotulo_estacao(nome_inmet: str, municipio: str) -> str:
    """O INMET grava nomes em maiúsculas e sem acento; usa o nome do município quando é o mesmo."""
    if _sem_acento(municipio) == nome_inmet.upper():
        return municipio
    particulas = {"Da", "De", "Do", "Das", "Dos"}
    return " ".join(p.lower() if p in particulas else p for p in nome_inmet.title().split())


def estacoes() -> pd.DataFrame:
    est = pd.read_csv(ARQ_ESTACOES, dtype={"codigo": str, "codigo_ibge": "Int64"})
    est["rotulo"] = [rotulo_estacao(n, m) for n, m in zip(est["nome"], est["municipio"])]
    return est


def malha() -> dict:
    return json.loads(ARQ_MALHA.read_text(encoding="utf-8"))


def _area(anel: list) -> float:
    return sum(x0 * y1 - x1 * y0 for (x0, y0, *_), (x1, y1, *_) in zip(anel, anel[1:] + anel[:1])) / 2


def malha_para_plotly(geojson: dict) -> dict:
    """Reorienta os anéis para o padrão do d3-geo/Plotly (externo horário, buracos anti-horários).

    O IBGE segue a RFC 7946 (externo anti-horário); sem isso o Plotly pinta o "mundo menos o município".
    """
    def orientar(pol: list) -> list:
        return [anel[::-1] if (_area(anel) > 0) == (i == 0) else anel for i, anel in enumerate(pol)]

    out = json.loads(json.dumps(geojson))
    for f in out["features"]:
        g = f["geometry"]
        if g["type"] == "Polygon":
            g["coordinates"] = orientar(g["coordinates"])
        elif g["type"] == "MultiPolygon":
            g["coordinates"] = [orientar(p) for p in g["coordinates"]]
    return out


# --- usados por scripts/preparar_regiao.py --------------------------------------


def baixar_municipios() -> pd.DataFrame:
    ibge = requests.get(URL_IBGE_MUNICIPIOS, timeout=60).json()
    lista = pd.DataFrame(
        {
            "codigo_ibge": [m["id"] for m in ibge],
            "nome": [m["nome"] for m in ibge],
            "microrregiao": [m["microrregiao"]["nome"] for m in ibge],
        }
    )
    sedes = pd.read_csv(URL_SEDES, usecols=["codigo_ibge", "latitude", "longitude"])
    sedes = sedes.rename(columns={"latitude": "lat", "longitude": "lon"})
    return lista.merge(sedes, on="codigo_ibge", how="left").sort_values("nome", ignore_index=True)


def baixar_malha(por_municipio: bool = True) -> dict:
    params = {"formato": "application/vnd.geo+json", "qualidade": "minima"}
    if por_municipio:
        params["intrarregiao"] = "municipio"
    return requests.get(URL_IBGE_MALHA, params=params, timeout=60).json()


def _ponto_no_anel(lon: float, lat: float, anel: list) -> bool:
    dentro = False
    j = len(anel) - 1
    for i in range(len(anel)):
        xi, yi = anel[i][0], anel[i][1]
        xj, yj = anel[j][0], anel[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


def municipio_do_ponto(lon: float, lat: float, malha_geojson: dict) -> int | None:
    """Código IBGE do município (polígono) que contém o ponto, ou None."""
    for f in malha_geojson["features"]:
        g = f["geometry"]
        poligonos = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for pol in poligonos:
            if _ponto_no_anel(lon, lat, pol[0]) and not any(_ponto_no_anel(lon, lat, buraco) for buraco in pol[1:]):
                return int(f["properties"]["codarea"])
    return None
