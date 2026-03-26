import asyncio
import numpy as np
import os
import yaml
from collections import deque
from numpy_ringbuffer import RingBuffer
from typing import Dict
from numpy.typing import NDArray
from mm_toolbox.orderbook import Orderbook, OrderbookLevel
from src.exchanges.bybit.websockets.handlers.orderbook import OrderBookBybit
from src.exchanges.binance.websockets.handlers.orderbook import OrderBookBinance


class SharedState:
    """
    Centralizes shared data and configurations for the trading application,
    including market data and trading parameters, and provides utility methods
    for market metric calculations.
    """

    PARAM_PATH = os.path.dirname(os.path.realpath(__file__)) + "/../parameters.yaml"

    def __init__(self) -> None:
        self.api_key = os.getenv("API_KEY")
        self.api_secret = os.getenv("API_SECRET")
        if not self.api_key or not self.api_secret:
            raise ValueError("Missing API key and/or secret!")
        if not self.PARAM_PATH:
            raise ValueError("Missing config and/or param directories!")
        self._load_initial_settings_()

        # Initialize market data attributes for Binance and Bybit
        self.binance_ws_connected = False
        self.binance_trades = RingBuffer(capacity=1000, dtype=(float, 4))
        self.binance_bba = np.ones((2, 2), dtype=np.float64)
        self.binance_book = OrderBookBinance()
        self.binance_last_price = 0

        self.bybit_ws_connected = False
        self.bybit_klines = RingBuffer(capacity=500, dtype=(float, 7))
        self.bybit_trades = RingBuffer(capacity=1000, dtype=(float, 4))
        self.bybit_bba = np.ones((2, 2), dtype=np.float64)
        self.bybit_book = OrderBookBybit()
        self.bybit_mark_price = 0

        # mm_toolbox Orderbook (initialized after tick/lot sizes are known)
        self._bybit_ob: Orderbook | None = None

        # Other shared attributes
        self.current_orders = {}
        self.execution_feed = deque(maxlen=100)
        self.volatility_value = 0
        self.inventory_delta = 0

    def init_mm_orderbook(self) -> None:
        """Initialize mm_toolbox Orderbook once tick/lot sizes are available."""
        self._bybit_ob = Orderbook(
            tick_size=self.bybit_tick_size,
            lot_size=self.bybit_lot_size,
            size=500,
        )

    def _load_settings_(self, settings: Dict, reload: bool=False) -> None:
        """Updates trading parameters and settings from a dictionary of settings."""
        if not reload:
            self.primary_data_feed = str(settings["primary_data_feed"]).upper()
            self.binance_symbol = str(settings["binance_symbol"])
            self.bybit_symbol = str(settings["bybit_symbol"])
            self.account_size = float(settings["account_size"])
            self.bb_length = int(settings["bollinger_band_length"])
            self.bb_std = int(settings["bollinger_band_std"])
            self.price_offset = float(settings["price_offset"])
            self.size_offset = float(settings["size_offset"])
            self.volatility_offset = float(settings["volatility_offset"])
            self.base_spread = float(settings["base_spread"])
            self.min_order_size = float(settings["min_order_size"])
            self.max_order_size = float(settings["max_order_size"])
            self.inventory_extreme = float(settings["inventory_extreme"])

        # Avellaneda-Stoikov parameters (hot-reloadable)
        self.as_gamma = float(settings.get("as_gamma", 0.1))
        self.as_k = float(settings.get("as_k", 1.5))
        self.as_T = float(settings.get("as_T", 1.0))
        self.as_dt = float(settings.get("as_dt", 1.0))
        self.as_vol_window = int(settings.get("as_vol_window", 100))

    def _load_initial_settings_(self) -> None:
        """Loads initial trading settings from the parameters YAML file."""
        with open(self.PARAM_PATH, "r") as f:
            settings = yaml.safe_load(f)
        self._load_settings_(settings)

    async def refresh_parameters(self) -> None:
        """Periodically refreshes trading parameters from the parameters file."""
        while True:
            await asyncio.sleep(10)
            with open(self.PARAM_PATH, "r") as f:
                settings = yaml.safe_load(f)
            self._load_settings_(settings, reload=True)

    @property
    def binance_mid(self) -> float:
        return self.calculate_mid(self.binance_bba)

    @property
    def binance_wmid(self) -> float:
        return self.calculate_wmid(self.binance_bba)

    @property
    def binance_vamp(self) -> float:
        return self.calculate_vamp(self.binance_book)

    @property
    def bybit_mid(self) -> float:
        # Use mm_toolbox Orderbook if available, else fallback to BBA
        if self._bybit_ob is not None and self._bybit_ob._is_populated:
            return self._bybit_ob.get_mid_price()
        return self.calculate_mid(self.bybit_bba)

    @property
    def bybit_wmid(self) -> float:
        if self._bybit_ob is not None and self._bybit_ob._is_populated:
            return self._bybit_ob.get_wmid_price()
        return self.calculate_wmid(self.bybit_bba)

    @property
    def bybit_vamp(self) -> float:
        if self._bybit_ob is not None and self._bybit_ob._is_populated:
            return self._bybit_ob.get_volume_weighted_mid_price(self.account_size)
        return self.calculate_vamp(self.bybit_book)

    @staticmethod
    def calculate_mid(bba: NDArray) -> float:
        best_bid, best_ask = bba[0][0], bba[1][0]
        return (best_ask + best_bid) / 2

    @staticmethod
    def calculate_wmid(bba: NDArray) -> float:
        imb = bba[0][1] / (bba[0][1] + bba[1][1])
        return bba[1][0] * imb + bba[0][0] * (1 - imb)

    @staticmethod
    def calculate_vamp(book, depth=10) -> float:
        bids_qty_sum = sum(bid[1] for bid in book.bids[:depth])
        asks_qty_sum = sum(ask[1] for ask in book.asks[:depth])
        bid_fair = sum(bid[0] * (bid[1] / bids_qty_sum) for bid in book.bids[:depth])
        ask_fair = sum(ask[0] * (ask[1] / asks_qty_sum) for ask in book.asks[:depth])
        return (bid_fair + ask_fair) / 2
