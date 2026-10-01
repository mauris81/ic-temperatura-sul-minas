"""Gera as tabelas fixas da região: municípios, contornos (GeoJSON) e estações do INMET.

Uso:  python scripts/preparar_regiao.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from clima_ssm import DADOS, inmet, regiao  # noqa: E402


def main() -> None:
    DADOS.mkdir(exist_ok=True)

    mun = regiao.baixar_municipios()
    mun.to_csv(regiao.ARQ_MUNICIPIOS, index=False)
    print(f"{len(mun)} municípios -> {regiao.ARQ_MUNICIPIOS.name}")

    malha = regiao.baixar_malha()
    regiao.ARQ_MALHA.write_text(json.dumps(malha, ensure_ascii=False), encoding="utf-8")
    print(f"{len(malha['features'])} polígonos -> {regiao.ARQ_MALHA.name}")

    todas = pd.concat([inmet.estacoes("T"), inmet.estacoes("M")], ignore_index=True)
    todas = todas[todas["uf"] == "MG"].copy()
    todas["codigo_ibge"] = [regiao.municipio_do_ponto(lo, la, malha) for lo, la in zip(todas["lon"], todas["lat"])]
    est = todas.dropna(subset=["codigo_ibge"]).astype({"codigo_ibge": int})
    est = est.merge(mun[["codigo_ibge", "nome"]].rename(columns={"nome": "municipio"}), on="codigo_ibge", how="left")
    est = est.sort_values(["tipo", "nome"], ascending=[False, True], ignore_index=True)
    est.to_csv(regiao.ARQ_ESTACOES, index=False)
    print(f"{len(est)} estações do INMET dentro da mesorregião -> {regiao.ARQ_ESTACOES.name}")
    print(est[["codigo", "nome", "municipio", "situacao", "tipo"]].to_string(index=False))


if __name__ == "__main__":
    main()
