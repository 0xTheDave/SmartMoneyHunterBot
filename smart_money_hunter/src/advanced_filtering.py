# advanced_filtering.py
import asyncio
import logging
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from collections import Counter, defaultdict
import numpy as np
from database import get_db, Transaction, SmartWallet
from api_client import RateLimitedAPIClient

logger = logging.getLogger(__name__)

@dataclass
class FilterResult:
    is_legitimate: bool
    risk_score: float  # 0-100, higher = more risky
    risk_factors: List[str]
    confidence: float  # 0-1

@dataclass
class TokenRiskAssessment:
    token_mint: str
    market_cap: Optional[float]
    liquidity: Optional[float]
    holder_concentration: Optional[float]
    age_hours: Optional[float]
    volume_24h: Optional[float]
    risk_score: float
    risk_factors: List[str]

class AdvancedFilteringSystem:
    def __init__(self):
        self.api = RateLimitedAPIClient()
        self.db = get_db()
        self.known_mev_bots = set()
        self.known_insiders = set()
        self.pump_group_addresses = set()
        self.suspicious_patterns_cache = {}
        
    async def comprehensive_wallet_filter(self, wallet_address: str) -> FilterResult:
        """Comprehensive filtering to detect illegitimate wallets"""
        risk_factors = []
        risk_score = 0.0
        
        try:
            # Get wallet transaction history
            async with self.api as api:
                transactions = await api.get_wallet_transactions(wallet_address, 200)
            
            if not transactions:
                return FilterResult(False, 100.0, ["No transaction data"], 0.1)
            
            # Run all filter checks
            mev_result = await self._check_mev_bot_patterns(transactions)
            wash_result = await self._check_wash_trading(transactions)
            insider_result = await self._check_insider_patterns(transactions)
            pump_result = await self._check_pump_group_activity(transactions)
            coordination_result = await self._check_coordination_patterns(wallet_address, transactions)
            
            # Aggregate results
            checks = [mev_result, wash_result, insider_result, pump_result, coordination_result]
            
            for check in checks:
                risk_score += check.risk_score
                risk_factors.extend(check.risk_factors)
            
            # Normalize risk score
            risk_score = min(risk_score / len(checks), 100.0)
            
            # Determine legitimacy
            is_legitimate = risk_score < 70.0
            confidence = self._calculate_confidence(checks)
            
            return FilterResult(is_legitimate, risk_score, risk_factors, confidence)
            
        except Exception as e:
            logger.error(f"Error in comprehensive wallet filter: {e}")
            return FilterResult(False, 90.0, ["Filter error"], 0.1)
    
    async def _check_mev_bot_patterns(self, transactions: List[Dict]) -> FilterResult:
        """Advanced MEV bot detection"""
        risk_factors = []
        risk_score = 0.0
        
        if len(transactions) < 10:
            return FilterResult(True, 0.0, [], 0.5)
        
        # 1. Timing analysis - extremely fast transactions
        time_diffs = []
        for i in range(1, len(transactions)):
            diff = abs(transactions[i]['timestamp'] - transactions[i-1]['timestamp'])
            time_diffs.append(diff)
        
        if time_diffs:
            avg_time_diff = sum(time_diffs) / len(time_diffs)
            median_time_diff = sorted(time_diffs)[len(time_diffs)//2]
            
            if avg_time_diff < 30:  # Less than 30 seconds average
                risk_score += 25
                risk_factors.append("Extremely fast trading (avg <30s)")
            
            if median_time_diff < 10:  # Median less than 10 seconds
                risk_score += 15
                risk_factors.append("Median transaction time <10s")
        
        # 2. Sandwich attack detection
        sandwich_patterns = 0
        for i in range(len(transactions) - 2):
            tx1, tx2, tx3 = transactions[i:i+3]
            
            # Look for BUY-SELL pattern on same token within minutes
            if (self._extract_action(tx1) == 'BUY' and 
                self._extract_action(tx3) == 'SELL' and
                self._extract_token(tx1) == self._extract_token(tx3) and
                abs(tx3['timestamp'] - tx1['timestamp']) < 300):
                sandwich_patterns += 1
        
        sandwich_ratio = sandwich_patterns / (len(transactions) / 3)
        if sandwich_ratio > 0.2:  # More than 20% sandwich patterns
            risk_score += 30
            risk_factors.append(f"High sandwich pattern ratio: {sandwich_ratio:.1%}")
        
        # 3. Failed transaction analysis (MEV bots have high failure rates)
        # This would require access to failed transactions from API
        
        # 4. Gas price analysis - MEV bots often use very high gas
        # This would require gas price data from transactions
        
        is_legitimate = risk_score < 40
        return FilterResult(is_legitimate, risk_score, risk_factors, 0.8)
    
    async def _check_wash_trading(self, transactions: List[Dict]) -> FilterResult:
        """Detect wash trading patterns"""
        risk_factors = []
        risk_score = 0.0
        
        # Group transactions by token
        token_txs = defaultdict(list)
        for tx in transactions:
            token = self._extract_token(tx)
            if token:
                token_txs[token].append(tx)
        
        total_suspicious_tokens = 0
        
        for token, txs in token_txs.items():
            if len(txs) < 4:
                continue
            
            # Sort by timestamp
            txs.sort(key=lambda x: x['timestamp'])
            
            # Look for alternating BUY/SELL patterns
            actions = [self._extract_action(tx) for tx in txs]
            alternating_count = 0
            
            for i in range(len(actions) - 1):
                if actions[i] != actions[i+1]:
                    alternating_count += 1
            
            alternating_ratio = alternating_count / (len(actions) - 1)
            
            # Check volume consistency (wash traders use similar amounts)
            volumes = [self._extract_volume(tx) for tx in txs if self._extract_volume(tx) > 0]
            if len(volumes) >= 4:
                volume_std = np.std(volumes)
                volume_mean = np.mean(volumes)
                coefficient_of_variation = volume_std / volume_mean if volume_mean > 0 else 0
                
                # Low variation suggests wash trading
                if coefficient_of_variation < 0.2 and alternating_ratio > 0.6:
                    total_suspicious_tokens += 1
                    risk_factors.append(f"Suspicious wash trading in {token[:8]}...")
        
        if total_suspicious_tokens > len(token_txs) * 0.3:
            risk_score = 60
            risk_factors.append(f"Wash trading detected in {total_suspicious_tokens} tokens")
        elif total_suspicious_tokens > 0:
            risk_score = 30
        
        is_legitimate = risk_score < 50
        return FilterResult(is_legitimate, risk_score, risk_factors, 0.7)
    
    async def _check_insider_patterns(self, transactions: List[Dict]) -> FilterResult:
        """Detect insider trading patterns"""
        risk_factors = []
        risk_score = 0.0
        
        buy_transactions = [tx for tx in transactions if self._extract_action(tx) == 'BUY']
        
        if len(buy_transactions) < 5:
            return FilterResult(True, 0.0, [], 0.5)
        
        # 1. Impossibly high success rate with large positions
        large_buys = [tx for tx in buy_transactions if self._extract_volume(tx) >= 10]
        
        if len(large_buys) >= 5:
            # This would require price data to calculate actual success rate
            # For now, use proxy: large positions + unusual timing patterns
            
            # Check if buys happen right before major events (simplified)
            unusual_timing_count = 0
            for buy in large_buys:
                # Look for buys at unusual hours (potential inside info timing)
                hour = datetime.fromtimestamp(buy['timestamp']).hour
                if hour < 6 or hour > 22:  # Very early or very late
                    unusual_timing_count += 1
            
            if unusual_timing_count > len(large_buys) * 0.4:
                risk_score += 25
                risk_factors.append("Unusual timing for large positions")
        
        # 2. Extremely concentrated token selection
        token_counts = Counter(self._extract_token(tx) for tx in buy_transactions)
        unique_tokens = len(token_counts)
        
        if unique_tokens < 3 and len(buy_transactions) > 20:
            risk_score += 20
            risk_factors.append("Extremely concentrated token selection")
        
        # 3. Sudden portfolio changes (would need historical analysis)
        # This would track changes in trading patterns over time
        
        is_legitimate = risk_score < 40
        return FilterResult(is_legitimate, risk_score, risk_factors, 0.6)
    
    async def _check_pump_group_activity(self, transactions: List[Dict]) -> FilterResult:
        """Detect coordinated pump group activity"""
        risk_factors = []
        risk_score = 0.0
        
        buy_transactions = [tx for tx in transactions if self._extract_action(tx) == 'BUY']
        
        # 1. Check for coordinated timing with known pump tokens
        # This would require a database of known pump tokens and their timing
        
        # 2. Look for uniform position sizes (pump groups often suggest specific amounts)
        volumes = [self._extract_volume(tx) for tx in buy_transactions if self._extract_volume(tx) > 0]
        
        if len(volumes) >= 10:
            # Look for clustering around specific amounts (1 SOL, 5 SOL, 10 SOL, etc.)
            common_amounts = [1, 2, 5, 10, 20, 50]
            clustering_score = 0
            
            for amount in common_amounts:
                close_to_amount = sum(1 for v in volumes if abs(v - amount) < amount * 0.1)
                if close_to_amount > len(volumes) * 0.2:
                    clustering_score += close_to_amount
            
            if clustering_score > len(volumes) * 0.4:
                risk_score += 30
                risk_factors.append("Suspicious position size clustering")
        
        # 3. Token selection patterns (pump groups target similar types)
        # This would analyze token characteristics for patterns
        
        is_legitimate = risk_score < 35
        return FilterResult(is_legitimate, risk_score, risk_factors, 0.6)
    
    async def _check_coordination_patterns(self, wallet_address: str, 
                                         transactions: List[Dict]) -> FilterResult:
        """Check for coordination with other suspicious wallets"""
        risk_factors = []
        risk_score = 0.0
        
        # 1. Check for synchronized trading with other wallets
        buy_tokens = set(self._extract_token(tx) for tx in transactions 
                        if self._extract_action(tx) == 'BUY')
        
        coordination_count = 0
        
        for token in buy_tokens:
            if not token:
                continue
                
            # Find other wallets that bought same token around same time
            similar_wallets = await self._find_wallets_trading_token_simultaneously(
                token, wallet_address, transactions
            )
            
            if len(similar_wallets) > 5:  # Many wallets buying same obscure token
                coordination_count += 1
        
        if coordination_count > len(buy_tokens) * 0.3:
            risk_score += 25
            risk_factors.append("High coordination with other wallets")
        
        is_legitimate = risk_score < 30
        return FilterResult(is_legitimate, risk_score, risk_factors, 0.5)
    
    async def assess_token_risk(self, token_mint: str) -> TokenRiskAssessment:
        """Assess risk factors for a specific token"""
        risk_factors = []
        risk_score = 0.0
        
        try:
            # Get token metadata
            async with self.api as api:
                token_price = await api.get_token_price_cached(token_mint)
                # Additional token info would come from other API endpoints
            
            # 1. Market cap analysis
            # Small market caps are riskier
            # This would require market cap data from API
            
            # 2. Liquidity analysis
            # Low liquidity = high risk
            
            # 3. Holder concentration
            # Few holders = high risk
            
            # 4. Age analysis
            # Very new tokens = high risk
            
            # 5. Volume analysis
            # Suspicious volume patterns
            
            return TokenRiskAssessment(
                token_mint=token_mint,
                market_cap=None,  # Would be populated with real data
                liquidity=None,
                holder_concentration=None,
                age_hours=None,
                volume_24h=None,
                risk_score=risk_score,
                risk_factors=risk_factors
            )
            
        except Exception as e:
            logger.error(f"Error assessing token risk: {e}")
            return TokenRiskAssessment(
                token_mint=token_mint,
                market_cap=None,
                liquidity=None,
                holder_concentration=None,
                age_hours=None,
                volume_24h=None,
                risk_score=90.0,
                risk_factors=["Risk assessment failed"]
            )
    
    def _extract_action(self, transaction: Dict) -> Optional[str]:
        """Extract BUY/SELL action from transaction"""
        # Implementation depends on transaction format
        return transaction.get('action')
    
    def _extract_token(self, transaction: Dict) -> Optional[str]:
        """Extract token mint from transaction"""
        return transaction.get('token_mint') or transaction.get('mint')
    
    def _extract_volume(self, transaction: Dict) -> float:
        """Extract SOL volume from transaction"""
        return transaction.get('sol_amount', 0) or transaction.get('amount', 0)
    
    def _calculate_confidence(self, checks: List[FilterResult]) -> float:
        """Calculate overall confidence in filtering decision"""
        confidences = [check.confidence for check in checks]
        return sum(confidences) / len(confidences) if confidences else 0.5
    
    async def _find_wallets_trading_token_simultaneously(self, token_mint: str, 
                                                       exclude_wallet: str, 
                                                       reference_transactions: List[Dict]) -> List[str]:
        """Find wallets trading same token around same time"""
        # Get timestamps for reference wallet's trades
        ref_times = [tx['timestamp'] for tx in reference_transactions 
                    if self._extract_token(tx) == token_mint]
        
        if not ref_times:
            return []
        
        # Find other transactions for this token in similar timeframe
        similar_wallets = set()
        
        try:
            for ref_time in ref_times:
                start_time = datetime.fromtimestamp(ref_time) - timedelta(hours=2)
                end_time = datetime.fromtimestamp(ref_time) + timedelta(hours=2)
                
                similar_transactions = (
                    self.db.query(Transaction)
                    .filter(
                        Transaction.token_mint == token_mint,
                        Transaction.timestamp >= start_time,
                        Transaction.timestamp <= end_time,
                        Transaction.wallet_address != exclude_wallet
                    )
                    .all()
                )
                
                for tx in similar_transactions:
                    similar_wallets.add(tx.wallet_address)
            
            return list(similar_wallets)
            
        except Exception as e:
            logger.error(f"Error finding simultaneous traders: {e}")
            return []