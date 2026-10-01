"""Baixa os arquivos anuais do INMET (BDMEP) e salva Tmax/Tmin diários das estações da região.

Uso:  python scripts/processar_bdmep.py 2025 2026
(sem argumentos usa o ano corrente; o ZIP de cada ano tem de 60 a 100 MB)
"""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from clima_ssm import DADOS, inmet, regiao  # noqa: E402

ARQ_SAIDA = DADOS / "inmet_bdmep_diario.csv"
COLUNAS = ["codigo", "data", "tmax", "tmin", "horas_tmax", "horas_tmin"]


def main(anos: list[int]) -> None:
    est = regiao.estacoes()
    codigos = est.loc[est["tipo"] == "T", "codigo"].tolist()
    novos = []
    for ano in anos:
        print(f"Baixando BDMEP {ano} ...", flush=True)
        df = inmet.bdmep_ano(ano, codigos)
        print(f"  {df['codigo'].nunique()} estações, {len(df)} dias")
        novos.append(df[COLUNAS])
    novos = pd.concat(novos, ignore_index=True)

    if ARQ_SAIDA.exists():  # mantém os anos que não foram reprocessados
        antigo = pd.read_csv(ARQ_SAIDA, parse_dates=["data"], dtype={"codigo": str})
        novos = pd.concat([antigo[~antigo["data"].dt.year.isin(anos)], novos], ignore_index=True)
    novos = novos.sort_values(["codigo", "data"], ignore_index=True)
    novos.to_csv(ARQ_SAIDA, index=False, float_format="%.1f")

    resumo = (
        novos.assign(ano=novos["data"].dt.year)
        .groupby(["codigo", "ano"])
        .agg(pct_dias_tmax=("tmax", lambda s: round(100 * s.notna().mean())), ultimo_dia=("data", "max"))
    )
    print(resumo.to_string())
    print(f"-> {ARQ_SAIDA}")


if __name__ == "__main__":
    anos = [int(a) for a in sys.argv[1:]] or [dt.date.today().year]
    main(anos)
