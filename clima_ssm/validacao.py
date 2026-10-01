"""Comparação entre a série em grade (Open-Meteo) e a observada nas estações do INMET."""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import DADOS, fontes, regiao

ARQ_BDMEP = DADOS / "inmet_bdmep_diario.csv"


def observado() -> pd.DataFrame:
    """Tmax/Tmin diários das estações (gerado por scripts/processar_bdmep.py)."""
    return pd.read_csv(ARQ_BDMEP, parse_dates=["data"], dtype={"codigo": str})


def pareado(codigo: str, obs: pd.DataFrame | None = None) -> pd.DataFrame:
    """Junta, dia a dia, a estação ``codigo`` e a Open-Meteo no ponto da estação."""
    obs = observado() if obs is None else obs
    est = regiao.estacoes().set_index("codigo").loc[codigo]
    o = obs[obs["codigo"] == codigo].dropna(subset=["tmax", "tmin"], how="all")
    if o.empty:
        return pd.DataFrame(columns=["data", "tmax_obs", "tmin_obs", "tmax_mod", "tmin_mod"])
    m = fontes.open_meteo_historico(est["lat"], est["lon"], o["data"].min().date(), o["data"].max().date())
    return o[["data", "tmax", "tmin"]].merge(m[["data", "tmax", "tmin"]], on="data", suffixes=("_obs", "_mod"))


def metricas(par: pd.DataFrame) -> pd.DataFrame:
    """Viés (modelo − estação), erro absoluto médio, RMSE e correlação para Tmax e Tmin."""
    linhas = []
    for v in ("tmax", "tmin"):
        p = par[[f"{v}_obs", f"{v}_mod"]].dropna()
        d = p[f"{v}_mod"] - p[f"{v}_obs"]
        linhas.append(
            {
                "variavel": v.replace("t", "T", 1),
                "n_dias": len(p),
                "vies": d.mean(),
                "mae": d.abs().mean(),
                "rmse": np.sqrt((d**2).mean()),
                "r": p[f"{v}_obs"].corr(p[f"{v}_mod"]) if len(p) > 2 else np.nan,
            }
        )
    return pd.DataFrame(linhas)


def resumo_estacoes() -> pd.DataFrame:
    """Métricas de todas as estações com dados no arquivo do BDMEP."""
    obs = observado()
    est = regiao.estacoes().set_index("codigo")
    partes = []
    for cod in sorted(obs["codigo"].unique()):
        par = pareado(cod, obs)
        if par.empty:
            continue
        m = metricas(par)
        m.insert(0, "estacao", f"{est.loc[cod, 'rotulo']} ({cod})")
        partes.append(m)
    return pd.concat(partes, ignore_index=True)
