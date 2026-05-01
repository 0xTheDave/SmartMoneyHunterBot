# discovery.py
import asyncio
import logging
from typing import List, Set, Dict, Optional
from datetime import datetime, timedelta
import aiohttp
from api_client import RateLimitedAPIClient
from database import get_db, SmartWallet
from config import config

logger = logging.getLogger(__name__)

class WalletDiscovery:
    def __init__(self):
        self.api = RateLimitedAPIClient()
        self.db = get_db()
        self.known_bots = set()  # MEV bots, wash traders
        self.insider_patterns = {}
        
    async def discover_smart_wallets(self) -> List[str]:
        logger.info("Starting wallet discovery...")
        
        # TESTOWE PORTFELE - używamy ich do rozwoju
        test_wallets = [
            'D4U7BDNUVRsZsJnmCjUiwogjdckSNr43skivYhNCXbnm',
            '9bezpBBkNhg1GNPPSSwAgu6PonJ8tYcCcerYfd91xhY4',
            '5hyYQixyQiqEUnnMsGgE3RnengWDSJDmMosUyRiSrKQF',
            '3LRumB3yWo8aJ3b1m6JZQTtVyPsduRZXHT6Z7T49f2bz',
        ]
        
        logger.info(f"Using {len(test_wallets)} test wallets")
        return test_wallets  # ZWRACAMY TESTOWE PORTFELE

    async def _discover_early_buyers(self) -> Set[str]:
        """Find wallets that bought tokens before major price increases"""
        early_buyers = set()
        
        try:
            # Get tokens that gained >200% in last 7 days
            async with self.api as api:
                top_gainers = await api.get_top_tokens(50)
                
                for token in top_gainers:
                    if not token.get('address') or token.get('priceChange24hPercent', 0) < 200:
                        continue
                    
                    # Get transaction history for this token
                    token_transactions = await self._get_token_transactions(token['address'])
                    
                    # Find wallets that bought 24-72h before the pump
                    pump_time = self._detect_pump_start(token_transactions)
                    if pump_time:
                        early_wallets = self._find_pre_pump_buyers(token_transactions, pump_time)
                        early_buyers.update(early_wallets)
                    
                    await asyncio.sleep(2)  # Rate limiting
                    
        except Exception as e:
            logger.error(f"Error discovering early buyers: {e}")
        
        return early_buyers
    
    async def _discover_consistent_traders(self) -> Set[str]:
        """Find wallets with consistent profitable trading patterns"""
        consistent_traders = set()
        
        try:
            # Get high volume DEX transactions from last 30 days
            recent_swaps = await self._get_recent_dex_swaps(limit=10000)
            
            # Group by wallet and analyze performance
            wallet_performance = {}
            
            for swap in recent_swaps:
                wallet = swap.get('wallet_address')
                if not wallet:
                    continue
                    
                if wallet not in wallet_performance:
                    wallet_performance[wallet] = {
                        'trades': [],
                        'total_volume': 0,
                        'unique_tokens': set()
                    }
                
                wallet_performance[wallet]['trades'].append(swap)
                wallet_performance[wallet]['total_volume'] += swap.get('sol_amount', 0)
                wallet_performance[wallet]['unique_tokens'].add(swap.get('token_mint'))
            
            # Filter for consistent performers
            for wallet, data in wallet_performance.items():
                if (len(data['trades']) >= 20 and 
                    data['total_volume'] >= 100 and
                    len(data['unique_tokens']) >= 10):
                    
                    win_rate = await self._calculate_quick_win_rate(data['trades'])
                    if win_rate >= 65:
                        consistent_traders.add(wallet)
                        
        except Exception as e:
            logger.error(f"Error discovering consistent traders: {e}")
        
        return consistent_traders
    
    async def _discover_influencer_wallets(self) -> Set[str]:
        """Find wallets that are frequently copied by others"""
        influencer_wallets = set()
        
        try:
            # Analyze transaction patterns to find leader-follower relationships
            recent_transactions = await self._get_recent_dex_swaps(limit=5000)
            
            # Group transactions by token and time windows
            token_timeline = {}
            for tx in recent_transactions:
                token = tx.get('token_mint')
                timestamp = tx.get('timestamp')
                
                if token not in token_timeline:
                    token_timeline[token] = []
                
                token_timeline[token].append({
                    'wallet': tx.get('wallet_address'),
                    'timestamp': timestamp,
                    'action': tx.get('action'),
                    'volume': tx.get('sol_amount', 0)
                })
            
            # Find patterns where one wallet leads and others follow
            for token, transactions in token_timeline.items():
                if len(transactions) < 5:
                    continue
                
                # Sort by timestamp
                transactions.sort(key=lambda x: x['timestamp'])
                
                # Find potential leaders (first to buy with significant volume)
                leaders = self._identify_leaders(transactions)
                influencer_wallets.update(leaders)
                
        except Exception as e:
            logger.error(f"Error discovering influencer wallets: {e}")
        
        return influencer_wallets
    
    async def _filter_suspicious_wallets(self, candidates: Set[str]) -> Set[str]:
        """Filter out MEV bots, wash traders, and insider wallets"""
        filtered = set()
        
        for wallet in candidates:
            try:
                if await self._is_legitimate_trader(wallet):
                    filtered.add(wallet)
                else:
                    logger.info(f"Filtered out suspicious wallet: {wallet[:8]}...")
                    
                await asyncio.sleep(0.5)  # Rate limiting
                
            except Exception as e:
                logger.error(f"Error filtering wallet {wallet}: {e}")
        
        return filtered
    
    async def _is_legitimate_trader(self, wallet_address: str) -> bool:
        """Check if wallet shows legitimate trading patterns"""
        try:
            async with self.api as api:
                transactions = await api.get_wallet_transactions(wallet_address, 100)
                
                if not transactions:
                    return False
                
                # Check for suspicious patterns
                if self._has_mev_bot_pattern(transactions):
                    return False
                    
                if self._has_wash_trading_pattern(transactions):
                    return False
                    
                if self._has_insider_pattern(transactions):
                    return False
                
                # Check for legitimate trading characteristics
                if not self._has_diverse_trading_pattern(transactions):
                    return False
                
                return True
                
        except Exception as e:
            logger.error(f"Error validating wallet legitimacy: {e}")
            return False
    
    def _has_mev_bot_pattern(self, transactions: List[Dict]) -> bool:
        """Detect MEV bot characteristics"""
        if len(transactions) < 10:
            return False
        
        # Check for extremely high frequency trading
        time_diffs = []
        for i in range(1, len(transactions)):
            diff = abs(transactions[i]['timestamp'] - transactions[i-1]['timestamp'])
            time_diffs.append(diff)
        
        avg_time_diff = sum(time_diffs) / len(time_diffs)
        
        # MEV bots often trade within seconds
        if avg_time_diff < 60:  # Less than 1 minute average
            return True
        
        # Check for sandwich attack patterns
        sandwich_count = 0
        for i in range(len(transactions) - 2):
            tx1, tx2, tx3 = transactions[i:i+3]
            
            # Pattern: BUY -> (other trader) -> SELL
            if (tx1.get('action') == 'BUY' and 
                tx3.get('action') == 'SELL' and
                tx1.get('token_mint') == tx3.get('token_mint') and
                abs(tx3['timestamp'] - tx1['timestamp']) < 300):  # Within 5 minutes
                sandwich_count += 1
        
        return sandwich_count > len(transactions) * 0.3
    
    def _has_wash_trading_pattern(self, transactions: List[Dict]) -> bool:
        """Detect wash trading patterns"""
        # Look for rapid buy/sell cycles of same token
        token_cycles = {}
        
        for tx in transactions:
            token = tx.get('token_mint')
            if not token:
                continue
                
            if token not in token_cycles:
                token_cycles[token] = []
            
            token_cycles[token].append(tx)
        
        # Check each token for suspicious patterns
        for token, token_txs in token_cycles.items():
            if len(token_txs) < 4:
                continue
            
            # Sort by timestamp
            token_txs.sort(key=lambda x: x['timestamp'])
            
            # Look for alternating BUY/SELL pattern
            pattern_score = 0
            for i in range(len(token_txs) - 1):
                if (token_txs[i]['action'] != token_txs[i+1]['action'] and
                    abs(token_txs[i]['sol_amount'] - token_txs[i+1]['sol_amount']) < 0.1):
                    pattern_score += 1
            
            if pattern_score > len(token_txs) * 0.6:
                return True
        
        return False
    
    def _has_insider_pattern(self, transactions: List[Dict]) -> bool:
        """Detect potential insider trading"""
        # Check for impossibly high win rate with large positions
        buy_txs = [tx for tx in transactions if tx.get('action') == 'BUY']
        
        if len(buy_txs) < 5:
            return False
        
        large_positions = [tx for tx in buy_txs if tx.get('sol_amount', 0) > 10]
        
        # If >90% of large positions are profitable, likely insider
        if len(large_positions) > 5:
            # This would require price data to calculate, simplified for now
            avg_position_size = sum(tx.get('sol_amount', 0) for tx in large_positions) / len(large_positions)
            
            # Extremely large average positions might indicate insider knowledge
            if avg_position_size > 50:
                return True
        
        return False
    
    def _has_diverse_trading_pattern(self, transactions: List[Dict]) -> bool:
        """Check for legitimate diverse trading patterns"""
        unique_tokens = set(tx.get('token_mint') for tx in transactions)
        
        # Should trade multiple different tokens
        if len(unique_tokens) < 5:
            return False
        
        # Should have reasonable position sizes
        buy_amounts = [tx.get('sol_amount', 0) for tx in transactions if tx.get('action') == 'BUY']
        
        if not buy_amounts:
            return False
        
        avg_buy = sum(buy_amounts) / len(buy_amounts)
        
        # Reasonable position sizing (not too small, not too large)
        if avg_buy < 0.5 or avg_buy > 100:
            return False
        
        return True
    
    async def _get_token_transactions(self, token_mint: str) -> List[Dict]:
        # Real call do Helius (przykład z docs)
        url = f"https://api.helius.xyz/v0/tokens/{token_mint}/transactions?api-key={self.helius_key}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"Błąd Helius: {response.status}")
                    return []
    
    async def _get_recent_dex_swaps(self, limit: int) -> List[Dict]:
        """Get recent DEX swap transactions (mock implementation)"""
        # This would analyze DEX program logs (Jupiter, Raydium, etc.)
        # For now, return empty list
        return []
    
    def _detect_pump_start(self, transactions: List[Dict]) -> Optional[datetime]:
        """Detect when a token pump started"""
        # Analyze volume and price action to find pump start
        # Mock implementation
        return None
    
    def _find_pre_pump_buyers(self, transactions: List[Dict], pump_time: datetime) -> List[str]:
        """Find wallets that bought before pump"""
        # Filter transactions before pump_time
        # Return wallet addresses
        return []
    
    def _identify_leaders(self, transactions: List[Dict]) -> List[str]:
        """Identify leader wallets that others follow"""
        leaders = []
        
        if len(transactions) < 3:
            return leaders
        
        # Find first buyer with significant volume
        buy_txs = [tx for tx in transactions if tx.get('action') == 'BUY']
        
        if buy_txs:
            # Sort by timestamp
            buy_txs.sort(key=lambda x: x['timestamp'])
            
            # First buyer with >5 SOL could be leader
            for tx in buy_txs[:3]:  # Check first 3 buyers
                if tx.get('volume', 0) >= 5:
                    leaders.append(tx['wallet'])
        
        return leaders
    
    async def _calculate_quick_win_rate(self, trades: List[Dict]) -> float:
        """Quick win rate calculation"""
        # Simplified calculation - would need price data for accuracy
        buy_trades = len([t for t in trades if t.get('action') == 'BUY'])
        sell_trades = len([t for t in trades if t.get('action') == 'SELL'])
        
        # Assume 70% of completed trades are wins (placeholder)
        completed_trades = min(buy_trades, sell_trades)
        
        if completed_trades < 5:
            return 0.0
        
        # Mock calculation - in reality would compare buy/sell prices
        return 70.0