"""Clientes das APIs de temperatura em grade (Open-Meteo e NASA POWER).

Todas as funções devolvem um ``pandas.DataFrame`` diário com as colunas
``data`` (datetime), ``tmax`` e ``tmin`` (°C) e ``fonte``.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import requests

TIMEOUT = 90
FUSO = "America/Sao_Paulo"
CABECALHO = {"User-Agent": "Mozilla/5.0 (IC temperatura Sul de Minas)"}

URL_OM_HISTORICO = "https://archive-api.open-meteo.com/v1/archive"
URL_OM_PREVISAO = "https://api.open-meteo.com/v1/forecast"
URL_POWER = "https://power.larc.nasa.gov/api/temporal/daily/point"


def hoje() -> dt.date:
    return pd.Timestamp.now(tz=FUSO).date()


def ontem() -> dt.date:
    return hoje() - dt.timedelta(days=1)


def _get(url: str, params: dict) -> dict | list:
    r = requests.get(url, params=params, headers=CABECALHO, timeout=TIMEOUT)
    if r.status_code != 200:
        # A Open-Meteo explica o erro em {"error": true, "reason": "..."}
        try:
            motivo = r.json().get("reason", r.text[:200])
        except ValueError:
            motivo = r.text[:200]
        raise RuntimeError(f"{url} respondeu {r.status_code}: {motivo}")
    return r.json()


def _diario(datas, tmax, tmin, fonte: str, formato: str = "%Y-%m-%d") -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "data": pd.to_datetime(datas, format=formato),
            "tmax": pd.Series(tmax, dtype="float64"),
            "tmin": pd.Series(tmin, dtype="float64"),
            "fonte": fonte,
        }
    )
    return df.dropna(subset=["tmax", "tmin"], how="all").reset_index(drop=True)


def open_meteo_historico(
    lat: float, lon: float, inicio: dt.date | str = "1991-01-01", fim: dt.date | str | None = None
) -> pd.DataFrame:
    """Série diária da Historical Weather API (reanálise ERA5 + análise ECMWF IFS).

    Vai de 1940 até ontem; não precisa de chave. É dado de modelo, não de estação.
    """
    js = _get(
        URL_OM_HISTORICO,
        {
            "latitude": lat,
            "longitude": lon,
            "start_date": str(inicio),
            "end_date": str(fim or ontem()),
            "daily": "temperature_2m_max,temperature_2m_min",
            "timezone": FUSO,
        },
    )
    d = js["daily"]
    return _diario(d["time"], d["temperature_2m_max"], d["temperature_2m_min"], "Open-Meteo (histórico)")


def open_meteo_previsao(lat: float, lon: float, dias_passados: int = 14, dias_previsao: int = 7) -> pd.DataFrame:
    """Últimos dias + previsão da Forecast API (atualizada várias vezes por dia).

    A coluna ``previsao`` indica os dias a partir de hoje.
    """
    js = _get(
        URL_OM_PREVISAO,
        {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min",
            "past_days": dias_passados,
            "forecast_days": dias_previsao,
            "timezone": FUSO,
        },
    )
    d = js["daily"]
    df = _diario(d["time"], d["temperature_2m_max"], d["temperature_2m_min"], "Open-Meteo (previsão)")
    df["previsao"] = df["data"].dt.date >= hoje()
    return df


def open_meteo_varios_pontos(
    lats: list[float], lons: list[float], dias_passados: int = 31, dias_previsao: int = 8
) -> pd.DataFrame:
    """Mesma Forecast API, mas para vários pontos numa só requisição (usado no mapa).

    Devolve as colunas ``ponto`` (índice na lista de entrada), ``data``, ``tmax`` e ``tmin``.
    """
    js = _get(
        URL_OM_PREVISAO,
        {
            "latitude": ",".join(f"{v:.4f}" for v in lats),
            "longitude": ",".join(f"{v:.4f}" for v in lons),
            "daily": "temperature_2m_max,temperature_2m_min",
            "past_days": dias_passados,
            "forecast_days": dias_previsao,
            "timezone": FUSO,
        },
    )
    if isinstance(js, dict):  # um ponto só vem como objeto, não lista
        js = [js]
    partes = []
    for i, ponto in enumerate(js):
        d = ponto["daily"]
        df = _diario(d["time"], d["temperature_2m_max"], d["temperature_2m_min"], "Open-Meteo (previsão)")
        df["ponto"] = i
        partes.append(df)
    return pd.concat(partes, ignore_index=True)


def nasa_power(lat: float, lon: float, inicio: dt.date | str, fim: dt.date | str | None = None) -> pd.DataFrame:
    """Série diária da NASA POWER (MERRA-2 + GEOS), grade de ~0,5°, defasagem de ~2-3 dias."""
    js = _get(
        URL_POWER,
        {
            "parameters": "T2M_MAX,T2M_MIN",
            "community": "AG",
            "latitude": lat,
            "longitude": lon,
            "start": str(inicio).replace("-", ""),
            "end": str(fim or ontem()).replace("-", ""),
            "format": "JSON",
        },
    )
    p = js["properties"]["parameter"]
    datas = sorted(p["T2M_MAX"])
    # A POWER marca dado ausente com -999
    tmax = [None if p["T2M_MAX"][k] <= -900 else p["T2M_MAX"][k] for k in datas]
    tmin = [None if p["T2M_MIN"][k] <= -900 else p["T2M_MIN"][k] for k in datas]
    return _diario(datas, tmax, tmin, "NASA POWER", formato="%Y%m%d")


def climatologia_mensal(df: pd.DataFrame, inicio: int = 1991, fim: int = 2020) -> pd.DataFrame:
    """Normal climatológica mensal (média de Tmax e Tmin por mês) no período dado."""
    base = df[df["data"].dt.year.between(inicio, fim)]
    return (
        base.groupby(base["data"].dt.month.rename("mes"))[["tmax", "tmin"]]
        .mean()
        .add_suffix("_normal")
        .reset_index()
    )


def normal_diaria(df: pd.DataFrame, inicio: int = 1991, fim: int = 2020, janela: int = 31) -> pd.DataFrame:
    """Normal diária (índice "mm-dd"), suavizada por média móvel circular de ``janela`` dias."""
    base = df[df["data"].dt.year.between(inicio, fim)]
    clim = base.groupby(base["data"].dt.strftime("%m-%d"))[["tmax", "tmin"]].mean()
    estendida = pd.concat([clim.iloc[-janela:], clim, clim.iloc[:janela]])
    suave = estendida.rolling(janela, center=True).mean().iloc[janela:-janela]
    return suave.add_suffix("_normal")


def com_normal(df: pd.DataFrame, normal: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta a normal mensal e as anomalias ``anom_tmax`` e ``anom_tmin``."""
    out = df.assign(mes=df["data"].dt.month).merge(normal, on="mes", how="left").drop(columns="mes")
    out["anom_tmax"] = out["tmax"] - out["tmax_normal"]
    out["anom_tmin"] = out["tmin"] - out["tmin_normal"]
    return out
