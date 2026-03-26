from functools import lru_cache
from mm_toolbox.rounding import Rounder, RounderConfig


@lru_cache(maxsize=128)
def _get_rounder(tick_size: float, lot_size: float) -> Rounder:
    """Cache Rounder instances per tick/lot size pair (Cython-accelerated)."""
    config = RounderConfig.default(tick_size=tick_size, lot_size=lot_size)
    return Rounder(config)


def round_step(num: float, step: float) -> float:
    """
    Rounds a float to a given step size using mm_toolbox Cython Rounder.
    Compatible drop-in for the old Decimal-based round_step.
    """
    rounder = _get_rounder(step, step)
    return rounder.bid(num)
