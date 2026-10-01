"""Gráficos estáticos (matplotlib) usados pelo script e pelo relatório."""

from __future__ import annotations

import datetime as dt

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import fontes

# Tmax = laranja, Tmin = azul (slots 2 e 1 da paleta categórica validada)
COR_TMAX = "#eb6834"
COR_TMIN = "#2a78d6"
COR_NORMAL = "#898781"
COR_GRADE = "#e1e0d9"
COR_EIXO = "#c3c2b7"
COR_FUNDO = "#fcfcfb"
COR_TEXTO = "#0b0b0b"
COR_TEXTO_2 = "#52514e"


def estilo_eixo(ax, unidade: str = "°C") -> None:
    ax.set_facecolor(COR_FUNDO)
    ax.grid(axis="y", color=COR_GRADE, linewidth=0.6)
    ax.set_axisbelow(True)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(COR_EIXO)
    ax.tick_params(colors=COR_TEXTO_2, labelsize=9, length=0)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f} {unidade}")


def tendencia_anual(df: pd.DataFrame, ano_final: int) -> tuple[pd.DataFrame, dict]:
    """Médias anuais de Tmax/Tmin (anos completos) e inclinação linear em °C/década."""
    base = df[df["data"].dt.year <= ano_final]
    anual = base.groupby(base["data"].dt.year.rename("ano"))[["tmax", "tmin"]].mean().reset_index()
    inclinacao = {c: np.polyfit(anual["ano"], anual[c], 1)[0] * 10 for c in ("tmax", "tmin")}
    return anual, inclinacao


def figura_serie(serie: pd.DataFrame, nome: str, hoje: dt.date | None = None) -> plt.Figure:
    """Painel A: últimos 12 meses + previsão; painel B: médias anuais e tendência.

    ``serie`` precisa das colunas data, tmax, tmin e previsao (bool).
    """
    hoje = pd.Timestamp(hoje or fontes.hoje())
    obs_todo = serie[~serie["previsao"]]
    normal = fontes.climatologia_mensal(obs_todo)
    recente = fontes.com_normal(serie[serie["data"] >= hoje - pd.Timedelta(days=365)], normal)
    obs = recente[~recente["previsao"]]
    prev = pd.concat([obs.tail(1), recente[recente["previsao"]]])  # liga a previsão ao último dado
    anual, incl = tendencia_anual(obs_todo, hoje.year - 1)

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 8.2), height_ratios=[1.35, 1], layout="constrained")
    fig.patch.set_facecolor(COR_FUNDO)
    estilo_eixo(a1)
    estilo_eixo(a2)

    a1.plot(recente["data"], recente["tmax_normal"], color=COR_NORMAL, lw=1, label="Normal mensal 1991–2020")
    a1.plot(recente["data"], recente["tmin_normal"], color=COR_NORMAL, lw=1)
    a1.plot(obs["data"], obs["tmax"], color=COR_TMAX, lw=1.3, label="Tmax diária")
    a1.plot(obs["data"], obs["tmin"], color=COR_TMIN, lw=1.3, label="Tmin diária")
    a1.plot(prev["data"], prev["tmax"], color=COR_TMAX, lw=1.3, ls=(0, (3, 2)), label="Previsão (7 dias)")
    a1.plot(prev["data"], prev["tmin"], color=COR_TMIN, lw=1.3, ls=(0, (3, 2)))
    a1.axvline(hoje, color=COR_EIXO, lw=0.8)
    a1.text(hoje, a1.get_ylim()[1], " hoje", color=COR_TEXTO_2, fontsize=8.5, va="top")
    a1.xaxis.set_major_locator(mdates.MonthLocator())
    a1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%y"))
    a1.legend(loc="lower left", ncols=4, frameon=False, fontsize=8.5, labelcolor=COR_TEXTO_2)
    ult = obs.iloc[-1]
    a1.set_title(
        f"Últimos 12 meses (último dia observado: {ult['data']:%d/%m/%Y}, "
        f"Tmax {ult['tmax']:.1f} °C, Tmin {ult['tmin']:.1f} °C)",
        loc="left", fontsize=10.5, color=COR_TEXTO,
    )

    anos = anual["ano"].to_numpy()
    for col, cor, rot in (("tmax", COR_TMAX, "Tmax"), ("tmin", COR_TMIN, "Tmin")):
        y = anual[col].to_numpy()
        a, b = np.polyfit(anos, y, 1)
        a2.plot(anos, y, color=cor, lw=1.6, marker="o", ms=3.5)
        a2.plot(anos, a * anos + b, color=cor, lw=0.9, alpha=0.6)
        a2.annotate(
            f"{rot}  {incl[col]:+.2f} °C/década", (anos[-1], y[-1]), xytext=(8, 0), textcoords="offset points",
            color=COR_TEXTO, fontsize=9, va="center",
        )
    a2.set_xlim(anos[0] - 0.5, anos[-1] + 7)  # espaço à direita para os rótulos
    a2.set_xticks([a for a in range(1995, anos[-1] + 1, 5)])
    a2.set_title(f"Média anual {anos[0]}–{anos[-1]} e tendência linear", loc="left", fontsize=10.5, color=COR_TEXTO)

    fig.suptitle(f"Temperatura máxima e mínima diária, {nome} (MG)", x=0.01, ha="left", fontsize=13, color=COR_TEXTO)
    fig.text(
        0.01, -0.01,
        "Fonte: Open-Meteo, Historical Weather API (ERA5 + ECMWF IFS) e Forecast API. "
        "Dado de modelo em grade, não de estação.",
        fontsize=8, color=COR_TEXTO_2,
    )
    return fig
