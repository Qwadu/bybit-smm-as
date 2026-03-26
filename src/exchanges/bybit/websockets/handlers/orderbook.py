import numpy as np
from typing import Dict, List
from src.exchanges.common.localorderbook import BaseOrderBook
from mm_toolbox.orderbook import Orderbook, OrderbookLevel


class OrderBookBybit(BaseOrderBook):
    """
    Order book class for Bybit, extending the BaseOrderBook for handling Bybit-specific order book data.
    """

    def process_snapshot(self, asks: List[List[float]], bids: List[List[float]]) -> None:
        self.asks = np.array(asks, dtype=float)
        self.bids = np.array(bids, dtype=float)
        self.sort_book()

    def process(self, recv: Dict) -> None:
        asks = np.array(recv["data"]["a"], dtype=float)
        bids = np.array(recv["data"]["b"], dtype=float)

        if recv["type"] == "snapshot":
            self.process_snapshot(asks, bids)

        elif recv["type"] == "delta":
            self.asks = self.update_book(self.asks, asks)
            self.bids = self.update_book(self.bids, bids)
            self.sort_book()


def _to_ob_levels(data: List) -> List[OrderbookLevel]:
    """Convert raw [[price, qty], ...] list to mm_toolbox OrderbookLevel list."""
    return [OrderbookLevel(price=float(item[0]), size=float(item[1])) for item in data]


class BybitOrderBookMMHandler:
    """
    Feeds the mm_toolbox Orderbook with Bybit snapshot/delta WebSocket data.
    Requires ss._bybit_ob to be initialized (call ss.init_mm_orderbook() first).
    """

    def __init__(self, ss) -> None:
        self.ss = ss

    def process(self, recv: Dict) -> None:
        ob = self.ss._bybit_ob
        if ob is None:
            return

        raw_asks = recv["data"]["a"]
        raw_bids = recv["data"]["b"]
        ask_levels = _to_ob_levels(raw_asks)
        bid_levels = _to_ob_levels(raw_bids)

        if recv["type"] == "snapshot":
            # mm_toolbox requires >= size levels; skip if insufficient data
            if len(ask_levels) >= ob._size and len(bid_levels) >= ob._size:
                ob.consume_snapshot(asks=ask_levels, bids=bid_levels)
        elif recv["type"] == "delta":
            if ob._is_populated:
                ob.consume_deltas(asks=ask_levels, bids=bid_levels)


class BybitBBAHandler:
    """
    Handler for processing Best Bid and Ask (BBA) updates from Bybit.
    Also feeds mm_toolbox Orderbook BBO if available.
    """

    def __init__(self, ss) -> None:
        self.ss = ss

    def process(self, recv: Dict) -> None:
        best_bid = recv["data"]["b"]
        best_ask = recv["data"]["a"]

        bid_price, bid_qty = 0.0, 0.0
        ask_price, ask_qty = 0.0, 0.0

        if best_bid:
            price, qty = list(map(float, best_bid[0]))
            if qty > 0:
                self.ss.bybit_bba[0, 0] = price
                self.ss.bybit_bba[0, 1] = qty
                bid_price, bid_qty = price, qty

        if best_ask:
            price, qty = list(map(float, best_ask[0]))
            if qty > 0:
                self.ss.bybit_bba[1, 0] = price
                self.ss.bybit_bba[1, 1] = qty
                ask_price, ask_qty = price, qty

        # Feed mm_toolbox Orderbook BBO if initialized
        ob = self.ss._bybit_ob
        if ob is not None and bid_price > 0 and ask_price > 0:
            bid_level = OrderbookLevel(price=bid_price, size=bid_qty)
            ask_level = OrderbookLevel(price=ask_price, size=ask_qty)
            ob.consume_bbo(ask=ask_level, bid=bid_level)
