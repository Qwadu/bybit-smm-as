import orjson
import websockets
from typing import Coroutine, Union

from src.utils.misc import datetime_now as dt_now
from src.exchanges.bybit.get.public import BybitPublicClient
from src.exchanges.bybit.endpoints import WsStreamLinks
from src.exchanges.bybit.websockets.handlers.kline import BybitKlineHandler
from src.exchanges.bybit.websockets.handlers.orderbook import BybitBBAHandler, BybitOrderBookMMHandler
from src.exchanges.bybit.websockets.handlers.ticker import BybitTickerHandler
from src.exchanges.bybit.websockets.handlers.trades import BybitTradesHandler
from src.exchanges.bybit.websockets.public import BybitPublicWs
from src.sharedstate import SharedState


class BybitMarketData:
    """
    Manages market data streams from Bybit, including order book, BBA, trades, ticker, and kline.
    """

    _topics_ = ["Orderbook", "BBA", "Trades", "Ticker", "Kline"]

    def __init__(self, ss: SharedState) -> None:
        self.ss = ss
        self.public_ws = BybitPublicWs(self.ss)
        self.ws_req, self.ws_topics = self.public_ws.multi_stream_request(
            topics=self._topics_,
            depth=500,
            interval=1
        )
        # mm_ob_handler initialized after _get_precision_ sets tick/lot sizes
        self._mm_ob_handler = None
        self.topic_handler_map = {
            self.ws_topics[0]: self._dispatch_orderbook,
            self.ws_topics[1]: BybitBBAHandler(self.ss).process,
            self.ws_topics[2]: BybitTradesHandler(self.ss).process,
            self.ws_topics[3]: BybitTickerHandler(self.ss).process,
            self.ws_topics[4]: BybitKlineHandler(self.ss).process,
        }

    def _dispatch_orderbook(self, recv: dict) -> None:
        """Dispatch orderbook updates to both legacy and mm_toolbox handlers."""
        self.ss.bybit_book.process(recv)
        if self._mm_ob_handler is not None:
            self._mm_ob_handler.process(recv)

    async def _initialize_(self) -> None:
        klines = await BybitPublicClient(self.ss).klines(1, 500)
        trades = await BybitPublicClient(self.ss).trades(1000)
        BybitKlineHandler(self.ss).initialize(klines["result"]["list"])
        BybitTradesHandler(self.ss).initialize(trades["result"]["list"])

    async def _get_precision_(self) -> None:
        info = (await BybitPublicClient(self.ss).instrument_info())["result"]["list"][0]
        self.ss.bybit_tick_size = float(info["priceFilter"]["tickSize"])
        self.ss.bybit_lot_size = float(info["lotSizeFilter"]["qtyStep"])
        # Now initialize mm_toolbox Orderbook with correct precision
        self.ss.init_mm_orderbook()
        self._mm_ob_handler = BybitOrderBookMMHandler(self.ss)

    async def _stream_(self) -> Union[Coroutine, None]:
        await self._initialize_()
        await self._get_precision_()

        async for websocket in websockets.connect(WsStreamLinks.FUTURES_PUBLIC_STREAM):
            print(f"{dt_now()}: Connected to {self.ws_topics} bybit feeds...")
            self.ss.bybit_ws_connected = True

            try:
                await websocket.send(self.ws_req)

                while True:
                    recv = orjson.loads(await websocket.recv())

                    if "success" in recv:
                        continue

                    handler = self.topic_handler_map.get(recv["topic"])

                    if handler:
                        handler(recv)

            except websockets.ConnectionClosed:
                continue

            except Exception as e:
                print(f"{dt_now()}: Error with bybit public feed: {e}")
                raise e

    async def start_feed(self) -> Coroutine:
        await self._stream_()
