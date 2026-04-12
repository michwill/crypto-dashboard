#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "PyQt6",
#     "pyqtgraph",
#     "requests",
#     "websocket-client",
#     "numpy",
#     "platformdirs",
# ]
# ///
"""Real-time cryptocurrency dashboard with candlestick charts."""

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from queue import Queue

import platformdirs

os.environ["QT_LOGGING_RULES"] = "qt.qpa.theme.gnome.warning=false"

import numpy as np
import pyqtgraph as pg
import requests
import websocket
from PyQt6.QtCore import (
    QEvent, QPointF, QRect, QRectF, QSize, QTimer, Qt, pyqtSignal, QObject,
)
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPicture, QPixmap,
    QRegion,
)
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QGraphicsItem, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

# ── Configuration ───────────────────────────────────────────────────────────

INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]

DEFAULT_SYMBOLS = ["BTC", "ETH", "SOL"]

COLORS = [
    "#f7931a", "#627eea", "#9945ff", "#0033ad", "#00aae4",
    "#e6007a", "#c2a633", "#e84142", "#2a5ada", "#8247e5",
    "#bfbbbb", "#ff007a", "#14b8a6", "#2e3148", "#00ec97",
    "#06d6a0", "#4da2ff", "#28a0f0", "#ff0420", "#e14eff",
    "#ff6b6b", "#4ecdc4", "#45b7d1", "#96ceb4", "#ffeaa7",
    "#dfe6e9", "#fd79a8", "#6c5ce7", "#00b894", "#e17055",
]

CANDLE_LIMIT = 200
WS_URL = "wss://stream.binance.com:9443/ws"
REST_URL = "https://api.binance.com/api/v3"
CONFIG_DIR = Path(platformdirs.user_config_dir("crypto-dashboard"))
CONFIG_FILE = CONFIG_DIR / "coins.json"
ICON_CACHE_DIR = Path(platformdirs.user_cache_dir("crypto-dashboard")) / "icons"


# ── Candlestick Graphics Item ──────────────────────────────────────────────

class CandlestickItem(pg.GraphicsObject):
    """Custom pyqtgraph item that draws OHLC candlesticks."""

    def __init__(self):
        super().__init__()
        self._data = np.empty((0, 5))   # Nx5: time, open, high, low, close
        self._picture = None

    def set_data(self, data):
        """Set OHLC data as an Nx5 numpy array [time, open, high, low, close]."""
        if len(data) > 0:
            self._data = data[:, :5]
        else:
            self._data = np.empty((0, 5))
        self._picture = None
        self.prepareGeometryChange()
        self.informViewBoundsChanged()
        self.update()

    def _generate_picture(self):
        self._picture = QPicture()
        p = QPainter(self._picture)
        data = self._data
        n = len(data)
        if n == 0:
            p.end()
            return

        w = (data[1, 0] - data[0, 0]) * 0.4 if n >= 2 else 30.0
        bull = QColor("#a6e3a1")
        bear = QColor("#f38ba8")
        bull_pen = pg.mkPen(bull, width=1)
        bear_pen = pg.mkPen(bear, width=1)
        bull_brush = pg.mkBrush(bull)
        bear_brush = pg.mkBrush(bear)

        for i in range(n):
            t, o, h, l, c = data[i]
            if c >= o:
                p.setPen(bull_pen)
                p.setBrush(bull_brush)
            else:
                p.setPen(bear_pen)
                p.setBrush(bear_brush)
            # Wick
            p.drawLine(QPointF(t, l), QPointF(t, h))
            # Body
            body = c - o
            if abs(body) < (h - l) * 0.004:
                body = (h - l) * 0.004 or 0.01
                if c < o:
                    body = -body
            p.drawRect(QRectF(t - w, o, w * 2, body))

        p.end()

    def paint(self, painter, option, widget):
        if self._picture is None:
            self._generate_picture()
        self._picture.play(painter)

    def boundingRect(self):
        if len(self._data) == 0:
            return QRectF()
        xmin, xmax = self._data[0, 0], self._data[-1, 0]
        ymin = float(self._data[:, 3].min())
        ymax = float(self._data[:, 2].max())
        margin = (ymax - ymin) * 0.05 or 1.0
        if len(self._data) >= 2:
            bar_w = self._data[1, 0] - self._data[0, 0]
        else:
            bar_w = 60
        return QRectF(xmin - bar_w, ymin - margin,
                      (xmax - xmin) + 2 * bar_w, (ymax - ymin) + 2 * margin)


# ── Volume Graphics Item ───────────────────────────────────────────────────

class VolumeItem(pg.GraphicsObject):
    """Translucent volume bars coloured by candle direction (bull/bear)."""

    def __init__(self):
        super().__init__()
        self._data = np.empty((0, 6))  # same Nx6 OHLCV as Dashboard._ohlc
        self._picture = None

    def set_data(self, data):
        self._data = data if len(data) > 0 else np.empty((0, 6))
        self._picture = None
        self.prepareGeometryChange()
        self.informViewBoundsChanged()
        self.update()

    def _generate_picture(self):
        self._picture = QPicture()
        p = QPainter(self._picture)
        data = self._data
        n = len(data)
        if n == 0:
            p.end()
            return

        w = (data[1, 0] - data[0, 0]) * 0.4 if n >= 2 else 30.0
        bull = QColor("#a6e3a1")
        bull.setAlpha(110)
        bear = QColor("#f38ba8")
        bear.setAlpha(110)
        bull_brush = pg.mkBrush(bull)
        bear_brush = pg.mkBrush(bear)
        p.setPen(Qt.PenStyle.NoPen)

        for i in range(n):
            t, o, _h, _l, c, v = data[i]
            p.setBrush(bull_brush if c >= o else bear_brush)
            p.drawRect(QRectF(t - w, 0.0, w * 2, v))

        p.end()

    def paint(self, painter, option, widget):
        if self._picture is None:
            self._generate_picture()
        self._picture.play(painter)

    def boundingRect(self):
        if len(self._data) == 0:
            return QRectF()
        xmin, xmax = self._data[0, 0], self._data[-1, 0]
        vmax = float(self._data[:, 5].max()) or 1.0
        if len(self._data) >= 2:
            bar_w = self._data[1, 0] - self._data[0, 0]
        else:
            bar_w = 60
        return QRectF(xmin - bar_w, 0.0,
                      (xmax - xmin) + 2 * bar_w, vmax)


# ── Crosshair Overlay ──────────────────────────────────────────────────────

class CrosshairOverlay(QWidget):
    """Transparent overlay that paints a crosshair without touching the
    underlying QGraphicsScene. Mouse moves only repaint two narrow strips on
    this widget — the chart's scene is never marked dirty."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._x = -1
        self._y = -1
        self._text = ""
        self._active = False
        self._pen = QPen(QColor("#585b70"))
        self._pen.setWidth(1)
        self._pen.setStyle(Qt.PenStyle.DashLine)
        self._font = QFont("monospace", 9)
        self._fm = QFontMetrics(self._font)
        self._text_color = QColor("#cdd6f4")
        self._bg_color = QColor(30, 30, 46, 220)

    def set_position(self, x, y, text):
        if (self._active and x == self._x and y == self._y
                and text == self._text):
            return
        region = self._dirty_region()
        self._x = x
        self._y = y
        self._text = text
        self._active = True
        region = region.united(self._dirty_region())
        self.update(region)

    def clear(self):
        if not self._active:
            return
        region = self._dirty_region()
        self._active = False
        self.update(region)

    def _dirty_region(self):
        if not self._active or self._x < 0:
            return QRegion()
        w = self.width()
        h = self.height()
        region = QRegion(self._x - 1, 0, 3, h)
        region += QRegion(0, self._y - 1, w, 3)
        if self._text:
            tw = self._fm.horizontalAdvance(self._text)
            th = self._fm.height()
            tx = self._x + 6
            ty = self._y - 6 - th
            if tx + tw + 4 > w:
                tx = self._x - 6 - tw
            if ty < 0:
                ty = self._y + 6
            region += QRegion(tx - 3, ty - 1, tw + 6, th + 2)
        return region

    def paintEvent(self, ev):
        if not self._active or self._x < 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(self._pen)
        p.drawLine(self._x, 0, self._x, self.height())
        p.drawLine(0, self._y, self.width(), self._y)
        if self._text:
            p.setFont(self._font)
            tw = self._fm.horizontalAdvance(self._text)
            th = self._fm.height()
            asc = self._fm.ascent()
            tx = self._x + 6
            ty = self._y - 6 - th
            if tx + tw + 4 > self.width():
                tx = self._x - 6 - tw
            if ty < 0:
                ty = self._y + 6
            p.fillRect(QRect(tx - 3, ty - 1, tw + 6, th + 2), self._bg_color)
            p.setPen(self._text_color)
            p.drawText(tx, ty + asc, self._text)


# ── Qt Signals ──────────────────────────────────────────────────────────────

class Signals(QObject):
    ticker_update = pyqtSignal(str, dict)           # symbol, ticker data
    kline_update = pyqtSignal(str, dict)            # symbol, kline data
    candles_loaded = pyqtSignal(str, str, object)   # symbol, interval, np array
    coin_validated = pyqtSignal(str, bool, str)     # symbol, valid, error
    icon_ready = pyqtSignal(str, str)               # symbol, file path


# ── Binance WebSocket ───────────────────────────────────────────────────────

class BinanceWS(threading.Thread):
    """WebSocket with dynamic subscribe/unsubscribe for live data."""

    def __init__(self, signals):
        super().__init__(daemon=True)
        self.signals = signals
        self._ws = None
        self._connected = threading.Event()
        self._lock = threading.Lock()
        self._subscriptions = set()
        self._msg_id = 0

    def subscribe(self, streams):
        with self._lock:
            new = [s for s in streams if s not in self._subscriptions]
            if not new:
                return
            self._subscriptions.update(new)
            if self._connected.is_set() and self._ws:
                self._send_sub("SUBSCRIBE", new)

    def unsubscribe(self, streams):
        with self._lock:
            old = [s for s in streams if s in self._subscriptions]
            if not old:
                return
            self._subscriptions -= set(old)
            if self._connected.is_set() and self._ws:
                self._send_sub("UNSUBSCRIBE", old)

    def _send_sub(self, method, params):
        self._msg_id += 1
        try:
            self._ws.send(json.dumps({
                "method": method, "params": params, "id": self._msg_id,
            }))
        except Exception as exc:
            print(f"[ws] {method} error: {exc}")

    def run(self):
        while True:
            try:
                self._do_connect()
            except Exception as exc:
                print(f"[ws] connection error: {exc}")
            self._connected.clear()
            time.sleep(3)

    def _do_connect(self):
        def on_open(ws):
            self._ws = ws
            self._connected.set()
            with self._lock:
                if self._subscriptions:
                    self._send_sub("SUBSCRIBE", list(self._subscriptions))

        def on_message(_ws, raw):
            msg = json.loads(raw)
            if "stream" in msg and "data" in msg:
                self._route(msg["stream"], msg["data"])
            elif "e" in msg:
                # Raw-format event (no stream wrapper)
                self._route_raw(msg)

        def on_error(_ws, err):
            print(f"[ws] error: {err}")

        def on_close(_ws, _code, _reason):
            self._connected.clear()

        app = websocket.WebSocketApp(
            WS_URL, on_open=on_open, on_message=on_message,
            on_error=on_error, on_close=on_close,
        )
        app.run_forever(ping_interval=30)

    def _route_raw(self, data):
        """Handle raw-format events (no stream wrapper)."""
        e = data.get("e", "")
        sym = data.get("s", "")
        if e == "24hrMiniTicker":
            self._route(f"{sym.lower()}@miniTicker", data)
        elif e == "kline":
            iv = data.get("k", {}).get("i", "")
            self._route(f"{sym.lower()}@kline_{iv}", data)

    def _route(self, stream, data):
        if "@miniTicker" in stream:
            sym = data["s"]
            if sym.endswith("USDT"):
                sym = sym[:-4]
            self.signals.ticker_update.emit(sym, {
                "price": float(data["c"]),
                "open": float(data["o"]),
                "high": float(data["h"]),
                "low": float(data["l"]),
                "volume": float(data["v"]),
                "quote_volume": float(data["q"]),
            })
        elif "@kline_" in stream:
            k = data["k"]
            sym = k["s"]
            if sym.endswith("USDT"):
                sym = sym[:-4]
            self.signals.kline_update.emit(sym, {
                "t": k["t"] / 1000.0,
                "o": float(k["o"]),
                "h": float(k["h"]),
                "l": float(k["l"]),
                "c": float(k["c"]),
                "v": float(k["v"]),
                "closed": k["x"],
            })


# ── Icon Fetcher ───────────────────────────────────────────────────────────

class IconFetcher(threading.Thread):
    """Downloads coin icons from CoinGecko and caches them locally."""

    SEARCH_URL = "https://api.coingecko.com/api/v3/search"

    def __init__(self, signals):
        super().__init__(daemon=True)
        self.signals = signals
        self._queue = Queue()

    def enqueue(self, symbol):
        self._queue.put(symbol)

    def run(self):
        ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        while True:
            symbol = self._queue.get()
            try:
                self._fetch(symbol)
            except Exception:
                pass
            time.sleep(0.5)

    def _fetch(self, symbol):
        path = ICON_CACHE_DIR / f"{symbol.lower()}.png"
        if path.exists():
            self.signals.icon_ready.emit(symbol, str(path))
            return
        resp = requests.get(
            self.SEARCH_URL, params={"query": symbol}, timeout=10)
        if resp.status_code != 200:
            return
        coins = resp.json().get("coins", [])
        for coin in sorted(
                coins, key=lambda c: c.get("market_cap_rank") or 9999):
            if coin.get("symbol", "").upper() == symbol.upper():
                img_url = coin.get("large") or coin.get("thumb")
                if img_url:
                    img_resp = requests.get(img_url, timeout=10)
                    if img_resp.status_code == 200:
                        path.write_bytes(img_resp.content)
                        self.signals.icon_ready.emit(symbol, str(path))
                return


# ── REST Ticker Poller ──────────────────────────────────────────────────────

class TickerPoller(threading.Thread):
    """Polls Binance REST for 24hr ticker data — reliable fallback for the table."""

    def __init__(self, signals, coins_getter, interval=10):
        super().__init__(daemon=True)
        self.signals = signals
        self._get_coins = coins_getter
        self.interval = interval

    def run(self):
        while True:
            try:
                self._poll()
            except Exception as exc:
                print(f"[rest] ticker poll error: {exc}")
            time.sleep(self.interval)

    def _poll(self):
        coins = self._get_coins()
        for symbol in coins:
            pair = f"{symbol}USDT"
            try:
                resp = requests.get(f"{REST_URL}/ticker/24hr",
                                    params={"symbol": pair}, timeout=5)
                if resp.status_code != 200:
                    continue
                d = resp.json()
                self.signals.ticker_update.emit(symbol, {
                    "price": float(d["lastPrice"]),
                    "open": float(d["openPrice"]),
                    "high": float(d["highPrice"]),
                    "low": float(d["lowPrice"]),
                    "volume": float(d["volume"]),
                    "quote_volume": float(d["quoteVolume"]),
                })
            except Exception:
                pass


# ── Ticker Table ────────────────────────────────────────────────────────────

class TickerTable(QTableWidget):
    COLUMNS = ["Coin", "Price", "24h %", "High", "Low", "Volume"]

    def __init__(self, parent=None):
        super().__init__(0, len(self.COLUMNS), parent)
        self.symbols = []
        self.setHorizontalHeaderLabels(self.COLUMNS)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setFont(QFont("monospace", 10))

    def add_coin(self, symbol, color):
        row = self.rowCount()
        self.insertRow(row)
        self.symbols.append(symbol)
        item = QTableWidgetItem(f" {symbol}")
        item.setForeground(QColor(color))
        self.setItem(row, 0, item)

    def remove_coin(self, symbol):
        if symbol not in self.symbols:
            return
        idx = self.symbols.index(symbol)
        self.symbols.pop(idx)
        self.removeRow(idx)

    def update_ticker(self, symbol, data):
        if symbol not in self.symbols:
            return
        row = self.symbols.index(symbol)
        price = data.get("price")
        self._set_cell(row, 1, self._fmt_price(price))
        open_24h = data.get("open")
        if open_24h and price and open_24h != 0:
            pct = ((price - open_24h) / open_24h) * 100
            color = "#a6e3a1" if pct >= 0 else "#f38ba8"
            self._set_cell(row, 2, f"{pct:+.2f}%", color)
        self._set_cell(row, 3, self._fmt_price(data.get("high")))
        self._set_cell(row, 4, self._fmt_price(data.get("low")))
        self._set_cell(row, 5, self._fmt_vol(data.get("quote_volume")))

    def _set_cell(self, row, col, text, color="#cdd6f4"):
        item = self.item(row, col)
        if item is None:
            item = QTableWidgetItem()
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.setItem(row, col, item)
        item.setText(str(text))
        item.setForeground(QColor(color))

    @staticmethod
    def _fmt_price(v):
        if v is None:
            return "—"
        if v >= 1:
            return f"${v:,.2f}"
        if v >= 0.01:
            return f"${v:.4f}"
        return f"${v:.8f}"

    @staticmethod
    def _fmt_vol(v):
        if v is None:
            return "—"
        if v >= 1e9:
            return f"${v / 1e9:.2f}B"
        if v >= 1e6:
            return f"${v / 1e6:.1f}M"
        if v >= 1e3:
            return f"${v / 1e3:.0f}K"
        return f"${v:,.0f}"


# ── Main Dashboard ──────────────────────────────────────────────────────────

class Dashboard(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Crypto Dashboard")
        self.resize(1400, 850)

        self.coins = self._load_coins()
        self._active_coin = self.coins[0]
        self._active_interval = "1h"
        self._ohlc = np.empty((0, 6))
        self._ticker_cache = {}          # symbol -> latest ticker dict
        self._current_price = None

        self.signals = Signals()
        self._setup_ui()
        self._connect_signals()
        self._start_feeds()

    # ── UI setup ────────────────────────────────────────────────────────────

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # ── Top bar: title, intervals, coin selector, add button ──
        top = QHBoxLayout()
        title = QLabel("Crypto Dashboard")
        title.setFont(QFont("sans-serif", 16, QFont.Weight.Bold))
        top.addWidget(title)
        top.addStretch()

        self._interval_btns = {}
        for iv in INTERVALS:
            btn = QPushButton(iv)
            btn.setCheckable(True)
            btn.setFixedWidth(48)
            btn.setStyleSheet("""
                QPushButton          { background:#313244; color:#a6adc8;
                                       border:none; border-radius:3px; padding:4px; }
                QPushButton:checked  { background:#89b4fa; color:#1e1e2e; }
                QPushButton:hover    { background:#45475a; }
            """)
            btn.clicked.connect(lambda _, i=iv: self._on_interval_changed(i))
            top.addWidget(btn)
            self._interval_btns[iv] = btn
        self._interval_btns[self._active_interval].setChecked(True)

        top.addSpacing(12)

        self.coin_selector = QComboBox()
        self.coin_selector.setMinimumWidth(130)
        self.coin_selector.setIconSize(QSize(20, 20))
        self.coin_selector.setStyleSheet(
            "QComboBox { background:#313244; color:#cdd6f4; padding:4px 8px;"
            " border-radius:4px; }"
            "QComboBox QAbstractItemView { background:#313244; color:#cdd6f4; }")
        for sym in self.coins:
            self.coin_selector.addItem(sym)
        self.coin_selector.currentTextChanged.connect(
            lambda s: self._switch_chart(symbol=s))
        top.addWidget(self.coin_selector)

        add_btn = QPushButton("+")
        add_btn.setFixedSize(32, 32)
        add_btn.setStyleSheet(
            "QPushButton { background:#313244; color:#a6e3a1; font-size:18px;"
            " border:none; border-radius:4px; }"
            "QPushButton:hover { background:#45475a; }")
        add_btn.setToolTip("Add a coin")
        add_btn.clicked.connect(self._on_add_clicked)
        top.addWidget(add_btn)

        root.addLayout(top)

        # ── Coin info label ──
        self._coin_info = QLabel()
        self._coin_info.setStyleSheet(
            "font-size:13px; padding:2px 4px; color:#a6adc8;")
        root.addWidget(self._coin_info)
        self._update_coin_info_label()

        # ── Splitter: chart + table ──
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Chart
        date_axis = pg.DateAxisItem()
        self.chart = pg.PlotWidget(
            axisItems={"bottom": date_axis}, background="#1e1e2e")
        self.chart.setLabel("left", "Price", units="$", color="#cdd6f4")
        self.chart.showGrid(x=True, y=True, alpha=0.15)
        self.chart.setMouseEnabled(x=True, y=True)
        self.chart.getAxis("left").setPen(pg.mkPen("#585b70"))
        self.chart.getAxis("bottom").setPen(pg.mkPen("#585b70"))

        self._candle_item = CandlestickItem()
        self._candle_item.setCacheMode(
            QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.chart.addItem(self._candle_item)

        # Volume overlay — separate ViewBox sharing X with the price plot,
        # with its own Y scaled so bars occupy the bottom ~20% of the chart.
        self._vol_vb = pg.ViewBox(enableMenu=False)
        self._vol_vb.setMouseEnabled(x=False, y=False)
        self._vol_vb.setZValue(-1000)
        self.chart.plotItem.scene().addItem(self._vol_vb)
        self._vol_vb.setXLink(self.chart.plotItem.vb)
        self._volume_item = VolumeItem()
        self._volume_item.setCacheMode(
            QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self._vol_vb.addItem(self._volume_item)

        def _sync_vol_geom():
            self._vol_vb.setGeometry(
                self.chart.plotItem.vb.sceneBoundingRect())
            self._vol_vb.linkedViewChanged(
                self.chart.plotItem.vb, self._vol_vb.XAxis)
        _sync_vol_geom()
        self.chart.plotItem.vb.sigResized.connect(_sync_vol_geom)

        # Crosshair — drawn on a transparent overlay widget so mouse moves
        # only repaint two narrow strips on the overlay; the chart's scene
        # (candles, volume, axes) is never marked dirty.
        self._xhair_overlay = CrosshairOverlay(self.chart.viewport())
        self._xhair_overlay.resize(self.chart.viewport().size())
        self._xhair_overlay.show()
        self._xhair_overlay.raise_()
        # Throttle hover mouse-moves at the source so pyqtgraph's scene
        # doesn't run hit-testing/hover dispatch at the OS mouse rate.
        self._last_hover_time = 0.0
        self._hover_min_interval = 1.0 / 30.0
        self.chart.viewport().installEventFilter(self)
        self.chart.scene().sigMouseMoved.connect(self._on_mouse_moved)

        # Current price line & label
        self._price_line = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen("#89b4fa", width=1, style=Qt.PenStyle.DashLine))
        self.chart.addItem(self._price_line, ignoreBounds=True)
        self._price_line.hide()

        self._price_label = pg.TextItem(
            color="#1e1e2e", anchor=(0, 0.5),
            fill=pg.mkBrush("#89b4fa"))
        self._price_label.setFont(QFont("monospace", 9, QFont.Weight.Bold))
        self._price_label.setZValue(100)
        self.chart.addItem(self._price_label, ignoreBounds=True)
        self._price_label.hide()

        self.chart.plotItem.vb.sigRangeChanged.connect(
            self._reposition_price_label)

        splitter.addWidget(self.chart)

        # Table
        self.table = TickerTable()
        self.table.setIconSize(QSize(20, 20))
        for i, sym in enumerate(self.coins):
            self.table.add_coin(sym, COLORS[i % len(COLORS)])
        self.table.cellDoubleClicked.connect(self._on_table_dbl_click)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_ctx_menu)
        splitter.addWidget(self.table)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter)

        # Status bar
        self.status_label = QLabel("Connecting…")
        self.status_label.setStyleSheet("color:#a6adc8; font-size:11px;")
        self.statusBar().addPermanentWidget(self.status_label)
        self.statusBar().setStyleSheet("background:#181825; border-top:1px solid #313244;")

    def _connect_signals(self):
        self.signals.ticker_update.connect(self._on_ticker)
        self.signals.kline_update.connect(self._on_kline)
        self.signals.candles_loaded.connect(self._on_candles_loaded)
        self.signals.coin_validated.connect(self._on_coin_validated)
        self.signals.icon_ready.connect(self._on_icon_ready)

        # Batch table refreshes at 2 Hz
        self._table_timer = QTimer(self)
        self._table_timer.setInterval(500)
        self._table_timer.timeout.connect(self._flush_table)
        self._table_timer.start()

        # Status bar clock
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._update_status)
        self._clock.start()

    # ── Feed startup ────────────────────────────────────────────────────────

    def _start_feeds(self):
        self._ws = BinanceWS(self.signals)
        self._ws.start()

        # Subscribe mini-tickers for all coins
        streams = [f"{s.lower()}usdt@miniTicker" for s in self.coins]
        self._ws.subscribe(streams)

        # REST ticker poller — fills the table immediately and keeps it updated
        self._ticker_poller = TickerPoller(
            self.signals, lambda: list(self.coins), interval=10)
        self._ticker_poller.start()

        # Load cached icons immediately, fetch missing ones in background
        self._icon_fetcher = IconFetcher(self.signals)
        self._icon_fetcher.start()
        for sym in self.coins:
            path = ICON_CACHE_DIR / f"{sym.lower()}.png"
            if path.exists():
                self._on_icon_ready(sym, str(path))
            else:
                self._icon_fetcher.enqueue(sym)

        # Load initial chart
        self._switch_chart(self._active_coin, self._active_interval)

    # ── Chart switching ─────────────────────────────────────────────────────

    def _switch_chart(self, symbol=None, interval=None):
        old_sym, old_iv = self._active_coin, self._active_interval
        if symbol is not None:
            self._active_coin = symbol
        if interval is not None:
            self._active_interval = interval

        # Unsubscribe old kline stream
        old_stream = f"{old_sym.lower()}usdt@kline_{old_iv}"
        self._ws.unsubscribe([old_stream])

        # Subscribe new kline stream
        new_stream = f"{self._active_coin.lower()}usdt@kline_{self._active_interval}"
        self._ws.subscribe([new_stream])

        # Hide price line until new data arrives
        self._current_price = None
        self._price_line.hide()
        self._price_label.hide()

        # Fetch historical candles in background
        self._load_candles(self._active_coin, self._active_interval)

        # Sync dropdown (avoid re-triggering signal)
        self.coin_selector.blockSignals(True)
        idx = self.coin_selector.findText(self._active_coin)
        if idx >= 0:
            self.coin_selector.setCurrentIndex(idx)
        self.coin_selector.blockSignals(False)

        self._update_coin_info_label()

    def _load_candles(self, symbol, interval):
        def worker():
            pair = f"{symbol}USDT"
            try:
                resp = requests.get(f"{REST_URL}/klines", params={
                    "symbol": pair, "interval": interval, "limit": CANDLE_LIMIT,
                }, timeout=10)
                resp.raise_for_status()
                raw = resp.json()
                data = np.array([
                    [float(k[0]) / 1000, float(k[1]), float(k[2]),
                     float(k[3]), float(k[4]), float(k[5])]
                    for k in raw
                ])
                self.signals.candles_loaded.emit(symbol, interval, data)
            except Exception as exc:
                print(f"[rest] kline fetch error for {pair}: {exc}")
        threading.Thread(target=worker, daemon=True).start()

    # ── Signal handlers ─────────────────────────────────────────────────────

    def _on_candles_loaded(self, symbol, interval, data):
        if symbol != self._active_coin or interval != self._active_interval:
            return
        self._ohlc = data
        self._candle_item.set_data(data)
        self._volume_item.set_data(data)
        self._rescale_volume()
        self.chart.enableAutoRange()
        if len(data) > 0:
            self._update_price_line(float(data[-1, 4]))

    def _on_kline(self, symbol, kline):
        if symbol != self._active_coin:
            return
        t = kline["t"]
        row = np.array([t, kline["o"], kline["h"], kline["l"],
                        kline["c"], kline.get("v", 0.0)])
        if len(self._ohlc) == 0:
            self._ohlc = row.reshape(1, 6)
        elif self._ohlc[-1, 0] == t:
            self._ohlc[-1] = row
        else:
            self._ohlc = np.vstack([self._ohlc, row])
            if len(self._ohlc) > CANDLE_LIMIT:
                self._ohlc = self._ohlc[1:]
        self._candle_item.set_data(self._ohlc)
        self._volume_item.set_data(self._ohlc)
        self._rescale_volume()
        self._update_price_line(float(kline["c"]))

    def _on_ticker(self, symbol, data):
        self._ticker_cache[symbol] = data

    def _flush_table(self):
        for sym, data in self._ticker_cache.items():
            self.table.update_ticker(sym, data)
        if self._active_coin in self._ticker_cache:
            self._update_coin_info_label(self._ticker_cache[self._active_coin])
        elif len(self._ohlc) > 0:
            # Fallback: derive info from candle data
            self._update_coin_info_label({
                "price": float(self._ohlc[-1, 4]),
                "open": float(self._ohlc[0, 1]),
                "high": float(self._ohlc[:, 2].max()),
                "low": float(self._ohlc[:, 3].min()),
            })

    # ── Interval buttons ────────────────────────────────────────────────────

    def _on_interval_changed(self, interval):
        for iv, btn in self._interval_btns.items():
            btn.setChecked(iv == interval)
        self._switch_chart(interval=interval)

    # ── Table interactions ──────────────────────────────────────────────────

    def _on_table_dbl_click(self, row, _col):
        if 0 <= row < len(self.table.symbols):
            sym = self.table.symbols[row]
            self._switch_chart(symbol=sym)

    def _on_table_ctx_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self.table.symbols):
            return
        sym = self.table.symbols[row]
        menu = QMenu(self)
        act = menu.addAction(f"Remove {sym}")
        if menu.exec(self.table.viewport().mapToGlobal(pos)) == act:
            self._remove_coin(sym)

    # ── Add / remove coins ──────────────────────────────────────────────────

    def _on_add_clicked(self):
        text, ok = QInputDialog.getText(
            self, "Add Coin",
            "Enter Binance symbol (e.g. PEPE, SHIB, WIF):")
        if not ok or not text.strip():
            return
        raw = text.strip().upper()
        if "/" in raw:
            raw = raw.split("/")[0]
        if raw.endswith("USDT"):
            raw = raw[:-4]
        symbol = raw
        if symbol in self.coins:
            QMessageBox.information(self, "Info", f"{symbol} is already tracked.")
            return
        self.status_label.setText(f"Validating {symbol}USDT…")
        threading.Thread(
            target=self._validate_coin, args=(symbol,), daemon=True).start()

    def _validate_coin(self, symbol):
        pair = f"{symbol}USDT"
        try:
            resp = requests.get(f"{REST_URL}/klines", params={
                "symbol": pair, "interval": "1m", "limit": 1,
            }, timeout=5)
            if resp.status_code == 200 and resp.json():
                self.signals.coin_validated.emit(symbol, True, "")
            else:
                self.signals.coin_validated.emit(
                    symbol, False, f"{pair} not found on Binance.")
        except Exception as exc:
            self.signals.coin_validated.emit(symbol, False, str(exc))

    def _on_coin_validated(self, symbol, valid, error):
        if not valid:
            QMessageBox.warning(self, "Invalid Symbol", error)
            self._update_status()
            return
        self._do_add_coin(symbol)

    def _do_add_coin(self, symbol):
        self.coins.append(symbol)
        color = COLORS[len(self.coins) % len(COLORS)]
        self.table.add_coin(symbol, color)
        self.coin_selector.addItem(symbol)
        self._ws.subscribe([f"{symbol.lower()}usdt@miniTicker"])
        self._save_coins()
        self._icon_fetcher.enqueue(symbol)
        self.status_label.setText(f"Added {symbol}")
        # Fetch ticker data immediately so the row doesn't stay empty
        threading.Thread(
            target=self._fetch_one_ticker, args=(symbol,), daemon=True).start()

    def _fetch_one_ticker(self, symbol):
        pair = f"{symbol}USDT"
        try:
            resp = requests.get(
                f"{REST_URL}/ticker/24hr", params={"symbol": pair}, timeout=5)
            if resp.status_code == 200:
                d = resp.json()
                self.signals.ticker_update.emit(symbol, {
                    "price": float(d["lastPrice"]),
                    "open": float(d["openPrice"]),
                    "high": float(d["highPrice"]),
                    "low": float(d["lowPrice"]),
                    "volume": float(d["volume"]),
                    "quote_volume": float(d["quoteVolume"]),
                })
        except Exception:
            pass

    # ── Icons ───────────────────────────────────────────────────────────────

    def _on_icon_ready(self, symbol, path):
        pixmap = QPixmap(path).scaled(
            20, 20, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        icon = QIcon(pixmap)
        if symbol in self.table.symbols:
            row = self.table.symbols.index(symbol)
            item = self.table.item(row, 0)
            if item:
                item.setIcon(icon)
        idx = self.coin_selector.findText(symbol)
        if idx >= 0:
            self.coin_selector.setItemIcon(idx, icon)

    def _remove_coin(self, symbol):
        if len(self.coins) <= 1:
            return
        self.coins.remove(symbol)
        self.table.remove_coin(symbol)
        idx = self.coin_selector.findText(symbol)
        if idx >= 0:
            self.coin_selector.removeItem(idx)
        self._ws.unsubscribe([f"{symbol.lower()}usdt@miniTicker"])
        self._ticker_cache.pop(symbol, None)
        self._save_coins()
        if self._active_coin == symbol:
            self._switch_chart(symbol=self.coins[0])

    # ── Volume overlay ──────────────────────────────────────────────────────

    def _rescale_volume(self):
        if len(self._ohlc) == 0:
            return
        vmax = float(self._ohlc[:, 5].max())
        if vmax <= 0:
            vmax = 1.0
        # Bars occupy ~20% of the chart height.
        self._vol_vb.setYRange(0.0, vmax * 5.0, padding=0)

    # ── Current price line ──────────────────────────────────────────────────

    def _update_price_line(self, price):
        self._current_price = price
        self._price_line.setPos(price)
        self._price_line.show()
        if price >= 1:
            txt = f" ${price:,.2f} "
        elif price >= 0.01:
            txt = f" ${price:.4f} "
        else:
            txt = f" ${price:.8f} "
        self._price_label.setText(txt)
        self._price_label.show()
        self._reposition_price_label()

    def _reposition_price_label(self):
        if self._current_price is None:
            return
        vr = self.chart.plotItem.vb.viewRange()
        x_min = vr[0][0]
        self._price_label.setPos(x_min, self._current_price)

    # ── Crosshair ───────────────────────────────────────────────────────────

    def _on_mouse_moved(self, pos):
        vb = self.chart.plotItem.vb
        if not vb.sceneBoundingRect().contains(pos):
            self._xhair_overlay.clear()
            return
        view_pt = vb.mapSceneToView(pos)
        vp_pt = self.chart.mapFromScene(pos)
        price = view_pt.y()
        if price >= 1:
            txt = f"${price:,.2f}"
        elif price >= 0.01:
            txt = f"${price:.4f}"
        else:
            txt = f"${price:.8f}"
        dt = datetime.fromtimestamp(view_pt.x())
        txt += f"  {dt:%H:%M}"
        self._xhair_overlay.set_position(vp_pt.x(), vp_pt.y(), txt)

    def eventFilter(self, obj, ev):
        if obj is self.chart.viewport():
            t = ev.type()
            if t == QEvent.Type.MouseMove:
                if not ev.buttons():
                    now = time.monotonic()
                    if now - self._last_hover_time < self._hover_min_interval:
                        return True  # drop — never reaches pyqtgraph's scene
                    self._last_hover_time = now
            elif t == QEvent.Type.Resize:
                self._xhair_overlay.resize(ev.size())
            elif t == QEvent.Type.Leave:
                self._xhair_overlay.clear()
        return super().eventFilter(obj, ev)

    # ── Coin info header ────────────────────────────────────────────────────

    def _update_coin_info_label(self, data=None):
        sym = self._active_coin
        iv = self._active_interval
        if data is None:
            self._coin_info.setText(
                f"<b>{sym}</b>/USDT &nbsp; {iv} &nbsp; Loading…")
            return
        price = data.get("price", 0)
        open_24h = data.get("open", 0)
        hi = data.get("high", 0)
        lo = data.get("low", 0)
        pct = ((price - open_24h) / open_24h * 100) if open_24h else 0
        arrow = "&#9650;" if pct >= 0 else "&#9660;"
        pct_color = "#a6e3a1" if pct >= 0 else "#f38ba8"
        p_str = f"${price:,.2f}" if price >= 1 else f"${price:.6f}"
        h_str = f"${hi:,.2f}" if hi >= 1 else f"${hi:.6f}"
        l_str = f"${lo:,.2f}" if lo >= 1 else f"${lo:.6f}"
        self._coin_info.setText(
            f"<b>{sym}</b>/USDT &nbsp; {iv} &nbsp;&nbsp; "
            f"<b>{p_str}</b> &nbsp; "
            f"<span style='color:{pct_color}'>{arrow} {pct:+.2f}%</span>"
            f" &nbsp; H {h_str} &nbsp; L {l_str}")

    # ── Status bar ──────────────────────────────────────────────────────────

    def _update_status(self):
        now = datetime.now().strftime("%H:%M:%S")
        n = len(self.coins)
        sym = self._active_coin
        iv = self._active_interval
        pts = len(self._ohlc)
        self.status_label.setText(
            f"  {now}  |  {n} coins  |  {sym}/USDT {iv}  |  "
            f"{pts} candles  |  Binance")

    # ── Persistence ─────────────────────────────────────────────────────────

    @staticmethod
    def _load_coins():
        try:
            coins = json.loads(CONFIG_FILE.read_text())
            if isinstance(coins, list) and coins:
                return coins
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            pass
        return list(DEFAULT_SYMBOLS)

    def _save_coins(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self.coins, indent=2))


# ── Entry Point ─────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Global dark palette
    pal = app.palette()
    pal.setColor(pal.ColorRole.Window, QColor("#1e1e2e"))
    pal.setColor(pal.ColorRole.WindowText, QColor("#cdd6f4"))
    pal.setColor(pal.ColorRole.Base, QColor("#1e1e2e"))
    pal.setColor(pal.ColorRole.AlternateBase, QColor("#252536"))
    pal.setColor(pal.ColorRole.Text, QColor("#cdd6f4"))
    pal.setColor(pal.ColorRole.Button, QColor("#313244"))
    pal.setColor(pal.ColorRole.ButtonText, QColor("#cdd6f4"))
    pal.setColor(pal.ColorRole.Highlight, QColor("#89b4fa"))
    pal.setColor(pal.ColorRole.HighlightedText, QColor("#1e1e2e"))
    app.setPalette(pal)

    win = Dashboard()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
