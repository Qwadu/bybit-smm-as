import numpy as np
from numpy.typing import NDArray
from typing import List, Tuple
from src.utils.rounding import round_step
from src.utils.jit_funcs import nblinspace, nbgeomspace, nbround, nbabs, nbclip
from src.strategy.features.generate import Features
from src.strategy.avellaneda_stoikov import AvellanedaStoikov, ASParams
from src.sharedstate import SharedState


class MarketMaker:
    """
    Market making bot with Avellaneda-Stoikov optimal quoting engine.

    Uses A-S reservation price and optimal spread for quote placement.
    Retains original skew/inventory logic for size and side weighting.
    """

    max_orders = 8

    def __init__(self, ss: SharedState) -> None:
        self.ss = ss
        self.features = Features(self.ss)
        self.tick_size = self.ss.bybit_tick_size
        self.lot_size = self.ss.bybit_lot_size
        # A-S engine - params can be tuned via parameters.yaml
        as_params = ASParams(
            gamma=getattr(self.ss, 'as_gamma', 0.1),
            k=getattr(self.ss, 'as_k', 1.5),
            T=getattr(self.ss, 'as_T', 1.0),
            dt=getattr(self.ss, 'as_dt', 1.0),
            vol_window=getattr(self.ss, 'as_vol_window', 100),
        )
        self.as_engine = AvellanedaStoikov(as_params)
        self.spread = self._adjusted_spread_()

    def _skew_(self) -> Tuple[float, float]:
        skew = self.features.generate_skew()
        skew = nbround(skew, 2)
        bid_skew = nbclip(skew, 0, 1)
        ask_skew = nbclip(skew, -1, 0)
        bid_skew += self.ss.inventory_delta if self.ss.inventory_delta < 0 else 0
        ask_skew -= self.ss.inventory_delta if self.ss.inventory_delta > 0 else 0
        bid_skew = bid_skew if self.ss.inventory_delta > -self.ss.inventory_extreme else 1
        ask_skew = ask_skew if self.ss.inventory_delta < self.ss.inventory_extreme else 1
        if (bid_skew == 1 or ask_skew == 1) and (self.ss.inventory_delta == 0):
            return 0, 0
        return nbabs(bid_skew), nbabs(ask_skew)

    def _adjusted_spread_(self) -> float:
        multiplier = (self.ss.volatility_value * 100) / self.ss.bybit_mid
        return self.ss.base_spread * nbclip(multiplier, 1, 10)

    def _as_quotes_(self) -> Tuple[float, float]:
        """
        Compute optimal bid/ask via Avellaneda-Stoikov engine.
        Returns (bid_price, ask_price).
        """
        mid = float(self.ss.bybit_mid)
        inventory = float(self.ss.inventory_delta)
        bid, ask = self.as_engine.quotes(
            mid=mid,
            inventory=inventory,
            tick_size=self.tick_size,
        )
        return bid, ask

    def _prices_(self, bid_skew: float, ask_skew: float) -> Tuple[NDArray, NDArray]:
        # Get A-S reservation center
        as_bid, as_ask = self._as_quotes_()
        spread = max(as_ask - as_bid, self.spread)

        # Inventory is too short, dont quote asks
        if bid_skew >= 1:
            bid_lower = as_bid - (spread * self.max_orders)
            bid_prices = nblinspace(as_bid, bid_lower, self.max_orders)
            return bid_prices, None

        # Inventory is too long, dont quote bids
        elif ask_skew >= 1:
            ask_upper = as_ask + (spread * self.max_orders)
            ask_prices = nblinspace(as_ask, ask_upper, self.max_orders)
            return None, ask_prices

        # Normal: use A-S midpoint adjusted by skew
        elif bid_skew >= ask_skew:
            best_bid = as_ask - spread * 0.33
            best_ask = best_bid + spread * 0.67
        else:
            best_ask = as_bid + spread * 0.33
            best_bid = best_ask - spread * 0.67

        base_range = self.ss.volatility_value / 2
        bid_lower = best_bid - (base_range * (1 - bid_skew))
        ask_upper = best_ask + (base_range * (1 - ask_skew))
        bid_prices = nbgeomspace(best_bid, bid_lower, self.max_orders / 2) + self.ss.price_offset
        ask_prices = nbgeomspace(best_ask, ask_upper, self.max_orders / 2) + self.ss.price_offset
        return bid_prices, ask_prices

    def _sizes_(self, bid_skew: float, ask_skew: float) -> Tuple[NDArray, NDArray]:
        if bid_skew >= 1:
            bid_sizes = np.full(
                shape=self.max_orders,
                fill_value=np.median([self.ss.min_order_size, self.ss.max_order_size / 2])
            )
            return bid_sizes, None
        elif ask_skew >= 1:
            ask_sizes = np.full(
                shape=self.max_orders,
                fill_value=np.median([self.ss.min_order_size, self.ss.max_order_size / 2])
            )
            return None, ask_sizes
        bid_min = self.ss.min_order_size * (1 + bid_skew**0.5)
        bid_upper = self.ss.max_order_size * (1 - bid_skew)
        ask_min = self.ss.min_order_size * (1 + ask_skew**0.5)
        ask_upper = self.ss.max_order_size * (1 - ask_skew)
        bid_sizes = nbgeomspace(
            start=bid_min if bid_skew >= ask_skew else self.ss.min_order_size,
            end=bid_upper,
            n=self.max_orders / 2
        ) + self.ss.size_offset
        ask_sizes = nbgeomspace(
            start=ask_min if ask_skew >= bid_skew else self.ss.min_order_size,
            end=ask_upper,
            n=self.max_orders / 2
        ) + self.ss.size_offset
        return bid_sizes, ask_sizes

    def generate_quotes(self, debug=False) -> List[Tuple[str, float, float]]:
        bid_skew, ask_skew = self._skew_()
        bid_prices, ask_prices = self._prices_(bid_skew, ask_skew)
        bid_sizes, ask_sizes = self._sizes_(bid_skew, ask_skew)
        bids, asks = [], []
        if isinstance(bid_prices, np.ndarray):
            bids = [
                ["Buy", round_step(price, self.tick_size), round_step(size, self.lot_size)]
                for price, size in zip(bid_prices, bid_sizes)
            ]
        if isinstance(ask_prices, np.ndarray):
            asks = [
                ["Sell", round_step(price, self.tick_size), round_step(size, self.lot_size)]
                for price, size in zip(ask_prices, ask_sizes)
            ]
        as_bid, as_ask = self._as_quotes_()
        effective_spread = as_ask - as_bid
        if debug:
            print("-----------------------------")
            print(f"A-S Bid: {as_bid} | A-S Ask: {as_ask} | Spread: {effective_spread:.6f}")
            print(f"Skews: {bid_skew} | {ask_skew}")
            print(f"Inventory: {self.ss.inventory_delta}")
            print(f"Bids: {bids}")
            print(f"Asks: {asks}")
        return bids + asks, effective_spread
