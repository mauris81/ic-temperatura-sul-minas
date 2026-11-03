"""Ondas de calor pelo critério de Oliveira et al. (2021) e tendência de Mann-Kendall/Sen.

Dia quente: Tmax > P90 da Tmax E Tmin > P90 da Tmin do seu dia do ano.
Onda de calor: 3 ou mais dias quentes seguidos.

``METODOS`` reúne também os outros critérios da tabela de Fante (2024), usados no dashboard
para comparação. Todos usam os mesmos limites diários (período-base e janela iguais).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pymannkendall as mk


def dia_do_ano(datas: pd.Series) -> pd.Series:
    """Dia do ano de 1 a 366 num calendário bissexto fixo (1º de março é sempre o dia 61)."""
    d = datas.dt.dayofyear
    return d + ((~datas.dt.is_leap_year) & (datas.dt.month > 2)).astype(int)


def limiares_p90(df: pd.DataFrame, inicio: int = 1991, fim: int = 2020, janela: int = 15) -> pd.DataFrame:
    """P90 da Tmax e da Tmin para cada dia do ano (1 a 366).

    Usa todos os valores do período-base numa janela de ``janela`` dias centrada no dia,
    circular na virada do ano. Devolve as colunas ``p90_tmax`` e ``p90_tmin`` (índice ``dia``).
    """
    base = df[df["data"].dt.year.between(inicio, fim)].dropna(subset=["tmax", "tmin"])
    doy = dia_do_ano(base["data"]).to_numpy()
    meia = janela // 2
    linhas = []
    for dia in range(1, 367):
        dist = np.abs(doy - dia)
        dentro = np.minimum(dist, 366 - dist) <= meia
        linhas.append(
            (dia, np.percentile(base["tmax"].to_numpy()[dentro], 90), np.percentile(base["tmin"].to_numpy()[dentro], 90))
        )
    return pd.DataFrame(linhas, columns=["dia", "p90_tmax", "p90_tmin"]).set_index("dia")


def limites_diarios(df: pd.DataFrame, inicio: int = 1991, fim: int = 2020, janela: int = 15) -> pd.DataFrame:
    """Limites de todos os métodos para cada dia do ano (1 a 366).

    Além de ``p90_tmax`` e ``p90_tmin``, traz ``normal5_tmax`` = média da Tmax na mesma janela + 5 °C
    (critério do IPCC).
    """
    lim = limiares_p90(df, inicio, fim, janela)
    base = df[df["data"].dt.year.between(inicio, fim)].dropna(subset=["tmax"])
    doy = dia_do_ano(base["data"]).to_numpy()
    meia = janela // 2
    media = []
    for dia in lim.index:
        dist = np.abs(doy - dia)
        media.append(base["tmax"].to_numpy()[np.minimum(dist, 366 - dist) <= meia].mean())
    return lim.assign(normal5_tmax=np.array(media) + 5)


@dataclass(frozen=True)
class Metodo:
    """Critério de onda de calor: todas as ``condicoes`` (variável, coluna do limite) valem no dia,
    por ``minimo`` dias seguidos. A intensidade usa a primeira condição."""

    nome: str
    minimo: int
    condicoes: tuple[tuple[str, str], ...]
    descricao: str


_TMAX = (("tmax", "p90_tmax"),)
_TMIN = (("tmin", "p90_tmin"),)
_AMBAS = (("tmax", "p90_tmax"), ("tmin", "p90_tmin"))

METODOS = {
    "oliveira": Metodo("Oliveira et al. (2021)", 3, _AMBAS, "Tmax e Tmin acima do P90, 3 dias ou mais"),
    "wsdi": Metodo("WSDI (OMM)", 6, _TMAX, "Tmax acima do P90, 6 dias ou mais"),
    "ipcc": Metodo("IPCC", 5, (("tmax", "normal5_tmax"),), "Tmax 5 °C acima da normal, 5 dias ou mais"),
    "silveira": Metodo("Silveira (2014)", 3, _TMAX, "Tmax acima do P90, 3 dias ou mais"),
    "diaz": Metodo("Díaz et al. (2002)", 2, _AMBAS, "Tmax e Tmin acima do P90, 2 dias ou mais"),
    "geirinhas_tmax": Metodo("Geirinhas et al. (2018), Tmax", 3, _TMAX, "Tmax acima do P90, 3 dias ou mais"),
    "geirinhas_tmin": Metodo("Geirinhas et al. (2018), Tmin", 3, _TMIN, "Tmin acima do P90, 3 dias ou mais"),
}


def ondas_por_metodo(df: pd.DataFrame, limites: pd.DataFrame, metodo: Metodo) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Dias marcados (com os limites e a coluna ``quente``) e eventos do ``metodo``."""
    out = df.join(limites, on=dia_do_ano(df["data"]).rename("dia"))
    out["quente"] = np.logical_and.reduce([out[v] > out[lim] for v, lim in metodo.condicoes])
    var, lim = metodo.condicoes[0]
    return out, ondas_de_calor(out, metodo.minimo, var, lim)


def dias_quentes(df: pd.DataFrame, limiares: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta os limiares do dia e a coluna booleana ``quente`` (Tmax > P90max e Tmin > P90min)."""
    out = df.join(limiares, on=dia_do_ano(df["data"]).rename("dia"))
    out["quente"] = (out["tmax"] > out["p90_tmax"]) & (out["tmin"] > out["p90_tmin"])
    return out


def ondas_de_calor(
    df_quentes: pd.DataFrame, minimo: int = 3, var: str = "tmax", limiar: str = "p90_tmax"
) -> pd.DataFrame:
    """Eventos de ``minimo`` ou mais dias quentes seguidos.

    Colunas: ``inicio``, ``fim``, ``duracao`` (dias), ``intensidade`` = média de (``var`` − ``limiar``)
    nos dias do evento e ``pico`` = maior ``var``, em °C. Uma falha de data quebra a sequência.
    """
    q = df_quentes.sort_values("data")
    q = q[q["quente"]]
    novo = q["data"].diff().ne(pd.Timedelta(days=1))
    grupos = q.assign(evento=novo.cumsum(), excesso=q[var] - q[limiar]).groupby("evento")
    ev = grupos.agg(
        inicio=("data", "min"), fim=("data", "max"), duracao=("data", "size"), intensidade=("excesso", "mean"),
        pico=(var, "max"),
    )
    return ev[ev["duracao"] >= minimo].reset_index(drop=True)


def indicadores_anuais(eventos: pd.DataFrame, anos) -> pd.DataFrame:
    """Indicadores por ano (cada evento conta no ano em que começa); anos sem onda ficam com 0.

    HWN: número de ondas; HWF: dias em onda; HWD: maior duração; intensidade: média das ondas do ano.
    """
    por_ano = eventos.groupby(eventos["inicio"].dt.year.rename("ano")).agg(
        HWN=("duracao", "size"), HWF=("duracao", "sum"), HWD=("duracao", "max"), intensidade=("intensidade", "mean")
    )
    ind = por_ano.reindex(pd.Index(list(anos), name="ano")).fillna(0)
    return ind.astype({"HWN": int, "HWF": int, "HWD": int})


def tendencia(serie: pd.Series) -> dict:
    """Mann-Kendall (tau, p-valor) e declive de Sen por ano e por década de uma série anual."""
    r = mk.original_test(np.asarray(serie, dtype=float))
    return {"tau": r.Tau, "p": r.p, "declive_ano": r.slope, "declive_decada": 10 * r.slope}
