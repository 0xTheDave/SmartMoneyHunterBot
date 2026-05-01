# enhanced_social_proof.py
import asyncio
import logging
from typing import Dict, List, Set, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from collections import defaultdict
from database import get_db, SmartWallet, Transaction
from api_client import RateLimitedAPIClient

logger = logging.getLogger(__name__)

@dataclass
class SocialSignal:
    token_mint: str
    leader_wallet: str
    follower_wallets: List[str]
    leader_timestamp: datetime
    follower_timestamps: List[datetime]
    time_to_follow: List[float]  # Minutes between leader and followers
    leader_amount: float
    follower_amounts: List[float]
    confidence_score: float
    signal_strength: str  # 'WEAK', 'MODERATE', 'STRONG', 'VERY_STRONG'

class EnhancedSocialProofAnalyzer:
    def __init__(self):
        self.api = RateLimitedAPIClient()
        self.db = get_db()
        self.known_leaders = set()  # Wallets identified as consistent leaders
        self.follower_networks = defaultdict(set)  # leader -> set of followers
        
    async def analyze_social_proof(self, token_mint: str, primary_buyer: str, 
                                 primary_timestamp: datetime) -> SocialSignal:
        """Analyze social proof for a token purchase"""
        try:
            # Get all smart wallet transactions for this token in relevant timeframe
            lookback_hours = 6
            lookforward_hours = 2
            
            start_time = primary_timestamp - timedelta(hours=lookback_hours)
            end_time = primary_timestamp + timedelta(hours=lookforward_hours)
            
            related_transactions = await self._get_token_transactions_in_timeframe(
                token_mint, start_time, end_time
            )
            
            # Analyze timing patterns
            social_signal = await self._analyze_timing_patterns(
                related_transactions, primary_buyer, primary_timestamp
            )
            
            # Calculate confidence score
            social_signal.confidence_score = self._calculate_confidence_score(social_signal)
            
            # Determine signal strength
            social_signal.signal_strength = self._determine_signal_strength(social_signal)
            
            return social_signal
            
        except Exception as e:
            logger.error(f"Error analyzing social proof: {e}")
            return self._create_empty_social_signal(token_mint, primary_buyer, primary_timestamp)
    
    async def _get_token_transactions_in_timeframe(self, token_mint: str, 
                                                 start_time: datetime, 
                                                 end_time: datetime) -> List[Dict]:
        """Get all smart wallet transactions for token in timeframe"""
        try:
            transactions = (
                self.db.query(Transaction)
                .join(SmartWallet, Transaction.wallet_address == SmartWallet.address)
                .filter(
                    Transaction.token_mint == token_mint,
                    Transaction.action == 'BUY',
                    Transaction.timestamp >= start_time,
                    Transaction.timestamp <= end_time,
                    SmartWallet.active == True,
                    SmartWallet.score >= 70
                )
                .order_by(Transaction.timestamp)
                .all()
            )
            
            return [
                {
                    'wallet_address': tx.wallet_address,
                    'timestamp': tx.timestamp,
                    'sol_amount': tx.sol_amount,
                    'wallet_score': self._get_wallet_score(tx.wallet_address)
                }
                for tx in transactions
            ]
            
        except Exception as e:
            logger.error(f"Error getting token transactions: {e}")
            return []
    
    async def _analyze_timing_patterns(self, transactions: List[Dict], 
                                     primary_buyer: str, 
                                     primary_timestamp: datetime) -> SocialSignal:
        """Analyze timing patterns to identify leaders and followers"""
        
        # Find the primary transaction
        primary_tx = next((tx for tx in transactions 
                          if tx['wallet_address'] == primary_buyer), None)
        
        if not primary_tx:
            return self._create_empty_social_signal(
                transactions[0]['token_mint'] if transactions else 'unknown',
                primary_buyer, 
                primary_timestamp
            )
        
        # Separate transactions into before/after primary
        before_transactions = [tx for tx in transactions 
                             if tx['timestamp'] < primary_timestamp]
        after_transactions = [tx for tx in transactions 
                            if tx['timestamp'] > primary_timestamp]
        
        # Determine if primary buyer is leader or follower
        if before_transactions:
            # Primary buyer might be following someone
            leader_candidates = self._identify_leaders(before_transactions, primary_tx)
            if leader_candidates:
                # Primary buyer is follower
                leader = leader_candidates[0]
                followers = [primary_buyer] + [tx['wallet_address'] for tx in after_transactions]
                leader_timestamp = leader['timestamp']
                follower_timestamps = [primary_timestamp] + [tx['timestamp'] for tx in after_transactions]
            else:
                # Primary buyer is leader
                leader = primary_tx
                followers = [tx['wallet_address'] for tx in after_transactions]
                leader_timestamp = primary_timestamp
                follower_timestamps = [tx['timestamp'] for tx in after_transactions]
        else:
            # Primary buyer is definitely leader
            leader = primary_tx
            followers = [tx['wallet_address'] for tx in after_transactions]
            leader_timestamp = primary_timestamp
            follower_timestamps = [tx['timestamp'] for tx in after_transactions]
        
        # Calculate timing metrics
        time_to_follow = [
            (ft - leader_timestamp).total_seconds() / 60  # Convert to minutes
            for ft in follower_timestamps
        ]
        
        follower_amounts = [
            tx['sol_amount'] for tx in after_transactions
            if tx['wallet_address'] in followers
        ]
        
        return SocialSignal(
            token_mint=transactions[0].get('token_mint', 'unknown'),
            leader_wallet=leader['wallet_address'],
            follower_wallets=followers,
            leader_timestamp=leader_timestamp,
            follower_timestamps=follower_timestamps,
            time_to_follow=time_to_follow,
            leader_amount=leader['sol_amount'],
            follower_amounts=follower_amounts,
            confidence_score=0.0,  # Will be calculated later
            signal_strength='WEAK'  # Will be determined later
        )
    
    def _identify_leaders(self, before_transactions: List[Dict], primary_tx: Dict) -> List[Dict]:
        """Identify potential leaders from earlier transactions"""
        leaders = []
        
        for tx in before_transactions:
            # Leader criteria
            is_larger_position = tx['sol_amount'] >= primary_tx['sol_amount'] * 0.8
            is_high_score_wallet = tx['wallet_score'] >= primary_tx['wallet_score']
            is_within_reasonable_time = (primary_tx['timestamp'] - tx['timestamp']).total_seconds() <= 3600  # 1 hour
            
            if is_larger_position and is_high_score_wallet and is_within_reasonable_time:
                leaders.append(tx)
        
        # Sort by wallet score and position size
        leaders.sort(key=lambda x: (x['wallet_score'], x['sol_amount']), reverse=True)
        
        return leaders[:3]  # Return top 3 leader candidates
    
    def _calculate_confidence_score(self, social_signal: SocialSignal) -> float:
        """Calculate confidence score for social signal"""
        score = 0.0
        
        # Number of followers (max 30 points)
        follower_count = len(social_signal.follower_wallets)
        score += min(follower_count * 5, 30)
        
        # Timing quality (max 25 points)
        if social_signal.time_to_follow:
            avg_follow_time = sum(social_signal.time_to_follow) / len(social_signal.time_to_follow)
            
            if avg_follow_time <= 30:  # Within 30 minutes
                score += 25
            elif avg_follow_time <= 60:  # Within 1 hour
                score += 20
            elif avg_follow_time <= 180:  # Within 3 hours
                score += 15
            else:
                score += 5
        
        # Position size correlation (max 20 points)
        if social_signal.follower_amounts:
            # Check if followers have similar position sizes (indicates coordination)
            position_similarity = self._calculate_position_similarity(
                social_signal.leader_amount, social_signal.follower_amounts
            )
            score += position_similarity * 20
        
        # Leader wallet quality (max 15 points)
        leader_score = self._get_wallet_score(social_signal.leader_wallet)
        if leader_score >= 90:
            score += 15
        elif leader_score >= 80:
            score += 12
        elif leader_score >= 70:
            score += 8
        else:
            score += 3
        
        # Historical leader performance (max 10 points)
        if social_signal.leader_wallet in self.known_leaders:
            score += 10
        elif self._check_historical_leadership(social_signal.leader_wallet):
            score += 5
            self.known_leaders.add(social_signal.leader_wallet)
        
        return min(score, 100.0)
    
    def _calculate_position_similarity(self, leader_amount: float, follower_amounts: List[float]) -> float:
        """Calculate how similar follower positions are to leader (0-1 scale)"""
        if not follower_amounts:
            return 0.0
        
        # Calculate coefficient of variation
        similar_count = 0
        for amount in follower_amounts:
            ratio = amount / leader_amount
            # Similar if within 0.5x to 2x of leader position
            if 0.5 <= ratio <= 2.0:
                similar_count += 1
        
        return similar_count / len(follower_amounts)
    
    def _determine_signal_strength(self, social_signal: SocialSignal) -> str:
        """Determine signal strength based on confidence score"""
        if social_signal.confidence_score >= 85:
            return 'VERY_STRONG'
        elif social_signal.confidence_score >= 70:
            return 'STRONG'
        elif social_signal.confidence_score >= 50:
            return 'MODERATE'
        else:
            return 'WEAK'
    
    def _get_wallet_score(self, wallet_address: str) -> float:
        """Get wallet score from database"""
        try:
            wallet = self.db.query(SmartWallet).filter_by(address=wallet_address).first()
            return wallet.score if wallet else 50.0
        except:
            return 50.0
    
    def _check_historical_leadership(self, wallet_address: str) -> bool:
        """Check if wallet has historically been a leader"""
        try:
            # Check if this wallet was first to buy tokens that later pumped
            cutoff_date = datetime.utcnow() - timedelta(days=30)
            
            # This would require more complex analysis of historical data
            # For now, simplified check based on wallet activity timing
            recent_buys = (
                self.db.query(Transaction)
                .filter(
                    Transaction.wallet_address == wallet_address,
                    Transaction.action == 'BUY',
                    Transaction.timestamp >= cutoff_date
                )
                .count()
            )
            
            return recent_buys >= 10  # Active trader
            
        except:
            return False
    
    def _create_empty_social_signal(self, token_mint: str, wallet_address: str, 
                                  timestamp: datetime) -> SocialSignal:
        """Create empty social signal for cases with no social proof"""
        return SocialSignal(
            token_mint=token_mint,
            leader_wallet=wallet_address,
            follower_wallets=[],
            leader_timestamp=timestamp,
            follower_timestamps=[],
            time_to_follow=[],
            leader_amount=0.0,
            follower_amounts=[],
            confidence_score=0.0,
            signal_strength='WEAK'
        )
    
    async def update_follower_networks(self):
        """Update follower network mapping based on recent activity"""
        try:
            # Analyze last 7 days of transactions to identify follower patterns
            cutoff_date = datetime.utcnow() - timedelta(days=7)
            
            # Get all transactions grouped by token
            token_transactions = defaultdict(list)
            
            transactions = (
                self.db.query(Transaction)
                .join(SmartWallet, Transaction.wallet_address == SmartWallet.address)
                .filter(
                    Transaction.action == 'BUY',
                    Transaction.timestamp >= cutoff_date,
                    SmartWallet.active == True,
                    SmartWallet.score >= 70
                )
                .order_by(Transaction.timestamp)
                .all()
            )
            
            # Group by token
            for tx in transactions:
                token_transactions[tx.token_mint].append({
                    'wallet': tx.wallet_address,
                    'timestamp': tx.timestamp,
                    'amount': tx.sol_amount
                })
            
            # Analyze each token for leader-follower patterns
            for token_mint, token_txs in token_transactions.items():
                if len(token_txs) < 3:
                    continue
                
                # Find patterns where one wallet consistently buys first
                self._analyze_leadership_patterns(token_txs)
            
            logger.info(f"Updated follower networks: {len(self.known_leaders)} known leaders")
            
        except Exception as e:
            logger.error(f"Error updating follower networks: {e}")
    
    def _analyze_leadership_patterns(self, token_transactions: List[Dict]):
        """Analyze transactions to identify leader-follower relationships"""
        if len(token_transactions) < 3:
            return
        
        # Sort by timestamp
        token_transactions.sort(key=lambda x: x['timestamp'])
        
        # Check if first few buyers are consistent leaders
        potential_leaders = token_transactions[:3]
        
        for leader_tx in potential_leaders:
            leader_wallet = leader_tx['wallet']
            leader_time = leader_tx['timestamp']
            
            # Find wallets that bought after this leader (within 2 hours)
            followers = []
            for tx in token_transactions:
                if (tx['wallet'] != leader_wallet and 
                    tx['timestamp'] > leader_time and
                    (tx['timestamp'] - leader_time).total_seconds() <= 7200):  # 2 hours
                    followers.append(tx['wallet'])
            
            if len(followers) >= 2:
                # This wallet shows leadership in this token
                self.follower_networks[leader_wallet].update(followers)
                
                # If wallet has multiple follower instances, mark as known leader
                if len(self.follower_networks[leader_wallet]) >= 5:
                    self.known_leaders.add(leader_wallet)