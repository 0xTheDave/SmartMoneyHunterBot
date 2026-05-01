import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from api_client import RateLimitedAPIClient
from database import SmartWallet, Transaction, get_db
from config import config

logger = logging.getLogger(__name__)

class WalletMonitor:
    def __init__(self):
        self.api = RateLimitedAPIClient()
        self.db = get_db()
        self.processed_signatures = set()
        
        # Load processed signatures from database
        self._load_processed_signatures()
    
    def _load_processed_signatures(self):
        """Load recent processed signatures to avoid duplicates"""
        try:
            cutoff = datetime.utcnow() - timedelta(hours=24)
            recent_transactions = (self.db.query(Transaction)
                                 .filter(Transaction.timestamp >= cutoff)
                                 .all())
            
            self.processed_signatures = {tx.signature for tx in recent_transactions if tx.signature}
            logger.info(f"Loaded {len(self.processed_signatures)} recent signatures")
        except Exception as e:
            logger.error(f"Error loading processed signatures: {e}")
    
    async def monitor_smart_wallets(self) -> List[Dict]:
        """Monitor top smart wallets for new trades"""
        signals = []
        
        try:
            # Get top wallets to monitor
            smart_wallets = (self.db.query(SmartWallet)
                           .filter(SmartWallet.active == True, 
                                  SmartWallet.score >= 70)
                           .order_by(SmartWallet.score.desc())
                           .limit(config.MAX_MONITORED_WALLETS)
                           .all())
            
            logger.info(f"Monitoring {len(smart_wallets)} smart wallets")
            
            for wallet in smart_wallets:
                new_trades = await self._check_wallet_new_trades(wallet)
                
                for trade in new_trades:
                    if trade['action'] == 'BUY' and trade['sol_amount'] >= config.MIN_VOLUME_SOL:
                        signal = await self._analyze_buy_signal(trade, wallet)
                        
                        if signal and signal['score'] >= config.MIN_SIGNAL_SCORE:
                            signals.append(signal)
                
                # Small delay to respect rate limits
                await asyncio.sleep(0.5)
            
            # Limit signals per day
            if len(signals) > config.MAX_SIGNALS_PER_DAY:
                signals = sorted(signals, key=lambda x: x['score'], reverse=True)[:config.MAX_SIGNALS_PER_DAY]
            
            return signals
            
        except Exception as e:
            logger.error(f"Error monitoring wallets: {e}")
            return []
    
    async def _check_wallet_new_trades(self, wallet) -> List[Dict]:
        """Check for new trades from a specific wallet"""
        new_trades = []
        
        try:
            async with self.api as api:
                transactions = await api.get_wallet_transactions(wallet.address, 10)
                
                for tx in transactions:
                    signature = tx.get('signature')
                    
                    if not signature or signature in self.processed_signatures:
                        continue
                    
                    self.processed_signatures.add(signature)
                    
                    # Parse transaction
                    trade = await self._parse_transaction(tx, wallet.address)
                    
                    if trade:
                        # Save to database
                        self._save_transaction(trade)
                        new_trades.append(trade)
                        
                        # Update wallet last activity
                        wallet.last_active = datetime.utcnow()
                        self.db.commit()
        
        except Exception as e:
            logger.error(f"Error checking wallet {wallet.address}: {e}")
        
        return new_trades
    
    async def _parse_transaction(self, tx: Dict, wallet_address: str) -> Optional[Dict]:
        """Parse a single transaction"""
        try:
            if not tx.get('tokenTransfers') or not tx.get('nativeTransfers'):
                return None
            
            token_transfers = tx['tokenTransfers']
            native_transfers = tx['nativeTransfers']
            timestamp = datetime.fromtimestamp(tx.get('timestamp', 0))
            
            # Find relevant transfers
            sol_transfer = next((nt for nt in native_transfers), None)
            token_transfer = next((tt for tt in token_transfers), None)
            
            if not sol_transfer or not token_transfer:
                return None
            
            sol_amount = abs(sol_transfer.get('amount', 0)) / 1e9
            
            # Determine action
            action = 'BUY' if sol_transfer.get('fromUserAccount') == wallet_address else 'SELL'
            
            # Get token info
            token_mint = token_transfer.get('mint')
            token_symbol = f'TOKEN_{token_mint[:8]}' if token_mint else 'UNKNOWN'
            
            return {
                'wallet_address': wallet_address,
                'signature': tx.get('signature'),
                'action': action,
                'token_mint': token_mint,
                'token_symbol': token_symbol,
                'sol_amount': sol_amount,
                'token_amount': token_transfer.get('tokenAmount', 0),
                'timestamp': timestamp
            }
        
        except Exception as e:
            logger.error(f"Error parsing transaction: {e}")
            return None
    
    def _save_transaction(self, trade: Dict):
        """Save transaction to database"""
        try:
            transaction = Transaction(
                wallet_address=trade['wallet_address'],
                token_mint=trade['token_mint'],
                token_symbol=trade['token_symbol'],
                action=trade['action'],
                sol_amount=trade['sol_amount'],
                token_amount=trade.get('token_amount', 0),
                timestamp=trade['timestamp'],
                signature=trade['signature']
            )
            
            self.db.add(transaction)
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Error saving transaction: {e}")
            self.db.rollback()
    
    async def _analyze_buy_signal(self, trade: Dict, wallet) -> Optional[Dict]:
        """Analyze buy signal quality"""
        try:
            # Check for similar recent buys from other smart wallets
            similar_wallets = await self._count_similar_buys(trade['token_mint'])
            
            # Calculate signal score
            score = self._calculate_signal_score(trade, wallet, similar_wallets)
            
            if score < config.MIN_SIGNAL_SCORE:
                return None
            
            # Determine recommendation
            if score >= 95:
                recommendation = "HOT_BUY"
            elif score >= 85:
                recommendation = "STRONG_BUY"
            else:
                recommendation = "WATCH"
            
            return {
                'token_mint': trade['token_mint'],
                'token_symbol': trade['token_symbol'],
                'score': score,
                'recommendation': recommendation,
                'wallet_address': wallet.address,
                'wallet_tier': wallet.tier,
                'wallet_score': wallet.score,
                'sol_amount': trade['sol_amount'],
                'similar_wallets': similar_wallets,
                'timestamp': trade['timestamp']
            }
        
        except Exception as e:
            logger.error(f"Error analyzing buy signal: {e}")
            return None
    
    async def _count_similar_buys(self, token_mint: str) -> int:
        """Count similar buys from other smart wallets in last 24h"""
        try:
            cutoff = datetime.utcnow() - timedelta(hours=24)
            
            similar_count = (self.db.query(Transaction)
                           .join(SmartWallet, Transaction.wallet_address == SmartWallet.address)
                           .filter(
                               Transaction.token_mint == token_mint,
                               Transaction.action == 'BUY',
                               Transaction.timestamp >= cutoff,
                               SmartWallet.active == True,
                               SmartWallet.score >= 70
                           ).count())
            
            return similar_count
        except Exception as e:
            logger.error(f"Error counting similar buys: {e}")
            return 0
    
    def _calculate_signal_score(self, trade: Dict, wallet, similar_wallets: int) -> int:
        """Calculate signal score based on multiple factors"""
        score = 0
        
        # Base score from wallet tier
        if wallet.tier == 'S':
            score += 35
        elif wallet.tier == 'A':
            score += 30
        elif wallet.tier == 'B':
            score += 20
        else:
            score += 10
        
        # Wallet score component
        score += min(wallet.score * 0.3, 30)
        
        # Trade size component
        if trade['sol_amount'] >= 10:
            score += 20
        elif trade['sol_amount'] >= 5:
            score += 15
        elif trade['sol_amount'] >= 2:
            score += 10
        else:
            score += 5
        
        # Similar wallets component (social proof)
        if similar_wallets >= 5:
            score += 15
        elif similar_wallets >= 3:
            score += 10
        elif similar_wallets >= 2:
            score += 5
        
        return min(score, 100)