"""Acesso aos dados das estações automáticas do INMET.

Três caminhos, testados em 01/10/2026:

* ``estacoes()``: catálogo público de estações (funciona sem chave).
* ``dados_api()``: dados horários quase em tempo real. **Exige token**, pedido por
  e-mail ao INMET (cadastro.act@inmet.gov.br). Sem token as rotas públicas devolvem
  204/404. Esta função segue o formato documentado da API, mas só pôde ser testada
  até a resposta "CHAVE INVÁLIDA!". Teste de novo quando o token chegar.
* ``bdmep_ano()``: arquivos anuais do BDMEP (portal.inmet.gov.br/dadoshistoricos),
  sem chave, atualizados cerca de uma vez por mês.

As medições horárias vêm em UTC. Para fechar o dia local (UTC-3), Tmax é a maior
"temperatura máxima na hora anterior" e Tmin a menor "mínima na hora anterior"
entre 00h e 23h locais. Dias com menos de ``MIN_HORAS`` registros ficam nulos.
"""

from __future__ import annotations

import datetime as dt
import io
import os
import tempfile
import zipfile

import pandas as pd
import requests

from .fontes import CABECALHO

URL_API = "https://apitempo.inmet.gov.br"
URL_BDMEP = "https://portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip"
MIN_HORAS = 18
FUSO_HORAS = -3


def estacoes(tipo: str = "T") -> pd.DataFrame:
    """Catálogo de estações (``T`` = automáticas, ``M`` = convencionais)."""
    r = requests.get(f"{URL_API}/estacoes/{tipo}", headers=CABECALHO, timeout=60)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    return pd.DataFrame(
        {
            "codigo": df["CD_ESTACAO"],
            "nome": df["DC_NOME"],
            "uf": df["SG_ESTADO"],
            "lat": pd.to_numeric(df["VL_LATITUDE"]),
            "lon": pd.to_numeric(df["VL_LONGITUDE"]),
            "altitude": pd.to_numeric(df["VL_ALTITUDE"], errors="coerce"),
            "situacao": df["CD_SITUACAO"],
            "inicio_operacao": df["DT_INICIO_OPERACAO"].str.slice(0, 10),
            "tipo": tipo,
        }
    )


def _num(serie: pd.Series) -> pd.Series:
    """Converte texto com vírgula decimal ("23,4", ",5", "-9999") em número."""
    txt = serie.astype("string").str.strip().str.replace(",", ".", regex=False)
    num = pd.to_numeric(txt, errors="coerce")
    return num.mask(num <= -9999)


def horario_para_diario(horario: pd.DataFrame) -> pd.DataFrame:
    """Agrega registros horários (``codigo``, ``datahora_utc``, ``tmax_h``, ``tmin_h``) em dias locais."""
    h = horario.assign(data=(horario["datahora_utc"] + pd.Timedelta(hours=FUSO_HORAS)).dt.normalize())
    dia = (
        h.groupby(["codigo", "data"])
        .agg(
            tmax=("tmax_h", "max"),
            tmin=("tmin_h", "min"),
            horas_tmax=("tmax_h", "count"),
            horas_tmin=("tmin_h", "count"),
        )
        .reset_index()
    )
    dia["tmax"] = dia["tmax"].where(dia["horas_tmax"] >= MIN_HORAS)
    dia["tmin"] = dia["tmin"].where(dia["horas_tmin"] >= MIN_HORAS)
    dia["fonte"] = "INMET"
    return dia


def dados_api(codigo: str, inicio: dt.date | str, fim: dt.date | str, token: str | None = None) -> pd.DataFrame:
    """Dados horários da API do INMET (rota com token), agregados por dia.

    O token pode vir do argumento ou da variável de ambiente ``INMET_TOKEN``.
    """
    token = token or os.environ.get("INMET_TOKEN")
    if not token:
        raise RuntimeError(
            "A API de dados do INMET exige token. Peça por e-mail (cadastro.act@inmet.gov.br) "
            "e defina a variável de ambiente INMET_TOKEN."
        )
    url = f"{URL_API}/token/estacao/{inicio}/{fim}/{codigo}/{token}"
    r = requests.get(url, headers=CABECALHO, timeout=120)
    r.raise_for_status()
    if r.status_code == 204 or not r.content:
        return horario_para_diario(_horario_vazio())
    if not r.text.lstrip().startswith("["):  # token errado vem como texto puro: "CHAVE INVÁLIDA!"
        raise RuntimeError(f"INMET: {r.text.strip()[:200]}")
    js = pd.DataFrame(r.json())
    horario = pd.DataFrame(
        {
            "codigo": codigo,
            "datahora_utc": pd.to_datetime(
                js["DT_MEDICAO"] + " " + js["HR_MEDICAO"].astype(str).str.zfill(4), format="%Y-%m-%d %H%M"
            ),
            "tmax_h": _num(js["TEM_MAX"]),
            "tmin_h": _num(js["TEM_MIN"]),
        }
    )
    return horario_para_diario(horario)


def _horario_vazio() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "codigo": pd.Series(dtype="string"),
            "datahora_utc": pd.Series(dtype="datetime64[us]"),
            "tmax_h": pd.Series(dtype="float64"),
            "tmin_h": pd.Series(dtype="float64"),
        }
    )


def ler_csv_bdmep(conteudo: bytes) -> tuple[dict, pd.DataFrame]:
    """Lê um CSV do BDMEP (8 linhas de metadados + cabeçalho + dados horários)."""
    texto = conteudo.decode("latin-1")
    linhas = texto.splitlines()
    meta = {}
    for linha in linhas[:8]:
        chave, _, valor = linha.partition(";")
        meta[chave.strip().rstrip(":")] = valor.strip().rstrip(";")
    df = pd.read_csv(io.StringIO(texto), sep=";", skiprows=8, dtype=str, index_col=False)
    cab = {c.strip().upper(): c for c in df.columns}

    def coluna(prefixo: str) -> pd.Series:
        return df[next(orig for up, orig in cab.items() if up.startswith(prefixo))]

    # Formatos: "2026/08/31" + "2300 UTC" (2019+) ou "2018-08-31" + "23:00" (até 2018)
    data = coluna("DATA").str.strip().str.replace("/", "-", regex=False)
    hora = coluna("HORA").str.replace(r"\D", "", regex=True).str.slice(0, 2)
    horario = pd.DataFrame(
        {
            "codigo": meta.get("CODIGO (WMO)", ""),
            "datahora_utc": pd.to_datetime(data + " " + hora, format="%Y-%m-%d %H"),
            "tmax_h": _num(coluna("TEMPERATURA MÁXIMA NA HORA ANT")),
            "tmin_h": _num(coluna("TEMPERATURA MÍNIMA NA HORA ANT")),
        }
    )
    return meta, horario


def bdmep_ano(ano: int, codigos: list[str]) -> pd.DataFrame:
    """Baixa o ZIP anual do BDMEP e devolve Tmax/Tmin diários das estações pedidas."""
    with tempfile.TemporaryFile() as tmp:
        with requests.get(URL_BDMEP.format(ano=ano), headers=CABECALHO, timeout=600, stream=True) as r:
            r.raise_for_status()
            for bloco in r.iter_content(1 << 20):
                tmp.write(bloco)
        tmp.seek(0)
        z = zipfile.ZipFile(tmp)
        partes = []
        for nome in z.namelist():
            if any(f"_{cod}_" in nome for cod in codigos):
                _, horario = ler_csv_bdmep(z.read(nome))
                partes.append(horario_para_diario(horario))
    if not partes:
        return horario_para_diario(_horario_vazio())
    df = pd.concat(partes, ignore_index=True)
    # A conversão UTC -> local joga as 3 primeiras horas do ano para 31/12 do ano anterior
    return df[df["data"].dt.year == ano].reset_index(drop=True)
