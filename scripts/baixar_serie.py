"""Baixa a série diária de Tmax/Tmin de um município e gera o gráfico da série temporal.

Uso:
    python scripts/baixar_serie.py                          # São Sebastião do Paraíso
    python scripts/baixar_serie.py --municipio "Varginha"

Saídas:
    dados/serie_<municipio>.csv     (1991 até ontem + previsão de 7 dias)
    figuras/serie_<municipio>.png
"""

import argparse
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import pandas as pd  # noqa: E402

from clima_ssm import DADOS, FIGURAS, fontes, graficos, regiao  # noqa: E402


def slug(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode().lower()
    return "_".join(txt.split())


def baixar(lat: float, lon: float) -> pd.DataFrame:
    """Histórico desde 1991 + os dias de previsão que ainda não estão no histórico."""
    hist = fontes.open_meteo_historico(lat, lon, "1991-01-01").assign(previsao=False)
    prev = fontes.open_meteo_previsao(lat, lon, dias_passados=0, dias_previsao=8)
    prev = prev[prev["data"] > hist["data"].max()]
    return pd.concat([hist, prev], ignore_index=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--municipio", default="São Sebastião do Paraíso")
    nome = p.parse_args().municipio

    mun = regiao.municipios()
    sel = mun[mun["nome"].str.lower() == nome.lower()]
    if sel.empty:
        sys.exit(f"Município '{nome}' não está na mesorregião. Veja dados/municipios_ssm.csv.")
    m = sel.iloc[0]

    print(f"Baixando {m['nome']} ({m['lat']}, {m['lon']}) ...", flush=True)
    df = baixar(m["lat"], m["lon"])
    obs = df[~df["previsao"]]
    print(
        f"  {len(obs)} dias observados ({obs['data'].min():%d/%m/%Y} a {obs['data'].max():%d/%m/%Y}), "
        f"{int(df['previsao'].sum())} dias de previsão"
    )

    DADOS.mkdir(exist_ok=True)
    FIGURAS.mkdir(exist_ok=True)
    arq_csv = DADOS / f"serie_{slug(m['nome'])}.csv"
    df.to_csv(arq_csv, index=False, date_format="%Y-%m-%d")
    arq_png = FIGURAS / f"serie_{slug(m['nome'])}.png"
    fig = graficos.figura_serie(df, m["nome"])
    fig.savefig(arq_png, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"-> {arq_csv}\n-> {arq_png}")


if __name__ == "__main__":
    main()
