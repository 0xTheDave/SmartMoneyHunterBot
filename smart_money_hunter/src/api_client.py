import aiohttp
import asyncio
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from database import get_db
from config import config

logger = logging.getLogger(__name__)

class RateLimitedAPIClient:
    def __init__(self):
        self.helius_key = config.HELIUS_API_KEY
        self.birdeye_key = config.BIRDEYE_API_KEY
        self.session = None
        self.db = get_db()
        self.api_calls_today = {'helius': 0, 'birdeye': 0}
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def get_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self.session
    
    def _can_make_api_call(self, service: str) -> bool:
        """Simple rate limiting without database tracking"""
        limit = config.HELIUS_DAILY_LIMIT if service == 'helius' else config.BIRDEYE_DAILY_LIMIT
        return self.api_calls_today[service] < limit
    
    def _track_api_usage(self, service: str):
        """Simple in-memory tracking"""
        self.api_calls_today[service] += 1
        return self.api_calls_today[service]
    
    async def get_token_price_cached(self, token_mint: str) -> Optional[float]:
        """Get token price - simplified without cache"""
        if not self._can_make_api_call('birdeye'):
            logger.warning("Birdeye API limit reached")
            return None
        
        price = await self._fetch_token_price(token_mint)
        if price:
            self._track_api_usage('birdeye')
        
        return price
    
    async def _fetch_token_price(self, token_mint: str) -> Optional[float]:
        """Fetch token price from Birdeye API"""
        if not self.birdeye_key:
            return None
            
        url = "https://public-api.birdeye.so/defi/price"
        headers = {"X-API-KEY": self.birdeye_key}
        params = {"address": token_mint}
        
        try:
            session = await self.get_session()
            async with session.get(url, headers=headers, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('data', {}).get('value', 0)
        except Exception as e:
            logger.error(f"Error fetching token price: {e}")
        return None
    
    async def get_wallet_transactions(self, wallet_address: str, limit: int = 50) -> List[Dict]:
        """Get wallet transactions from Helius with rate limiting"""
        if not self._can_make_api_call('helius'):
            logger.warning("Helius API limit reached")
            return []
        
        if not self.helius_key:
            logger.warning("Helius API key not set")
            return []
            
        url = f"https://api.helius.xyz/v0/addresses/{wallet_address}/transactions"
        params = {
            "api-key": self.helius_key,
            "limit": limit,
            "type": "SWAP"
        }
        
        try:
            session = await self.get_session()
            async with session.get(url, params=params, timeout=15) as response:
                if response.status == 200:
                    self._track_api_usage('helius')
                    return await response.json()
                else:
                    logger.error(f"Helius API error: {response.status}")
        except Exception as e:
            logger.error(f"Error getting wallet transactions: {e}")
        
        return []
    
    async def get_top_tokens(self, limit: int = 20) -> List[Dict]:
        """Get top performing tokens"""
        if not self._can_make_api_call('birdeye'):
            logger.warning("Birdeye API limit reached for top tokens")
            return []
        
        if not self.birdeye_key:
            return []
            
        url = "https://public-api.birdeye.so/defi/tokenlist"
        headers = {"X-API-KEY": self.birdeye_key}
        params = {
            "sort_by": "priceChange24hPercent",
            "sort_type": "desc", 
            "limit": limit,
            "offset": 0
        }
        
        try:
            session = await self.get_session()
            async with session.get(url, headers=headers, params=params, timeout=15) as response:
                if response.status == 200:
                    self._track_api_usage('birdeye')
                    data = await response.json()
                    return data.get('data', [])
        except Exception as e:
            logger.error(f"Error getting top tokens: {e}")
        
        return []
