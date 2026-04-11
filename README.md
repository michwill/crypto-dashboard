# Crypto Dashboard

Real-time cryptocurrency dashboard built with Python and Qt. Features candlestick charts, live price streaming from Binance, and a dynamic coin watchlist.

## Features

- **Candlestick charts** with OHLC data from Binance, updated in real time
- **Multiple timeframes**: 1m, 5m, 15m, 1h, 4h, 1d
- **Live ticker table** with price, 24h change, high/low, and volume
- **Add/remove coins** dynamically — your watchlist is saved across restarts
- **Crosshair** with price and time readout on hover
- **Dark theme** (Catppuccin Mocha)

## Quick Start

Requires [uv](https://docs.astral.sh/uv/):

```sh
./crypto-dashboard
```

Or run directly:

```sh
uv run crypto_dashboard.py
```

## Alternative Setup

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python crypto_dashboard.py
```

## Usage

- **Switch coins**: click the dropdown or double-click a table row
- **Change timeframe**: click the interval buttons (1m / 5m / 15m / 1h / 4h / 1d)
- **Add a coin**: click **+** and enter a Binance symbol (e.g. PEPE, SHIB, WIF)
- **Remove a coin**: right-click a table row
- **Zoom/pan**: scroll wheel and drag on the chart; right-click > View All to reset

## Data Sources

All data comes from Binance:
- WebSocket streams for live kline and mini-ticker updates
- REST API for historical candlesticks and 24hr ticker stats
