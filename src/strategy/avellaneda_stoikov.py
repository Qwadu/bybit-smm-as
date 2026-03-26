import numpy as np
from dataclasses import dataclass
from typing import Tuple


@dataclass
class ASParams:
    """Avellaneda-Stoikov model parameters."""
    gamma: float = 0.1      # risk aversion coefficient
    k: float = 1.5          # order book liquidity parameter
    sigma: float = 0.02     # volatility (updated dynamically)
    T: float = 1.0          # time horizon (normalized)
    dt: float = 1.0         # time step
    vol_window: int = 100   # rolling window for vol estimation


class AvellanedaStoikov:
    """
    Avellaneda-Stoikov optimal market-making quoting engine.

    Computes reservation price and optimal bid/ask spread based on:
    - Current mid price
    - Inventory position
    - Realized volatility
    - Risk aversion gamma
    - Liquidity parameter k

    Reference: Avellaneda & Stoikov (2008)
    """

    def __init__(self, params: ASParams):
        self.params = params
        self._price_history = []

    def update_volatility(self, mid_price: float) -> None:
        """Update rolling volatility estimate from mid price history."""
        self._price_history.append(mid_price)
        if len(self._price_history) > self.params.vol_window:
            self._price_history.pop(0)
        if len(self._price_history) >= 2:
            returns = np.diff(np.log(self._price_history))
            self.params.sigma = float(np.std(returns)) if len(returns) > 0 else self.params.sigma

    def reservation_price(self, mid: float, inventory: float, t_remaining: float = None) -> float:
        """
        Compute reservation (indifference) price.

        r = s - q * gamma * sigma^2 * (T - t)

        Args:
            mid: current mid price
            inventory: current signed inventory (positive = long)
            t_remaining: time remaining in horizon (defaults to T)
        Returns:
            reservation price
        """
        T_minus_t = t_remaining if t_remaining is not None else self.params.T
        return mid - inventory * self.params.gamma * (self.params.sigma ** 2) * T_minus_t

    def optimal_spread(self, t_remaining: float = None) -> float:
        """
        Compute optimal total bid-ask spread.

        spread = gamma * sigma^2 * (T - t) + (2/gamma) * ln(1 + gamma/k)

        Args:
            t_remaining: time remaining in horizon
        Returns:
            total optimal spread
        """
        T_minus_t = t_remaining if t_remaining is not None else self.params.T
        g = self.params.gamma
        k = self.params.k
        sigma = self.params.sigma
        spread = g * (sigma ** 2) * T_minus_t + (2.0 / g) * np.log(1.0 + g / k)
        return spread

    def quotes(
        self,
        mid: float,
        inventory: float,
        t_remaining: float = None,
        tick_size: float = 0.01,
    ) -> Tuple[float, float]:
        """
        Compute optimal bid and ask prices.

        Args:
            mid: current mid price
            inventory: signed inventory
            t_remaining: time remaining
            tick_size: minimum price increment for rounding
        Returns:
            (bid_price, ask_price)
        """
        self.update_volatility(mid)
        r = self.reservation_price(mid, inventory, t_remaining)
        half_spread = self.optimal_spread(t_remaining) / 2.0

        bid = r - half_spread
        ask = r + half_spread

        # Snap to tick grid
        if tick_size > 0:
            bid = round(round(bid / tick_size) * tick_size, 10)
            ask = round(round(ask / tick_size) * tick_size, 10)

        return bid, ask
