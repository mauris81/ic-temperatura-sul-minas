"""Reconstrução da série de uma estação do INMET a partir do ERA5-Land, e o teste de acerto.

Métodos comparados (todos aprendem só com os anos de treino):

- ``cru``: ERA5-Land sem correção;
- ``mes``: ERA5-Land menos o viés médio (modelo − estação) de cada mês;
- ``quantis``: mapeamento de quantis empírico mês a mês (fora da faixa, mantém a diferença do extremo);
- ``backcast``: só a estação, série invertida no tempo e prevista "para frente" com MSTL + ETS
  (Hyndman et al., FPP, seção 13.6); depois a previsão é desinvertida.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import ondas

VARS = ("tmax", "tmin")
QUANTIS = np.linspace(0.01, 0.99, 99)


def pares(obs: pd.DataFrame, mod: pd.DataFrame) -> pd.DataFrame:
    """Dias em que há estação e modelo: colunas ``tmax_obs``, ``tmax_mod``, ``tmin_obs``, ``tmin_mod``."""
    return obs.merge(mod, on="data", suffixes=("_obs", "_mod"))


def corrige_mes(mod: pd.DataFrame, par_treino: pd.DataFrame) -> pd.DataFrame:
    """ERA5-Land menos o viés médio de cada mês, calculado nos pares de treino."""
    out = mod.copy()
    for v in VARS:
        p = par_treino.dropna(subset=[f"{v}_obs", f"{v}_mod"])
        vies = (p[f"{v}_mod"] - p[f"{v}_obs"]).groupby(p["data"].dt.month).mean()
        out[v] = mod[v] - mod["data"].dt.month.map(vies)
    return out


def corrige_quantis(mod: pd.DataFrame, par_treino: pd.DataFrame) -> pd.DataFrame:
    """Mapeamento de quantis empírico, mês a mês (99 quantis, interpolação linear entre eles)."""
    out = mod.copy()
    for v in VARS:
        for m in range(1, 13):
            p = par_treino[par_treino["data"].dt.month == m].dropna(subset=[f"{v}_obs", f"{v}_mod"])
            qm, qo = np.quantile(p[f"{v}_mod"], QUANTIS), np.quantile(p[f"{v}_obs"], QUANTIS)
            sel = mod["data"].dt.month == m
            x = mod.loc[sel, v].to_numpy()
            y = np.interp(x, qm, qo)
            y = np.where(x < qm[0], x + qo[0] - qm[0], y)
            out.loc[sel, v] = np.where(x > qm[-1], x + qo[-1] - qm[-1], y)
    return out


def backcast(obs_treino: pd.DataFrame, datas_alvo: pd.DatetimeIndex) -> pd.DataFrame:
    """Previsão "para trás" só com a estação: inverte a série, prevê com MSTL + ETS e desinverte.

    ``datas_alvo`` precisa terminar no dia anterior ao começo do treino. As falhas do treino são
    preenchidas por interpolação linear, porque o modelo não aceita buracos.
    """
    from statsforecast import StatsForecast
    from statsforecast.models import MSTL, AutoETS

    datas_tr = pd.date_range(obs_treino["data"].min(), obs_treino["data"].max())
    if datas_alvo.max() != datas_tr.min() - pd.Timedelta(days=1):
        raise ValueError("as datas a reconstruir devem terminar logo antes do começo do treino")
    out = pd.DataFrame({"data": datas_alvo})
    for v in VARS:
        s = obs_treino.set_index("data")[v].reindex(datas_tr).interpolate(limit_direction="both")
        inv = pd.DataFrame({"unique_id": v, "ds": np.arange(len(s)), "y": s.to_numpy()[::-1]})
        sf = StatsForecast(models=[MSTL(season_length=365, trend_forecaster=AutoETS(model="ZZN"))], freq=1)
        prev = sf.forecast(df=inv, h=len(datas_alvo))
        out[v] = prev["MSTL"].to_numpy()[::-1]  # o 1º passo previsto é o dia logo antes do treino
    return out


def erros(obs: pd.DataFrame, rec: pd.DataFrame) -> pd.DataFrame:
    """Viés, EAM, REQM e correlação (r) da reconstrução contra a estação, por variável."""
    pr = pares(obs, rec)
    linhas = {}
    for v in VARS:
        p = pr[[f"{v}_obs", f"{v}_mod"]].dropna()
        e = p[f"{v}_mod"] - p[f"{v}_obs"]
        linhas[v] = {"vies": e.mean(), "eam": e.abs().mean(), "reqm": np.sqrt((e**2).mean()),
                     "r": p.corr().iloc[0, 1], "n": len(p)}
    return pd.DataFrame(linhas).T


def blocos(obs: pd.DataFrame, mod: pd.DataFrame, lista_blocos) -> dict[str, pd.DataFrame]:
    """Validação cruzada em blocos: cada bloco de anos é escondido e reconstruído com a correção
    calibrada nos outros. Devolve a série reconstruída inteira de cada método."""
    rec = {"mes": [], "quantis": []}
    for a, b in lista_blocos:
        treino = pares(obs[~obs["data"].dt.year.between(a, b)], mod)
        alvo = mod[mod["data"].dt.year.between(a, b)]
        rec["mes"].append(corrige_mes(alvo, treino))
        rec["quantis"].append(corrige_quantis(alvo, treino))
    return {"cru": mod.copy(), **{k: pd.concat(v, ignore_index=True) for k, v in rec.items()}}


def acerto_ondas(obs: pd.DataFrame, rec: pd.DataFrame, lim_obs: pd.DataFrame, lim_rec: pd.DataFrame) -> dict:
    """Compara dias quentes e ondas de calor (critério de Oliveira et al. 2021) da reconstrução com
    os da estação, só nos dias em que a estação tem Tmax e Tmin.

    POD = acertos / dias quentes da estação; FAR = dias quentes só da reconstrução / dias quentes
    da reconstrução; CSI = acertos / dias quentes de qualquer um dos dois.
    """
    obs = obs.dropna(subset=list(VARS))
    rec = rec[rec["data"].isin(set(obs["data"]))]
    q_obs, q_rec = ondas.dias_quentes(obs, lim_obs), ondas.dias_quentes(rec, lim_rec)
    d_obs = set(q_obs.loc[q_obs["quente"], "data"])
    d_rec = set(q_rec.loc[q_rec["quente"], "data"])
    hit = len(d_obs & d_rec)
    ev_obs, ev_rec = ondas.ondas_de_calor(q_obs), ondas.ondas_de_calor(q_rec)
    dias_ev_rec = {d for e in ev_rec.itertuples() for d in pd.date_range(e.inicio, e.fim)}
    achadas = sum(any(d in dias_ev_rec for d in pd.date_range(e.inicio, e.fim)) for e in ev_obs.itertuples())
    return {
        "dias_quentes": len(d_rec), "acertos": hit,
        "pod": hit / len(d_obs) if d_obs else np.nan,
        "far": (len(d_rec) - hit) / len(d_rec) if d_rec else np.nan,
        "csi": hit / len(d_obs | d_rec) if d_obs | d_rec else np.nan,
        "ondas": len(ev_rec), "ondas_obs_achadas": achadas, "ondas_obs": len(ev_obs),
        "intensidade": ev_rec["intensidade"].mean() if len(ev_rec) else np.nan,
    }
