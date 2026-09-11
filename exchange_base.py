from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class BaseExchange(ABC):
    """
    Abstract base class for prediction market exchanges.
    Allows easy extension to Polymarket, SX Bet, Betfair, etc.
    """

    @abstractmethod
    async def initialize(self):
        """Pre-warm connections and initialize authentication."""
        pass

    @abstractmethod
    async def close(self):
        """Close connection pools."""
        pass

    @abstractmethod
    async def search_game_events(self, query: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        """Search available sports game events."""
        pass

    @abstractmethod
    async def get_market_quote(self, ticker: str) -> Dict[str, Any]:
        """Fetch latest bid/ask and price for a market ticker."""
        pass

    @abstractmethod
    async def place_order(
        self,
        ticker: str,
        side: str,  # 'bid' (buy Yes) or 'ask' (sell Yes / buy No)
        price: float,
        count: int,
        client_order_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Submit an order to the exchange."""
        pass
