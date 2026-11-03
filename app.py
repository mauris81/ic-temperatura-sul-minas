"""Dashboard de temperatura do Sul e Sudoeste de Minas (Shiny for Python).

Rodar localmente:  shiny run app.py   (ou o botão "Run Shiny App" no Positron)
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from shiny import App, reactive, render, req, ui
from shinywidgets import output_widget, render_plotly

from clima_ssm import fontes, ondas, regiao

COR_TMAX = "#eb6834"
COR_TMIN = "#2a78d6"
COR_GRADE = "#e1e0d9"
COR_TEXTO_2 = "#52514e"
COR_BARRA = "#a8401a"
COR_BARRA_PREVISTA = "#f19a6e"
ROTULO_LIMITE = {"p90_tmax": "P90 da Tmax", "p90_tmin": "P90 da Tmin", "normal5_tmax": "Normal da Tmax + 5 °C"}
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
def _limites(codigo: int, dia: dt.date) -> pd.DataFrame:
    return ondas.limites_diarios(_historico(codigo, dia))


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
            "Ondas de calor",
            ui.input_checkbox_group(
                "metodos", "Critérios (marque um para ver só ele, ou vários para comparar)",
                {k: m.nome for k, m in ondas.METODOS.items()}, selected=list(ondas.METODOS), inline=True,
            ),
            ui.div(
                ui.input_action_button("metodos_todos", "Marcar todos", class_="btn-sm btn-outline-secondary"),
                ui.input_action_button("metodos_limpar", "Desmarcar todos", class_="btn-sm btn-outline-secondary"),
                class_="d-flex gap-2 mb-2",
            ),
            output_widget("g_ondas"),
            ui.output_ui("nota_ondas"),
            ui.layout_columns(
                ui.div(ui.h6("Todos os critérios no período"), ui.output_data_frame("t_metodos")),
                ui.div(ui.h6("Ondas dos critérios marcados"), ui.output_data_frame("t_ondas")),
                col_widths={"sm": 12, "xl": (7, 5)},
            ),
        ),
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

    # --- ondas de calor ---

    @reactive.calc
    def janela_ondas() -> tuple[pd.Timestamp, pd.Timestamp]:
        """Período escolhido; se a previsão estiver ligada e o período chegar a ontem, vai até o fim dela."""
        inicio, fim = req(input.periodo())
        fim = pd.Timestamp(fim)
        if input.previsao() and fim.date() >= fontes.ontem() and not previsao().empty:
            fim = previsao()["data"].max()
        return pd.Timestamp(inicio), fim

    @reactive.calc
    def ondas_todas() -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
        """Dias marcados e eventos de cada critério, na série inteira (+ previsão, se ligada)."""
        serie = historico()[["data", "tmax", "tmin"]]
        if input.previsao():
            serie = pd.concat([serie, previsao()[["data", "tmax", "tmin"]]], ignore_index=True)
        lim = _limites(codigo(), fontes.hoje())
        return {k: ondas.ondas_por_metodo(serie, lim, m) for k, m in ondas.METODOS.items()}

    def _no_periodo(ev: pd.DataFrame) -> pd.DataFrame:
        inicio, fim = janela_ondas()
        return ev[(ev["fim"] >= inicio) & (ev["inicio"] <= fim)]

    @reactive.effect
    @reactive.event(input.metodos_todos)
    def _marcar_todos():
        ui.update_checkbox_group("metodos", selected=list(ondas.METODOS))

    @reactive.effect
    @reactive.event(input.metodos_limpar)
    def _desmarcar_todos():
        ui.update_checkbox_group("metodos", selected=[])

    @reactive.calc
    def metodos() -> list[str]:
        """Critérios marcados, sempre na ordem de ``ondas.METODOS``."""
        return [k for k in ondas.METODOS if k in input.metodos()]

    @render_plotly
    def g_ondas():
        escolhidos = metodos()
        todas = ondas_todas()
        inicio, fim = janela_ondas()
        d = todas["oliveira"][0]
        d = d[d["data"].between(inicio, fim)]
        req(not d.empty)
        hoje = pd.Timestamp(fontes.hoje())
        meio_dia = pd.Timedelta(hours=12)  # a barra/faixa cobre o dia inteiro
        n = len(escolhidos)
        alt_barras = 50 + 32 * n
        fig = make_subplots(
            rows=2 if n else 1, cols=1, shared_xaxes=True, vertical_spacing=0.05,
            row_heights=[400, alt_barras] if n else None,
        )

        # em cima: temperaturas e os limites que os critérios marcados usam
        usadas = {lim: var for k in escolhidos for var, lim in ondas.METODOS[k].condicoes}
        for var, cor, nome in (("tmax", COR_TMAX, "Tmax"), ("tmin", COR_TMIN, "Tmin")):
            fig.add_scatter(
                x=d["data"], y=d[var], name=nome, mode="lines", line=dict(color=cor, width=1.5),
                opacity=1 if var in usadas.values() else 0.3, hovertemplate="%{y:.1f} °C", row=1, col=1,
            )
        for lim, rotulo in ROTULO_LIMITE.items():
            if lim in usadas:
                fig.add_scatter(
                    x=d["data"], y=d[lim], name=rotulo, mode="lines", hovertemplate="%{y:.1f} °C", row=1, col=1,
                    line=dict(color=COR_TMAX if usadas[lim] == "tmax" else COR_TMIN, width=1.3,
                              dash="dash" if lim == "normal5_tmax" else "dot"),
                )

        # embaixo: uma linha por critério, uma barra por onda
        for k in escolhidos:
            m = ondas.METODOS[k]
            ev = _no_periodo(todas[k][1])
            for prevista, cor in ((False, COR_BARRA), (True, COR_BARRA_PREVISTA)):
                xs = []
                for e in ev[(ev["fim"] >= hoje) == prevista].itertuples():
                    xs += [e.inicio - meio_dia, e.fim + meio_dia, None]
                fig.add_scatter(
                    x=xs, y=[None if x is None else m.nome for x in xs], mode="lines", showlegend=False,
                    line=dict(color=cor, width=14), hoverinfo="skip", row=2, col=1,
                )
            dias, texto = [], []  # pontos invisíveis, um por dia de onda, só para o tooltip
            for e in ev.itertuples():
                datas = pd.date_range(e.inicio, e.fim)
                dias += list(datas)
                texto += [f"{e.inicio:%d/%m} a {e.fim:%d/%m/%Y} ({e.duracao} dias)"] * len(datas)
            fig.add_scatter(  # o primeiro ponto, sem texto, garante a linha do critério mesmo sem ondas
                x=[inicio] + dias, y=[m.nome] * (len(dias) + 1), text=[""] + texto, mode="markers",
                marker=dict(size=14, color="rgba(0,0,0,0)"), name=m.nome, showlegend=False,
                hovertemplate="%{text}<extra>%{fullData.name}</extra>", row=2, col=1,
            )

        if n:  # em cima, o fundo de cada dia escurece com o número de critérios que o põem em onda
            votos = pd.Series(0, index=pd.DatetimeIndex(d["data"]))
            for k in escolhidos:
                for e in _no_periodo(todas[k][1]).itertuples():
                    votos[e.inicio:e.fim] += 1
            trecho = votos.ne(votos.shift()).cumsum()  # dias seguidos com o mesmo número de votos
            fig.update_layout(shapes=[
                dict(
                    type="rect", xref="x", yref="y domain", y0=0, y1=1, layer="below", line_width=0,
                    x0=t.index[0] - meio_dia, x1=t.index[-1] + meio_dia,
                    fillcolor=f"rgba(235, 104, 52, {0.04 + 0.28 * t.iloc[0] / n:.3f})",
                )
                for _, t in votos.groupby(trecho) if t.iloc[0] > 0
            ])
            fig.add_scatter(
                x=votos.index, y=d["tmax"], text=[f"{v} de {n}" for v in votos], mode="markers",
                marker=dict(color="rgba(0,0,0,0)"), name="Critérios em onda", showlegend=False,
                hovertemplate="%{text}", row=1, col=1,
            )
            fig.add_scatter(
                x=[None], y=[None], mode="markers", hoverinfo="skip", row=1, col=1,
                name="Dia em onda (mais escuro = mais critérios)" if n > 1 else "Dia em onda",
                marker=dict(symbol="square", size=13, color="rgba(235, 104, 52, 0.32)"),
            )
        if d["data"].max() >= hoje:
            fig.add_vline(x=hoje, line=dict(color="#898781", width=1, dash="dash"), row="all", col=1)
            fig.add_annotation(
                x=hoje, y=1, xref="x", yref="paper", text="previsão →", showarrow=False, xanchor="left",
                font=dict(size=11, color=COR_TEXTO_2),
            )

        if n == 1:
            q = len(_no_periodo(todas[escolhidos[0]][1]))
            titulo = f"{ondas.METODOS[escolhidos[0]].nome}: {q} onda{'s' if q != 1 else ''} de calor no período"
        elif n:
            titulo = f"Ondas de calor por critério ({n} critérios)"
        else:
            titulo = "Marque ao menos um critério para ver as ondas de calor"
        fig.update_layout(title=dict(text=f"{titulo}, {municipio()['nome']}"))
        fig.update_xaxes(tickformat="%m/%Y", hoverformat="%d/%m/%Y")
        _layout(fig, 400 + (alt_barras if n else 0) + 70)
        fig.update_yaxes(automargin=True)
        if n:
            nomes = [ondas.METODOS[k].nome for k in escolhidos]
            fig.update_yaxes(
                row=2, col=1, ticksuffix="", showgrid=False, fixedrange=True, tickfont=dict(size=11),
                categoryorder="array", categoryarray=nomes[::-1], range=[-0.6, n - 0.4],
            )
        return fig

    @render.ui
    def nota_ondas():
        return ui.p(
            "Embaixo, cada linha é um critério e cada barra é uma onda de calor (as barras claras entram na "
            "previsão). Em cima, o fundo laranja marca os dias em onda: quanto mais escuro, mais critérios marcados "
            "concordam (passe o mouse para ver quantos). "
            "O P90 e a normal de cada dia do ano vêm de 1991–2020, numa janela de 15 dias. "
            "Intensidade: quanto, em média, a temperatura passou do limite nos dias da onda.",
            class_="text-muted small",
        )

    @render.data_frame
    def t_metodos():
        linhas = []
        for k, m in ondas.METODOS.items():
            ev = _no_periodo(ondas_todas()[k][1])
            linhas.append({
                "Critério": m.nome,
                "Regra": m.descricao,
                "Ondas": len(ev),
                "Dias em onda": int(ev["duracao"].sum()),
                "Maior (dias)": int(ev["duracao"].max()) if len(ev) else 0,
                "Intensidade (°C)": round(ev["intensidade"].mean(), 1) if len(ev) else None,
            })
        return render.DataGrid(pd.DataFrame(linhas), width="100%")

    @render.data_frame
    def t_ondas():
        hoje = pd.Timestamp(fontes.hoje())
        partes = [_no_periodo(ondas_todas()[k][1]).assign(criterio=ondas.METODOS[k].nome) for k in metodos()]
        req(partes)
        ev = pd.concat(partes).sort_values("inicio", ascending=False, kind="stable")
        tabela = pd.DataFrame({
            "Critério": ev["criterio"],
            "Início": ev["inicio"].dt.strftime("%d/%m/%Y"),
            "Fim": ev["fim"].dt.strftime("%d/%m/%Y"),
            "Dias": ev["duracao"],
            "Intensidade (°C)": ev["intensidade"].round(1),
            "Pico (°C)": ev["pico"].round(1),
            "Prevista": (ev["fim"] >= hoje).map({True: "sim", False: ""}),
        })
        return render.DataGrid(tabela, width="100%", height="360px")

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

**Ondas de calor.** Sete critérios da literatura (tabela de Fante, 2024): WSDI da OMM, IPCC,
Silveira (2014), Díaz et al. (2002), Geirinhas et al. (2018, pela Tmax e pela Tmin) e
Oliveira et al. (2021), que é o usado no artigo. Todos comparam o dia com o limite do seu dia do ano
(P90 ou normal + 5 °C), calculado em 1991–2020 numa janela de 15 dias; mudam a variável e a duração mínima.

**Cuidados.** A Open-Meteo é dado de modelo em grade, não medição. Comparada com estações do INMET
da região, ela tende a subestimar a Tmax e superestimar a Tmin; por isso, os valores extremos devem
ser lidos com cautela.

Código e relatório: repositório do projeto no GitHub (`ic-temperatura-sul-minas`).
"""
        )


app = App(app_ui, server)
