# portfolio_tracking.py
import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from database import get_db, Base, Signal
from api_client import RateLimitedAPIClient

logger = logging.getLogger(__name__)

@dataclass
class PortfolioEntry:
    token_mint: str
    token_symbol: str
    entry_price: float
    entry_time: datetime
    position_size: float
    current_price: Optional[float] = None
    current_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    days_held: Optional[int] = None
    status: str = "OPEN"  # OPEN, CLOSED, EXPIRED

class PortfolioTracker:
    def __init__(self):
        self.api = RateLimitedAPIClient()
        self.db = get_db()
        
    async def track_all_signals(self):
        """Track performance of all active signal positions"""
        logger.info("Starting portfolio tracking cycle...")
        
        try:
            # Get all signals that need tracking
            active_positions = self._get_active_positions()
            logger.info(f"Tracking {len(active_positions)} active positions")
            
            for position in active_positions:
                await self._update_position_performance(position)
                await asyncio.sleep(0.5)  # Rate limiting
                
            # Generate portfolio summary
            await self._generate_portfolio_summary()
            
        except Exception as e:
            logger.error(f"Error in portfolio tracking: {e}")
    
    def _get_active_positions(self) -> List['SignalPortfolio']:
        """Get all positions that need tracking"""
        try:
            # Get signals from last 30 days that aren't closed
            cutoff_date = datetime.utcnow() - timedelta(days=30)
            
            return (
                self.db.query(SignalPortfolio)
                .filter(
                    SignalPortfolio.entry_time >= cutoff_date,
                    SignalPortfolio.status.in_(['OPEN', 'TRACKING'])
                )
                .all()
            )
            
        except Exception as e:
            logger.error(f"Error getting active positions: {e}")
            return []
    
    async def _update_position_performance(self, position: 'SignalPortfolio'):
        """Update performance metrics for a single position"""
        try:
            # Get current token price
            async with self.api as api:
                current_price = await api.get_token_price_cached(position.token_mint)
            
            if not current_price:
                logger.warning(f"Could not get price for {position.token_symbol}")
                return
            
            # Calculate performance metrics
            days_held = (datetime.utcnow() - position.entry_time).days
            unrealized_pnl_pct = ((current_price - position.entry_price) / position.entry_price) * 100
            unrealized_pnl = position.position_size * (unrealized_pnl_pct / 100)
            
            # Update position
            position.current_price = current_price
            position.current_value = position.position_size * (1 + unrealized_pnl_pct / 100)
            position.unrealized_pnl = unrealized_pnl
            position.unrealized_pnl_pct = unrealized_pnl_pct
            position.days_held = days_held
            position.last_updated = datetime.utcnow()
            
            # Determine if position should be closed
            if days_held >= 30:  # Auto-close after 30 days
                position.status = "EXPIRED"
                position.exit_price = current_price
                position.exit_time = datetime.utcnow()
                position.realized_pnl = unrealized_pnl
                position.realized_pnl_pct = unrealized_pnl_pct
            
            self.db.commit()
            
            logger.debug(f"Updated {position.token_symbol}: {unrealized_pnl_pct:.1f}% over {days_held} days")
            
        except Exception as e:
            logger.error(f"Error updating position {position.id}: {e}")
            self.db.rollback()
    
    async def add_signal_to_portfolio(self, signal_data: Dict, entry_price: float = None):
        """Add a new signal to portfolio tracking"""
        try:
            # Check if already tracking this signal
            existing = (
                self.db.query(SignalPortfolio)
                .filter_by(signal_id=signal_data.get('signal_id'))
                .first()
            )
            
            if existing:
                logger.info(f"Signal {signal_data.get('signal_id')} already in portfolio")
                return
            
            # Get entry price if not provided
            if not entry_price:
                async with self.api as api:
                    entry_price = await api.get_token_price_cached(signal_data['token_mint'])
            
            if not entry_price:
                logger.warning(f"Could not get entry price for {signal_data['token_symbol']}")
                return
            
            # Create portfolio entry
            portfolio_entry = SignalPortfolio(
                signal_id=signal_data.get('signal_id'),
                token_mint=signal_data['token_mint'],
                token_symbol=signal_data['token_symbol'],
                wallet_address=signal_data['wallet_address'],
                wallet_tier=signal_data['wallet_tier'],
                recommendation=signal_data['recommendation'],
                signal_score=signal_data['score'],
                entry_price=entry_price,
                entry_time=datetime.utcnow(),
                position_size=100.0,  # Virtual $100 position
                status="OPEN"
            )
            
            self.db.add(portfolio_entry)
            self.db.commit()
            
            logger.info(f"Added {signal_data['token_symbol']} to portfolio tracking")
            
        except Exception as e:
            logger.error(f"Error adding signal to portfolio: {e}")
            self.db.rollback()
    
    async def _generate_portfolio_summary(self):
        """Generate comprehensive portfolio performance summary"""
        try:
            # Get all positions
            all_positions = (
                self.db.query(SignalPortfolio)
                .filter(SignalPortfolio.entry_time >= datetime.utcnow() - timedelta(days=90))
                .all()
            )
            
            if not all_positions:
                return
            
            # Calculate summary statistics
            summary = PortfolioSummary()
            
            # Overall metrics
            summary.total_positions = len(all_positions)
            summary.active_positions = len([p for p in all_positions if p.status == "OPEN"])
            summary.closed_positions = len([p for p in all_positions if p.status in ["CLOSED", "EXPIRED"]])
            
            # Performance metrics for closed positions
            closed_positions = [p for p in all_positions if p.realized_pnl_pct is not None]
            
            if closed_positions:
                returns = [p.realized_pnl_pct for p in closed_positions]
                summary.total_return_pct = sum(returns)
                summary.avg_return_pct = sum(returns) / len(returns)
                summary.win_rate = len([r for r in returns if r > 0]) / len(returns) * 100
                summary.best_return = max(returns)
                summary.worst_return = min(returns)
            
            # Performance by recommendation type
            recommendations = {}
            for rec_type in ['HOT_BUY', 'STRONG_BUY', 'WATCH']:
                rec_positions = [p for p in closed_positions if p.recommendation == rec_type]
                if rec_positions:
                    rec_returns = [p.realized_pnl_pct for p in rec_positions]
                    recommendations[rec_type] = {
                        'count': len(rec_positions),
                        'avg_return': sum(rec_returns) / len(rec_returns),
                        'win_rate': len([r for r in rec_returns if r > 0]) / len(rec_returns) * 100
                    }
            
            summary.performance_by_recommendation = recommendations
            
            # Performance by wallet tier
            tiers = {}
            for tier in ['S', 'A', 'B', 'C']:
                tier_positions = [p for p in closed_positions if p.wallet_tier == tier]
                if tier_positions:
                    tier_returns = [p.realized_pnl_pct for p in tier_positions]
                    tiers[tier] = {
                        'count': len(tier_positions),
                        'avg_return': sum(tier_returns) / len(tier_returns),
                        'win_rate': len([r for r in tier_returns if r > 0]) / len(tier_returns) * 100
                    }
            
            summary.performance_by_tier = tiers
            
            # Save summary
            summary_record = PortfolioSummaryDB(
                total_positions=summary.total_positions,
                active_positions=summary.active_positions,
                closed_positions=summary.closed_positions,
                total_return_pct=summary.total_return_pct,
                avg_return_pct=summary.avg_return_pct,
                win_rate=summary.win_rate,
                best_return=summary.best_return,
                worst_return=summary.worst_return,
                summary_data=str(summary.__dict__),  # Store full summary as JSON string
                created_at=datetime.utcnow()
            )
            
            self.db.add(summary_record)
            self.db.commit()
            
            logger.info(f"Generated portfolio summary: {summary.win_rate:.1f}% win rate, {summary.avg_return_pct:.1f}% avg return")
            
        except Exception as e:
            logger.error(f"Error generating portfolio summary: {e}")
    
    def get_current_portfolio_status(self) -> Dict:
        """Get current portfolio status for reporting"""
        try:
            # Get recent summary
            latest_summary = (
                self.db.query(PortfolioSummaryDB)
                .order_by(PortfolioSummaryDB.created_at.desc())
                .first()
            )
            
            if not latest_summary:
                return {"status": "No portfolio data available"}
            
            # Get top performers
            top_performers = (
                self.db.query(SignalPortfolio)
                .filter(SignalPortfolio.realized_pnl_pct.isnot(None))
                .order_by(SignalPortfolio.realized_pnl_pct.desc())
                .limit(5)
                .all()
            )
            
            # Get worst performers
            worst_performers = (
                self.db.query(SignalPortfolio)
                .filter(SignalPortfolio.realized_pnl_pct.isnot(None))
                .order_by(SignalPortfolio.realized_pnl_pct.asc())
                .limit(5)
                .all()
            )
            
            return {
                "summary": {
                    "total_positions": latest_summary.total_positions,
                    "win_rate": latest_summary.win_rate,
                    "avg_return": latest_summary.avg_return_pct,
                    "best_return": latest_summary.best_return,
                    "worst_return": latest_summary.worst_return
                },
                "top_performers": [
                    {
                        "symbol": p.token_symbol,
                        "return": p.realized_pnl_pct,
                        "days_held": p.days_held,
                        "recommendation": p.recommendation
                    }
                    for p in top_performers
                ],
                "worst_performers": [
                    {
                        "symbol": p.token_symbol,
                        "return": p.realized_pnl_pct,
                        "days_held": p.days_held,
                        "recommendation": p.recommendation
                    }
                    for p in worst_performers
                ]
            }
            
        except Exception as e:
            logger.error(f"Error getting portfolio status: {e}")
            return {"error": "Could not retrieve portfolio status"}

@dataclass
class PortfolioSummary:
    total_positions: int = 0
    active_positions: int = 0
    closed_positions: int = 0
    total_return_pct: float = 0.0
    avg_return_pct: float = 0.0
    win_rate: float = 0.0
    best_return: float = 0.0
    worst_return: float = 0.0
    performance_by_recommendation: Dict = None
    performance_by_tier: Dict = None

# Database models to add to database.py
class SignalPortfolio(Base):
    __tablename__ = 'signal_portfolio'
    
    id = Column(Integer, primary_key=True)
    signal_id = Column(Integer)  # Reference to original signal
    token_mint = Column(String)
    token_symbol = Column(String)
    wallet_address = Column(String)
    wallet_tier = Column(String)
    recommendation = Column(String)
    signal_score = Column(Float)
    
    # Entry data
    entry_price = Column(Float)
    entry_time = Column(DateTime)
    position_size = Column(Float)  # Virtual position size
    
    # Current data
    current_price = Column(Float)
    current_value = Column(Float)
    unrealized_pnl = Column(Float)
    unrealized_pnl_pct = Column(Float)
    days_held = Column(Integer)
    
    # Exit data
    exit_price = Column(Float)
    exit_time = Column(DateTime)
    realized_pnl = Column(Float)
    realized_pnl_pct = Column(Float)
    
    status = Column(String, default="OPEN")  # OPEN, CLOSED, EXPIRED
    last_updated = Column(DateTime, default=datetime.utcnow)

class PortfolioSummaryDB(Base):
    __tablename__ = 'portfolio_summaries'
    
    id = Column(Integer, primary_key=True)
    total_positions = Column(Integer)
    active_positions = Column(Integer)
    closed_positions = Column(Integer)
    total_return_pct = Column(Float)
    avg_return_pct = Column(Float)
    win_rate = Column(Float)
    best_return = Column(Float)
    worst_return = Column(Float)
    summary_data = Column(Text)  # JSON string of full summary
    created_at = Column(DateTime, default=datetime.utcnow)