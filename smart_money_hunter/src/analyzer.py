import statistics
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from api_client import RateLimitedAPIClient
from database import get_db
from config import config
import logging

logger = logging.getLogger(__name__)

class WalletAnalyzer:
    def __init__(self):
        self.api = RateLimitedAPIClient()
        self.db = get_db()
    
    # TESTOWE DANE - zwracamy symulowane metryki (remove or comment out this block if not needed)
    # async def analyze_wallet_performance(self, wallet_address: str) -> Optional[Dict]:
    #     """Analyze wallet performance with real transaction data"""
    #     logger.info(f"Analyzing wallet {wallet_address[:8]}... (TEST MODE)")
    #     return {
    #         'total_trades': 50,
    #         'win_rate': 75.0,
    #         'avg_roi': 150.0,
    #         'timing_score': 85.0,
    #         'consistency': 80.0,
    #         'total_volume': 500.0,
    #         'recent_activity': 5
    #     }

    async def analyze_wallet_performance(self, wallet_address: str) -> Optional[Dict]:
        """Analyze wallet performance with real transaction data"""
        try:
            async with self.api as api:
                transactions = await api.get_wallet_transactions(wallet_address, 100)
                
                if not transactions or len(transactions) < config.MIN_WALLET_TRADES:
                    return None
                
                parsed_trades = await self._parse_real_transactions(transactions)
                
                if len(parsed_trades) < config.MIN_WALLET_TRADES:
                    return None
                
                metrics = {
                    'total_trades': len(parsed_trades),
                    'win_rate': self._calculate_win_rate(parsed_trades),
                    'avg_roi': self._calculate_avg_roi(parsed_trades),
                    'timing_score': self._calculate_timing_score(parsed_trades),
                    'consistency': self._calculate_consistency(parsed_trades),
                    'total_volume': sum([t.get('sol_amount', 0) for t in parsed_trades]),
                    'recent_activity': self._calculate_recent_activity(parsed_trades)
                }
                
                return metrics
        except Exception as e:
            logger.error(f"Error analyzing wallet {wallet_address}: {e}")
            return None
    
    async def _parse_real_transactions(self, transactions: List[Dict]) -> List[Dict]:
        """Parse real Helius transaction data"""
        parsed = []
        
        for tx in transactions:
            try:
                if not tx.get('tokenTransfers') or not tx.get('nativeTransfers'):
                    continue
                
                token_transfers = tx['tokenTransfers']
                native_transfers = tx['nativeTransfers']
                timestamp = datetime.fromtimestamp(tx.get('timestamp', 0))
                
                sol_transfer = next((nt for nt in native_transfers), None)
                token_transfer = next((tt for tt in token_transfers), None)
                
                if not sol_transfer or not token_transfer:
                    continue
                
                sol_amount = abs(sol_transfer.get('amount', 0)) / 1e9
                
                if sol_amount < config.MIN_VOLUME_SOL:
                    continue
                
                action = 'BUY' if sol_transfer.get('fromUserAccount') else 'SELL'
                
                trade = {
                    'signature': tx.get('signature'),
                    'timestamp': timestamp,
                    'action': action,
                    'token_mint': token_transfer.get('mint'),
                    'sol_amount': sol_amount,
                    'token_amount': token_transfer.get('tokenAmount', 0)
                }
                
                parsed.append(trade)
                
            except Exception as e:
                logger.error(f"Error parsing transaction: {e}")
                continue
        
        return parsed
    
    def _calculate_win_rate(self, trades: List[Dict]) -> float:
        """Calculate win rate by matching buy/sell pairs"""
        token_positions = {}
        wins = 0
        total_closed = 0
        
        for trade in sorted(trades, key=lambda x: x['timestamp']):
            token = trade['token_mint']
            
            if trade['action'] == 'BUY':
                if token not in token_positions:
                    token_positions[token] = []
                token_positions[token].append({
                    'amount': trade['token_amount'],
                    'price': trade['sol_amount'] / trade['token_amount'] if trade['token_amount'] > 0 else 0,
                    'timestamp': trade['timestamp']
                })
            
            elif trade['action'] == 'SELL' and token in token_positions:
                positions = token_positions[token]
                if positions:
                    buy_position = positions.pop(0)
                    
                    sell_price = trade['sol_amount'] / trade['token_amount'] if trade['token_amount'] > 0 else 0
                    buy_price = buy_position['price']
                    
                    if sell_price > buy_price:
                        wins += 1
                    total_closed += 1
        
        return (wins / total_closed * 100) if total_closed > 0 else 0.0
    
    def _calculate_avg_roi(self, trades: List[Dict]) -> float:
        """Calculate average ROI from completed trades"""
        token_positions = {}
        rois = []
        
        for trade in sorted(trades, key=lambda x: x['timestamp']):
            token = trade['token_mint']
            
            if trade['action'] == 'BUY':
                if token not in token_positions:
                    token_positions[token] = []
                token_positions[token].append({
                    'amount': trade['token_amount'],
                    'cost': trade['sol_amount'],
                    'timestamp': trade['timestamp']
                })
            
            elif trade['action'] == 'SELL' and token in token_positions:
                positions = token_positions[token]
                if positions:
                    buy_position = positions.pop(0)
                    roi = ((trade['sol_amount'] - buy_position['cost']) / buy_position['cost']) * 100
                    rois.append(roi)
        
        return statistics.mean(rois) if rois else 0.0
    
    def _calculate_timing_score(self, trades: List[Dict]) -> float:
        """Calculate timing score based on buy patterns"""
        if not trades:
            return 0.0
        
        buy_trades = [t for t in trades if t['action'] == 'BUY']
        
        if not buy_trades:
            return 0.0
        
        avg_volume = statistics.mean([t['sol_amount'] for t in buy_trades])
        early_buys = len([t for t in buy_trades if t['sol_amount'] >= avg_volume])
        
        timing_ratio = early_buys / len(buy_trades) if buy_trades else 0
        return min(timing_ratio * 100, 100)
    
    def _calculate_consistency(self, trades: List[Dict]) -> float:
        """Calculate consistency score based on ROI variance"""
        if len(trades) < 3:
            return 0.0
        
        weekly_performance = {}
        
        for trade in trades:
            week = trade['timestamp'].isocalendar()[:2]
            if week not in weekly_performance:
                weekly_performance[week] = []
            weekly_performance[week].append(trade)
        
        weekly_rois = []
        for week_trades in weekly_performance.values():
            if len(week_trades) >= 2:
                total_invested = sum([t['sol_amount'] for t in week_trades if t['action'] == 'BUY'])
                total_returned = sum([t['sol_amount'] for t in week_trades if t['action'] == 'SELL'])
                
                if total_invested > 0:
                    weekly_roi = ((total_returned - total_invested) / total_invested) * 100
                    weekly_rois.append(weekly_roi)
        
        if len(weekly_rois) < 2:
            return 50.0
        
        std_dev = statistics.stdev(weekly_rois)
        consistency_score = max(0, 100 - (std_dev / 10))
        return min(consistency_score, 100)
    
    def _calculate_recent_activity(self, trades: List[Dict]) -> int:
        """Calculate recent activity score"""
        cutoff = datetime.utcnow() - timedelta(days=7)
        return len([t for t in trades if t['timestamp'] >= cutoff])