"""Dashboard de temperatura do Sul e Sudoeste de Minas (Shiny for Python).

Rodar localmente:  shiny run app.py   (ou o botão "Run Shiny App" no Positron)
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache

import pandas as pd
import plotly.graph_objects as go
from shiny import App, reactive, render, req, ui
from shinywidgets import output_widget, render_plotly

from clima_ssm import fontes, regiao

COR_TMAX = "#eb6834"
COR_TMIN = "#2a78d6"
COR_GRADE = "#e1e0d9"
COR_TEXTO_2 = "#52514e"
ESCALA_LARANJA = [[0, "#fde6d8"], [0.5, "#f19a6e"], [1, "#a8401a"]]
ESCALA_AZUL = [[0, "#cde2fb"], [0.5, "#5598e7"], [1, "#0d366b"]]
MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

MUN = regiao.municipios()
MUN_IDX = MUN.set_index("codigo_ibge")
MALHA = regiao.malha_para_plotly(regiao.malha())


def br(v: float, casas: int = 1) -> str:
    """Número no formato brasileiro (vírgula decimal)."""
    return "–" if pd.isna(v) else f"{v:.{casas}f}".replace(".", ",")


# --- Cache das APIs: a chave inclui o dia (ou a hora), então os dados se renovam sozinhos ---


@lru_cache(maxsize=48)
def _historico(codigo: int, dia: dt.date) -> pd.DataFrame:
    m = MUN_IDX.loc[codigo]
    return fontes.open_meteo_historico(m["lat"], m["lon"], "1991-01-01")


@lru_cache(maxsize=48)
def _previsao(codigo: int, hora: str) -> pd.DataFrame:
    m = MUN_IDX.loc[codigo]
    return fontes.open_meteo_previsao(m["lat"], m["lon"], dias_passados=0, dias_previsao=8)


@lru_cache(maxsize=4)
def _regional(hora: str) -> pd.DataFrame:
    df = fontes.open_meteo_varios_pontos(MUN["lat"].tolist(), MUN["lon"].tolist(), dias_passados=31, dias_previsao=2)
    return df.assign(codigo_ibge=MUN["codigo_ibge"].to_numpy()[df["ponto"]])


def _hora() -> str:
    return pd.Timestamp.now(tz=fontes.FUSO).strftime("%Y-%m-%d %H")


def _layout(fig: go.Figure, altura: int = 440) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=altura,
        margin=dict(l=10, r=10, t=85, b=10),
        hovermode="x unified",
        title=dict(x=0.01, y=0.97, yanchor="top", font=dict(size=15)),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(color=COR_TEXTO_2)),
        font=dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif", size=12),
        separators=",.",
    )
    fig.update_yaxes(gridcolor=COR_GRADE, ticksuffix=" °C", zeroline=False)
    fig.update_xaxes(showgrid=False, linecolor="#c3c2b7")
    return fig


# --- Interface ----------------------------------------------------------------------------

ATALHOS = {"30": "30 dias", "90": "90 dias", "365": "1 ano", "1825": "5 anos", "tudo": "Desde 1991"}
VARIAVEIS_MAPA = {
    "tmax_ontem": "Tmax de ontem",
    "tmin_ontem": "Tmin de ontem",
    "tmax_amanha": "Tmax prevista para amanhã",
    "tmin_amanha": "Tmin prevista para amanhã",
    "tmax_30d": "Tmax média dos últimos 30 dias",
    "tmin_30d": "Tmin média dos últimos 30 dias",
}

def caixa(titulo: str, id_: str):
    """Caixa de destaque: valor (Tmax / Tmin) em fonte grande e uma legenda curta embaixo."""
    return ui.value_box(
        titulo,
        ui.output_text(f"{id_}_valor"),
        ui.p(ui.output_text(f"{id_}_nota", inline=True), class_="small text-muted mb-0"),
    )


app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.input_selectize(
            "municipio",
            "Município",
            choices={str(c): n for c, n in zip(MUN["codigo_ibge"], MUN["nome"])},
            selected=str(regiao.MUNICIPIO_PADRAO),
        ),
        ui.input_radio_buttons("atalho", "Período", ATALHOS, selected="365", inline=True),
        ui.input_date_range(
            "periodo", None, start="2025-01-01", end="2025-12-31", min="1991-01-01",
            format="dd/mm/yyyy", language="pt-BR", separator=" até ",
        ),
        ui.input_switch("previsao", "Mostrar previsão (hoje + 7 dias)", True),
        ui.input_switch("normal", "Mostrar normal 1991–2020", True),
        ui.input_switch("media7", "Suavizar (média móvel de 7 dias)", False),
        ui.hr(),
        ui.output_ui("rodape"),
        width=320,
    ),
    ui.layout_columns(
        caixa("Hoje (previsão)", "vb_hoje"),
        caixa("Último dia observado", "vb_ontem"),
        caixa("Últimos 30 dias × normal", "vb_30d"),
        caixa("Extremos no período", "vb_extremos"),
        col_widths={"sm": 6, "xl": 3},
        fill=False,
    ),
    ui.navset_card_underline(
        ui.nav_panel("Série temporal", output_widget("g_serie")),
        ui.nav_panel(
            "Climatologia",
            ui.input_select("ano", "Comparar o ano", choices=[], width="200px"),
            output_widget("g_clima"),
        ),
        ui.nav_panel(
            "Mapa da região",
            ui.input_select("var_mapa", None, VARIAVEIS_MAPA, width="320px"),
            output_widget("g_mapa"),
            ui.p("Passe o mouse sobre um município para ver o valor. Contorno preto: município selecionado.",
                 class_="text-muted small"),
        ),
        ui.nav_panel(
            "Dados",
            ui.download_button("baixar", "Baixar CSV do período"),
            ui.output_data_frame("t_dados"),
        ),
        ui.nav_panel("Sobre", ui.output_ui("sobre")),
    ),
    ui.tags.style(".bslib-value-box .value-box-value { font-size: 1.6rem; }"),
    title="Temperatura no Sul e Sudoeste de Minas",
    fillable=False,
)


# --- Servidor -----------------------------------------------------------------------------


def server(input, output, session):
    @reactive.effect
    @reactive.event(input.atalho)
    def _aplicar_atalho():
        fim = fontes.ontem()
        inicio = dt.date(1991, 1, 1) if input.atalho() == "tudo" else fim - dt.timedelta(days=int(input.atalho()))
        ui.update_date_range("periodo", start=inicio, end=fim, max=fim)

    @reactive.calc
    def codigo() -> int:
        return int(req(input.municipio()))

    @reactive.calc
    def municipio() -> pd.Series:
        return MUN_IDX.loc[codigo()]

    @reactive.calc
    def historico() -> pd.DataFrame:
        return _historico(codigo(), fontes.hoje())

    @reactive.calc
    def previsao() -> pd.DataFrame:
        prev = _previsao(codigo(), _hora())
        return prev[prev["data"] > historico()["data"].max()]

    @reactive.calc
    def normal() -> pd.DataFrame:
        return fontes.normal_diaria(historico())

    @reactive.calc
    def periodo() -> pd.DataFrame:
        inicio, fim = req(input.periodo())
        h = historico()
        return h[(h["data"].dt.date >= inicio) & (h["data"].dt.date <= fim)]

    @reactive.effect
    def _anos():
        anos = sorted(historico()["data"].dt.year.unique(), reverse=True)
        ui.update_select("ano", choices=[str(a) for a in anos], selected=str(anos[0]))

    # --- caixas de destaque ---

    @reactive.calc
    def hoje_prev() -> pd.Series | None:
        p = previsao()
        hoje = p[p["data"].dt.date == fontes.hoje()]
        return None if hoje.empty else hoje.iloc[0]

    @reactive.calc
    def anomalia_30d() -> tuple[float, float]:
        h = historico().tail(30)
        h = h.join(normal(), on=h["data"].dt.strftime("%m-%d"))
        return (h["tmax"] - h["tmax_normal"]).mean(), (h["tmin"] - h["tmin_normal"]).mean()

    @reactive.calc
    def extremos() -> tuple[pd.Series, pd.Series]:
        p = periodo()
        req(not p.empty)
        return p.loc[p["tmax"].idxmax()], p.loc[p["tmin"].idxmin()]

    def _com_sinal(v: float) -> str:
        return ("+" if v >= 0 else "−") + br(abs(v))

    @render.text
    def vb_hoje_valor():
        h = hoje_prev()
        return "–" if h is None else f"{br(h['tmax'])}° / {br(h['tmin'])}°"

    @render.text
    def vb_hoje_nota():
        h = hoje_prev()
        return "sem previsão" if h is None else f"máx / mín em {h['data']:%d/%m/%Y}"

    @render.text
    def vb_ontem_valor():
        u = historico().iloc[-1]
        return f"{br(u['tmax'])}° / {br(u['tmin'])}°"

    @render.text
    def vb_ontem_nota():
        return f"máx / mín em {historico().iloc[-1]['data']:%d/%m/%Y}"

    @render.text
    def vb_30d_valor():
        ax, an = anomalia_30d()
        return f"{_com_sinal(ax)}° / {_com_sinal(an)}°"

    @render.text
    def vb_30d_nota():
        return "anomalia média de máx / mín"

    @render.text
    def vb_extremos_valor():
        mx, mn = extremos()
        return f"{br(mx['tmax'])}° / {br(mn['tmin'])}°"

    @render.text
    def vb_extremos_nota():
        mx, mn = extremos()
        return f"máx em {mx['data']:%d/%m/%Y}, mín em {mn['data']:%d/%m/%Y}"

    @render.ui
    def rodape():
        h = historico()
        return ui.div(
            ui.p(f"Dados até {h['data'].max():%d/%m/%Y} (Open-Meteo, ERA5 + ECMWF IFS). Atualização diária."),
            ui.p(f"Ponto: {municipio()['lat']:.4f}, {municipio()['lon']:.4f} (sede municipal)."),
            class_="small text-muted",
        )

    # --- gráficos ---

    @render_plotly
    def g_serie():
        p = periodo().copy()
        req(not p.empty)
        fig = go.Figure()
        if input.normal():
            n = p.join(normal(), on=p["data"].dt.strftime("%m-%d"))
            for col in ("tmax_normal", "tmin_normal"):
                fig.add_scatter(
                    x=n["data"], y=n[col], name="Normal 1991–2020", legendgroup="normal",
                    showlegend=col == "tmax_normal", line=dict(color="#898781", width=1),
                    hovertemplate="%{y:.1f} °C",
                )
        if input.media7():
            p[["tmax", "tmin"]] = p[["tmax", "tmin"]].rolling(7, center=True, min_periods=4).mean()
        for col, cor, nome in (("tmax", COR_TMAX, "Tmax"), ("tmin", COR_TMIN, "Tmin")):
            fig.add_scatter(x=p["data"], y=p[col], name=nome, line=dict(color=cor, width=1.6), hovertemplate="%{y:.1f} °C")
        if input.previsao() and input.periodo()[1] >= fontes.ontem():
            prev = pd.concat([p.tail(1), previsao()])  # liga a previsão ao último dado
            for col, cor in (("tmax", COR_TMAX), ("tmin", COR_TMIN)):
                fig.add_scatter(
                    x=prev["data"], y=prev[col], name="Previsão", legendgroup="prev",
                    showlegend=col == "tmax", line=dict(color=cor, width=1.6, dash="dash"),
                    hovertemplate="%{y:.1f} °C",
                )
        fig.update_traces(mode="lines")
        fig.update_xaxes(tickformat="%m/%Y", hoverformat="%d/%m/%Y")
        fig.update_layout(title=dict(text=f"Tmax e Tmin diárias, {municipio()['nome']}"))
        return _layout(fig, 470)

    @render_plotly
    def g_clima():
        h = historico()
        req(input.ano())
        ano = int(input.ano())
        normal_m = fontes.climatologia_mensal(h)
        do_ano = h[h["data"].dt.year == ano]
        do_ano = do_ano.groupby(do_ano["data"].dt.month)[["tmax", "tmin"]].mean()
        fig = go.Figure()
        for col, cor, nome in (("tmax", COR_TMAX, "Tmax"), ("tmin", COR_TMIN, "Tmin")):
            fig.add_scatter(
                x=[MESES[m - 1] for m in normal_m["mes"]], y=normal_m[f"{col}_normal"],
                name=f"{nome} normal 1991–2020", mode="lines", line=dict(color=cor, width=1.2), opacity=0.45,
                hovertemplate="%{y:.1f} °C",
            )
            fig.add_scatter(
                x=[MESES[m - 1] for m in do_ano.index], y=do_ano[col], name=f"{nome} {ano}",
                mode="lines+markers", line=dict(color=cor, width=2.2), marker=dict(size=8),
                hovertemplate="%{y:.1f} °C",
            )
        fig.update_layout(title=dict(text=f"Média mensal de {ano} × normal 1991–2020, {municipio()['nome']}"))
        return _layout(fig, 440)

    @reactive.calc
    def valores_mapa() -> pd.DataFrame:
        reg = _regional(_hora())
        hoje = pd.Timestamp(fontes.hoje())
        var = input.var_mapa()
        col = var.split("_")[0]
        if var.endswith("ontem"):
            sel = reg[reg["data"] == hoje - pd.Timedelta(days=1)]
        elif var.endswith("amanha"):
            sel = reg[reg["data"] == hoje + pd.Timedelta(days=1)]
        else:
            sel = reg[(reg["data"] < hoje) & (reg["data"] >= hoje - pd.Timedelta(days=30))]
        v = sel.groupby("codigo_ibge")[col].mean().rename("valor").reset_index()
        return v.merge(MUN[["codigo_ibge", "nome"]], on="codigo_ibge")

    @render_plotly
    def g_mapa():
        v = valores_mapa()
        var = input.var_mapa()
        fig = go.Figure(
            go.Choropleth(
                geojson=MALHA, featureidkey="properties.codarea",
                locations=v["codigo_ibge"].astype(str), z=v["valor"].round(1), customdata=v[["nome"]],
                colorscale=ESCALA_LARANJA if var.startswith("tmax") else ESCALA_AZUL,
                marker=dict(line=dict(color="white", width=0.6)),
                colorbar=dict(title="°C", thickness=12, len=0.7),
                hovertemplate="<b>%{customdata[0]}</b><br>%{z:.1f} °C<extra></extra>",
            )
        )
        fig.add_trace(
            go.Choropleth(
                geojson=MALHA, featureidkey="properties.codarea", locations=[str(codigo())], z=[0],
                colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]], showscale=False,
                marker=dict(line=dict(color="#0b0b0b", width=2.5)), hoverinfo="skip",
            )
        )
        fig.update_geos(fitbounds="locations", visible=False)
        fig.update_layout(
            height=560, margin=dict(l=0, r=0, t=40, b=0), showlegend=False,
            title=dict(text=VARIAVEIS_MAPA[var] + " (Open-Meteo)", font=dict(size=15)),
            font=dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif"), separators=",.",
        )
        return fig

    @reactive.calc
    def tabela_dados() -> pd.DataFrame:
        p = periodo()
        return pd.DataFrame(
            {
                "data": p["data"].dt.strftime("%Y-%m-%d"),
                "municipio": municipio()["nome"],
                "tmax_c": p["tmax"].round(1),
                "tmin_c": p["tmin"].round(1),
                "fonte": p["fonte"],
            }
        )

    @render.data_frame
    def t_dados():
        return render.DataGrid(tabela_dados(), width="100%", height="420px")

    @render.download_button(filename=lambda: f"temperatura_{codigo()}_{input.periodo()[0]}_{input.periodo()[1]}.csv")
    def baixar():
        yield tabela_dados().to_csv(index=False)

    @render.ui
    def sobre():
        return ui.markdown(
            """
**Objetivo.** Acompanhar a temperatura máxima e mínima diária nos 146 municípios da mesorregião
Sul/Sudoeste de Minas (IBGE 3110), com dados atualizados todo dia.

**Fontes**

- **Open-Meteo**, Historical Weather API: reanálise ERA5 + análise ECMWF IFS, de 1991 até ontem.
  Forecast API: previsão de hoje + 7 dias e mapa regional. Sem chave, uso não comercial.
- **IBGE**: lista de municípios e malhas territoriais.

**Cuidados.** A Open-Meteo é dado de modelo em grade, não medição. Comparada com estações do INMET
da região, ela tende a subestimar a Tmax e superestimar a Tmin; por isso, os valores extremos devem
ser lidos com cautela.

Código e relatório: repositório do projeto no GitHub (`ic-temperatura-sul-minas`).
"""
        )


app = App(app_ui, server)
