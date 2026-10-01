# Pesquisa de APIs de temperatura: Sul e Sudoeste de Minas

Todos os testes abaixo foram feitos com **chamadas reais em 01/10/2026**, no ponto da sede de
São Sebastião do Paraíso (−20,9167; −46,9837) ou nas estações da mesorregião (IBGE 3110, 146 municípios).

## Resumo

| Fonte | O que é | Atualização | Chave | Situação no teste | Uso no projeto |
|---|---|---|---|---|---|
| Open-Meteo, Historical Weather API | Reanálise ERA5 + análise ECMWF IFS (grade de 9–25 km) | Diária, dados até **ontem** | Não | ✅ 1991-01-01 → 2026-09-30, sem lacunas | Série principal |
| Open-Meteo, Forecast API | Previsão (combinação de modelos) | Várias vezes ao dia | Não | ✅ Hoje + até 16 dias; 146 pontos numa chamada (1,9 s) | Previsão e mapa regional |
| NASA POWER | MERRA-2 / GEOS (grade de ~0,5°) | Diária, defasagem de ~2–3 dias | Não | ✅ Último dia válido: 2026-09-28 | Comparação (dashboard) |
| INMET, API de estações (apitempo) | Observação horária das estações automáticas | Horária | **Sim (token)** | ⚠️ Catálogo aberto; dados exigem token | Catálogo de estações |
| INMET, BDMEP (arquivos anuais) | Observação horária em CSV por estação | Cerca de uma vez por mês | Não | ✅ 2026.zip (64 MB), dados até 31/08/2026 | Validação |
| Meteostat (bulk) | Observação SYNOP/ISD | Diária | Não | ❌ Estações da região param em 2022 | Não usada |
| NOAA NCEI (GSOD) | Observação ISD | Diária | Não | ❌ Nenhum dado de 2026 nas estações da região | Não usada |
| CPTEC/INPE via BrasilAPI | Previsão por cidade | Diária | Não | ❌ HTTP 500 na busca da cidade | Não usada |
| IBGE (localidades e malhas) | Municípios e polígonos | Estável | Não | ✅ 146 municípios, GeoJSON de 69 kB | Área de estudo |

## Detalhes por fonte

### Open-Meteo ([documentação](https://open-meteo.com/en/docs/historical-weather-api))

```text
https://archive-api.open-meteo.com/v1/archive?latitude=-20.9167&longitude=-46.9837
    &start_date=1991-01-01&end_date=2026-09-30
    &daily=temperature_2m_max,temperature_2m_min&timezone=America/Sao_Paulo
https://api.open-meteo.com/v1/forecast?latitude=...&longitude=...
    &daily=temperature_2m_max,temperature_2m_min&past_days=92&forecast_days=16
```

- Sem cadastro; gratuito para uso não comercial (limite de ~10 mil chamadas por dia); dados sob CC BY 4.0.
- Aceita vários pontos separados por vírgula numa única chamada, o que viabiliza o mapa dos 146 municípios.
- **Atenção:** é dado de modelo. Na validação com o INMET (jan.–ago. 2026), subestimou a Tmax em
  1,0–2,0 °C e superestimou a Tmin em 0,8–2,8 °C (exceto Machado, −2,2 °C), com correlação de 0,81 a 0,96.

### NASA POWER ([documentação](https://power.larc.nasa.gov/docs/services/api/))

```text
https://power.larc.nasa.gov/api/temporal/daily/point?parameters=T2M_MAX,T2M_MIN
    &community=AG&latitude=-20.917&longitude=-46.987&start=20260801&end=20260930&format=JSON
```

- Valor ausente = −999. Grade mais grossa (~50 km) e defasagem de 2–3 dias.

### INMET ([portal](https://portal.inmet.gov.br/), [dados históricos](https://portal.inmet.gov.br/dadoshistoricos))

- `https://apitempo.inmet.gov.br/estacoes/T` (automáticas) e `/estacoes/M` (convencionais): **abertos**,
  mas exigem um cabeçalho `User-Agent` de navegador (sem ele a conexão é recusada).
- Rotas públicas de dados (`/estacao/{inicio}/{fim}/{codigo}`) devolvem **204 (vazio)**; `/estacao/diaria/...` dá 404.
- Rota com token: `/token/estacao/{inicio}/{fim}/{codigo}/{TOKEN}`. Com um token inválido a resposta é
  `CHAVE INVÁLIDA!`. O token é pedido por e-mail a **cadastro.act@inmet.gov.br** (endereço citado por
  vários projetos que usam a API; vale confirmar com o INMET). A função `clima_ssm.inmet.dados_api()`
  já está pronta e lê o token da variável de ambiente `INMET_TOKEN`.
- BDMEP: `https://portal.inmet.gov.br/uploads/dadoshistoricos/{ANO}.zip`, com um CSV horário por estação
  (latin-1, separador `;`, vírgula decimal, hora em UTC).

**Estações automáticas dentro da mesorregião** (cobertura de Tmax diária em jan.–ago. 2026):

| Código | Estação | Município | Catálogo | Dias com Tmax em 2026 |
|---|---|---|---|---|
| A509 | Monte Verde | Camanducaia | Operante | 100% |
| A515 | Varginha | Varginha | Operante | 75% |
| A516 | Passos | Passos | Operante | 81% |
| A529 | Passa Quatro | Passa Quatro | Operante | 14% |
| A530 | Caldas | Caldas | Operante | 98% |
| A531 | Maria da Fé | Maria da Fé | Operante | 100% |
| A561 | São Sebastião do Paraíso | São Sebastião do Paraíso | **Pane** | **0%** |
| A567 | Machado | Machado | Operante | 68% |

Há também a convencional 83737 (Passa Quatro). A estação de SSP está sem dados de temperatura em 2026,
e a operante mais próxima é Passos (A516), a ~40 km.

### Fontes descartadas

- **Meteostat** (`https://bulk.meteostat.net/v2/...`): as estações da região (inclusive 83631, SSP) só têm
  dados diários até 2019–2022.
- **NOAA NCEI GSOD** (`https://www.ncei.noaa.gov/access/services/data/v1`): consultas de 2026 para
  Varginha, Passos, SSP e Caldas vieram vazias.
- **CPTEC/INPE via BrasilAPI**: HTTP 500 (`CITY_INTERNAL`) no teste; além disso, só oferece previsão.

### Não testadas (exigem cadastro/chave)

OpenWeatherMap, Visual Crossing, WeatherAPI e Tomorrow.io (comerciais, com plano gratuito limitado) e
Copernicus CDS/ERA5 (cadastro; ERA5T com ~5 dias de defasagem). Podem ser avaliadas depois, se necessário.
