# historical_validation.py
import asyncio
import logging
from typing import Dict, List, Optional
from database import Base
from datetime import datetime, timedelta
from dataclasses import dataclass
from database import get_db, Signal, SmartWallet
from api_client import RateLimitedAPIClient
from sqlalchemy import Column, String, Float, Integer, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

logger = logging.getLogger(__name__)

@dataclass
class SignalPerformance:
    signal_id: int
    token_mint: str
    entry_price: float
    price_1h: Optional[float] = None
    price_24h: Optional[float] = None
    price_7d: Optional[float] = None
    return_1h: Optional[float] = None
    return_24h: Optional[float] = None
    return_7d: Optional[float] = None
    max_gain: Optional[float] = None
    max_drawdown: Optional[float] = None
    validated_at: datetime = None

class SignalValidator:
    def __init__(self):
        self.api = RateLimitedAPIClient()
        self.db = get_db()
        
    async def validate_all_pending_signals(self):
        """Validate performance of all untracked signals"""
        logger.info("Starting signal validation cycle...")
        
        try:
            # Get unvalidated signals older than 1 hour
            cutoff_time = datetime.utcnow() - timedelta(hours=1)
            pending_signals = (
                self.db.query(Signal)
                .filter(
                    Signal.created_at <= cutoff_time,
                    ~Signal.id.in_(
                        self.db.query(SignalPerformanceDB.signal_id).subquery()
                    )
                )
                .order_by(Signal.created_at.desc())
                .limit(50)
                .all()
            )
            
            logger.info(f"Found {len(pending_signals)} signals to validate")
            
            for signal in pending_signals:
                await self._validate_signal_performance(signal)
                await asyncio.sleep(1)  # Rate limiting
                
            # Update wallet scores based on signal performance
            await self._update_wallet_scores_from_performance()
            
        except Exception as e:
            logger.error(f"Error in signal validation: {e}")
    
    async def _validate_signal_performance(self, signal: Signal):
        """Validate performance of a single signal"""
        try:
            # Get current token price
            current_price = await self._get_token_price_with_retry(signal.token_mint)
            
            if not current_price:
                logger.warning(f"Could not get price for {signal.token_symbol}")
                return
            
            # Calculate time-based performance
            time_since_signal = datetime.utcnow() - signal.created_at
            hours_passed = time_since_signal.total_seconds() / 3600
            
            # Get historical prices at different intervals
            performance = SignalPerformance(
                signal_id=signal.id,
                token_mint=signal.token_mint,
                entry_price=current_price,  # Simplified - in reality need price at signal time
                validated_at=datetime.utcnow()
            )
            
            # If enough time has passed, get interval prices
            if hours_passed >= 1:
                performance.price_1h = current_price
                performance.return_1h = ((current_price - performance.entry_price) / performance.entry_price) * 100
            
            if hours_passed >= 24:
                performance.price_24h = current_price
                performance.return_24h = ((current_price - performance.entry_price) / performance.entry_price) * 100
            
            if hours_passed >= 168:  # 7 days
                performance.price_7d = current_price
                performance.return_7d = ((current_price - performance.entry_price) / performance.entry_price) * 100
            
            # Save performance data
            await self._save_signal_performance(performance)
            
            # Update signal success metrics
            await self._update_signal_metrics(signal, performance)
            
            logger.info(f"Validated signal {signal.id}: {signal.token_symbol} - 1h: {performance.return_1h:.1f}%")
            
        except Exception as e:
            logger.error(f"Error validating signal {signal.id}: {e}")
    
    async def _get_token_price_with_retry(self, token_mint: str, retries: int = 3) -> Optional[float]:
        """Get token price with retry logic"""
        for attempt in range(retries):
            try:
                async with self.api as api:
                    price = await api.get_token_price_cached(token_mint)
                    if price:
                        return price
                        
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                
            except Exception as e:
                logger.error(f"Price fetch attempt {attempt + 1} failed: {e}")
        
        return None
    
    async def _save_signal_performance(self, performance: SignalPerformance):
        """Save signal performance to database"""
        try:
            perf_record = SignalPerformanceDB(
                signal_id=performance.signal_id,
                token_mint=performance.token_mint,
                entry_price=performance.entry_price,
                price_1h=performance.price_1h,
                price_24h=performance.price_24h,
                price_7d=performance.price_7d,
                return_1h=performance.return_1h,
                return_24h=performance.return_24h,
                return_7d=performance.return_7d,
                max_gain=performance.max_gain,
                max_drawdown=performance.max_drawdown,
                validated_at=performance.validated_at
            )
            
            self.db.add(perf_record)
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Error saving signal performance: {e}")
            self.db.rollback()
    
    async def _update_signal_metrics(self, signal: Signal, performance: SignalPerformance):
        """Update signal with success/failure status"""
        try:
            # Determine if signal was successful
            success_threshold = 5.0  # 5% gain considered success
            
            is_successful = False
            if performance.return_24h and performance.return_24h >= success_threshold:
                is_successful = True
            elif performance.return_1h and performance.return_1h >= success_threshold:
                is_successful = True
            
            # Update signal record
            signal.is_successful = is_successful
            signal.actual_return_1h = performance.return_1h
            signal.actual_return_24h = performance.return_24h
            signal.actual_return_7d = performance.return_7d
            signal.validated_at = datetime.utcnow()
            
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Error updating signal metrics: {e}")
            self.db.rollback()
    
    async def _update_wallet_scores_from_performance(self):
        """Update wallet scores based on their signal success rates"""
        try:
            # Get wallet performance statistics
            wallet_stats = self._calculate_wallet_success_rates()
            
            for wallet_address, stats in wallet_stats.items():
                wallet = self.db.query(SmartWallet).filter_by(address=wallet_address).first()
                
                if wallet and stats['total_signals'] >= 3:  # Minimum signals for adjustment
                    # Adjust wallet score based on actual performance
                    success_rate = stats['success_rate']
                    
                    if success_rate >= 80:
                        wallet.score = min(wallet.score + 2, 100)
                    elif success_rate >= 60:
                        wallet.score = wallet.score  # No change
                    elif success_rate >= 40:
                        wallet.score = max(wallet.score - 3, 50)
                    else:
                        wallet.score = max(wallet.score - 5, 30)
                        wallet.active = False  # Deactivate poor performers
                    
                    # Update tier based on new score
                    if wallet.score >= 90: wallet.tier = 'S'
                    elif wallet.score >= 80: wallet.tier = 'A'
                    elif wallet.score >= 70: wallet.tier = 'B'
                    else: wallet.tier = 'C'
                    
                    wallet.last_updated = datetime.utcnow()
            
            self.db.commit()
            logger.info("Updated wallet scores based on signal performance")
            
        except Exception as e:
            logger.error(f"Error updating wallet scores: {e}")
            self.db.rollback()
    
    def _calculate_wallet_success_rates(self) -> Dict[str, Dict]:
        """Calculate success rates for each wallet"""
        try:
            # Query to get wallet signal performance
            query = """
            SELECT 
                s.wallet_address,
                COUNT(*) as total_signals,
                SUM(CASE WHEN s.is_successful = 1 THEN 1 ELSE 0 END) as successful_signals,
                AVG(s.actual_return_24h) as avg_return_24h
            FROM signals s
            WHERE s.validated_at IS NOT NULL
            GROUP BY s.wallet_address
            HAVING COUNT(*) >= 3
            """
            
            result = self.db.execute(query).fetchall()
            
            wallet_stats = {}
            for row in result:
                wallet_stats[row[0]] = {
                    'total_signals': row[1],
                    'successful_signals': row[2],
                    'success_rate': (row[2] / row[1]) * 100,
                    'avg_return_24h': row[3] or 0
                }
            
            return wallet_stats
            
        except Exception as e:
            logger.error(f"Error calculating wallet success rates: {e}")
            return {}
    
    async def get_signal_analytics(self) -> Dict:
        """Get comprehensive signal analytics"""
        try:
            analytics = {}
            
            # Overall performance metrics
            total_signals = self.db.query(Signal).filter(Signal.validated_at.isnot(None)).count()
            successful_signals = self.db.query(Signal).filter(Signal.is_successful == True).count()
            
            analytics['total_validated_signals'] = total_signals
            analytics['overall_success_rate'] = (successful_signals / total_signals * 100) if total_signals > 0 else 0
            
            # Performance by recommendation type
            recommendations = ['HOT_BUY', 'STRONG_BUY', 'WATCH']
            for rec in recommendations:
                rec_total = self.db.query(Signal).filter(
                    Signal.recommendation == rec,
                    Signal.validated_at.isnot(None)
                ).count()
                
                rec_successful = self.db.query(Signal).filter(
                    Signal.recommendation == rec,
                    Signal.is_successful == True
                ).count()
                
                analytics[f'{rec.lower()}_success_rate'] = (rec_successful / rec_total * 100) if rec_total > 0 else 0
            
            # Performance by wallet tier
            tiers = ['S', 'A', 'B', 'C']
            for tier in tiers:
                tier_total = self.db.query(Signal).filter(
                    Signal.wallet_tier == tier,
                    Signal.validated_at.isnot(None)
                ).count()
                
                tier_successful = self.db.query(Signal).filter(
                    Signal.wallet_tier == tier,
                    Signal.is_successful == True
                ).count()
                
                analytics[f'tier_{tier.lower()}_success_rate'] = (tier_successful / tier_total * 100) if tier_total > 0 else 0
            
            # Average returns
            avg_returns = self.db.query(Signal).filter(
                Signal.actual_return_24h.isnot(None)
            ).with_entities(
                Signal.actual_return_24h.label('return_24h')
            ).all()
            
            if avg_returns:
                returns = [r.return_24h for r in avg_returns if r.return_24h is not None]
                analytics['avg_return_24h'] = sum(returns) / len(returns) if returns else 0
                analytics['median_return_24h'] = sorted(returns)[len(returns)//2] if returns else 0
            
            return analytics
            
        except Exception as e:
            logger.error(f"Error getting signal analytics: {e}")
            return {}

# Add to database.py
class SignalPerformanceDB(Base):
    __tablename__ = 'signal_performance'
    
    id = Column(Integer, primary_key=True)
    signal_id = Column(Integer, unique=True)  # FK to signals table
    token_mint = Column(String)
    entry_price = Column(Float)
    price_1h = Column(Float)
    price_24h = Column(Float) 
    price_7d = Column(Float)
    return_1h = Column(Float)
    return_24h = Column(Float)
    return_7d = Column(Float)
    max_gain = Column(Float)
    max_drawdown = Column(Float)
    validated_at = Column(DateTime, default=datetime.utcnow)

# Add these columns to existing Signal model
# is_successful = Column(Boolean)
# actual_return_1h = Column(Float)
# actual_return_24h = Column(Float)  
# actual_return_7d = Column(Float)
# validated_at = Column(DateTime)