import asyncio
import logging
from datetime import datetime, timezone
from discovery import WalletDiscovery
from analyzer import WalletAnalyzer
from ranker import WalletRanker
from monitor import WalletMonitor
from telegram_bot import SmartMoneyTelegramBot
from database import Signal, get_db
from config import config

try:
    from discovery import WalletDiscovery
    from historical_validation import SignalValidator
    from risk_scoring import RiskScoringSystem
    from portfolio_tracking import PortfolioTracker
    from webhook_integration import WebhookManager
    from performance_monitoring import PerformanceMonitor
    ENHANCED_FEATURES = True
except ImportError:
    ENHANCED_FEATURES = False
    logging.info("Running in basic mode")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('smart_money_hunter.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SmartMoneyHunter:
    def __init__(self):
        self.discovery = WalletDiscovery()
        self.analyzer = WalletAnalyzer()
        self.ranker = WalletRanker()
        self.monitor = WalletMonitor()
        self.telegram_bot = SmartMoneyTelegramBot()
        self.db = get_db()
        self.running = False
        
        if ENHANCED_FEATURES:
            self.enhanced_discovery = WalletDiscovery()
            self.signal_validator = SignalValidator()
            self.risk_scorer = RiskScoringSystem()
            self.portfolio_tracker = PortfolioTracker()
            self.webhook_manager = WebhookManager()
            self.performance_monitor = PerformanceMonitor()
            logger.info("Enhanced features enabled")
        else:
            self.enhanced_discovery = None
            self.signal_validator = None
            self.risk_scorer = None
            self.portfolio_tracker = None
            self.webhook_manager = None
            self.performance_monitor = None
        
        logger.info("Smart Money Hunter initialized")
    
    async def discover_and_analyze_wallets(self):
        logger.info("Starting wallet discovery cycle...")
        try:
            if self.enhanced_discovery:
                candidates = await self.enhanced_discovery.discover_smart_wallets()
                logger.info(f"Enhanced discovery found {len(candidates)} candidates")
            else:
                candidates = await self.discovery.discover_smart_wallets()
                logger.info(f"Basic discovery found {len(candidates)} candidates")
            
            analyzed_count = 0
            for wallet_address in candidates:
                try:
                    logger.info(f"Analyzing {wallet_address[:8]}...")
                    metrics = await self.analyzer.analyze_wallet_performance(wallet_address)
                    if metrics and metrics['win_rate'] >= config.MIN_WIN_RATE:
                        ranking = self.ranker.calculate_wallet_score(metrics)
                        if ranking['score'] >= 65:
                            self.ranker.save_smart_wallet(wallet_address, ranking)
                            analyzed_count += 1
                            logger.info(f"Saved {wallet_address[:8]}... Score: {ranking['score']:.1f}")
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.error(f"Error analyzing {wallet_address}: {e}")
                    continue
            logger.info(f"Discovery completed. Analyzed {analyzed_count} wallets")
        except Exception as e:
            logger.error(f"Error in discovery cycle: {e}")
    
    async def monitor_and_signal(self):
        logger.info("Starting monitoring cycle...")
        try:
            today = datetime.now(timezone.utc).date()
            try:
                # Count today's signals - simplified query without missing columns
                todays_signals = self.db.query(Signal).filter(
                    Signal.created_at >= datetime.combine(today, datetime.min.time())
                ).count()
            except Exception as e:
                logger.error(f"Error counting signals: {e}, assuming 0 signals today")
                todays_signals = 0

            if todays_signals >= config.MAX_SIGNALS_PER_DAY:
                logger.info(f"Daily signal limit reached ({todays_signals})")
                return

            signals = await self.monitor.monitor_smart_wallets()

            if signals:
                logger.info(f"Found {len(signals)} quality signals")
                for signal_data in signals[:config.MAX_SIGNALS_PER_DAY - todays_signals]:
                    try:
                        # Create signal with all fields
                        signal = Signal(
                            token_mint=signal_data['token_mint'],
                            token_symbol=signal_data['token_symbol'],
                            score=signal_data['score'],
                            recommendation=signal_data['recommendation'],
                            wallet_address=signal_data.get('wallet_address', ''),
                            wallet_tier=signal_data.get('wallet_tier', ''),
                            wallet_score=signal_data.get('wallet_score', 0.0),
                            sol_amount=signal_data.get('sol_amount', 0.0),
                            similar_wallets=signal_data.get('similar_wallets', 1)
                        )
                        self.db.add(signal)
                        self.db.commit()

                        # Send notification
                        await self.telegram_bot.send_signal_notification(signal_data)
                        logger.info(f"Sent signal: {signal_data['token_symbol']} - {signal_data['recommendation']}")
                        await asyncio.sleep(3)
                    except Exception as e:
                        logger.error(f"Error processing signal: {e}")
                        self.db.rollback()
                        continue
            else:
                logger.info("No quality signals found")
        except Exception as e:
            logger.error(f"Error in monitoring cycle: {e}")
    
    async def validation_cycle(self):
        if not ENHANCED_FEATURES:
            return
        while self.running:
            try:
                logger.info("Starting validation cycle...")
                if self.signal_validator:
                    await self.signal_validator.validate_all_pending_signals()
                if self.portfolio_tracker:
                    await self.portfolio_tracker.track_all_signals()
                if self.performance_monitor:
                    report = await self.performance_monitor.generate_performance_report()
                    if self.webhook_manager and report.get('alerts'):
                        await self.webhook_manager.send_performance_alert({
                            'type': 'PERFORMANCE_REPORT',
                            'alerts': report['alerts'],
                            'summary': report
                        })
                await asyncio.sleep(3600)
            except Exception as e:
                logger.error(f"Error in validation cycle: {e}")
                await asyncio.sleep(3600)
    
    async def start(self):
        logger.info("Starting Smart Money Hunter...")
        self.running = True
        await self.telegram_bot.start_bot()
        logger.info("Running initial discovery...")
        await self.discover_and_analyze_wallets()
        validation_task = None
        if ENHANCED_FEATURES:
            validation_task = asyncio.create_task(self.validation_cycle())
        last_discovery = datetime.now(timezone.utc)
        try:
            while self.running:
                now = datetime.now(timezone.utc)
                await self.monitor_and_signal()
                if (now - last_discovery).total_seconds() >= config.DISCOVERY_INTERVAL:
                    await self.discover_and_analyze_wallets()
                    last_discovery = now
                await asyncio.sleep(config.MONITOR_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Shutdown requested")
        finally:
            if validation_task:
                validation_task.cancel()
            await self.stop()
    
    async def stop(self):
        logger.info("Stopping Smart Money Hunter...")
        self.running = False
        if self.webhook_manager:
            await self.webhook_manager.__aexit__(None, None, None)
        await self.telegram_bot.stop_bot()
        logger.info("Stopped successfully")

if __name__ == "__main__":
    async def main():
        bot = SmartMoneyHunter()
        await bot.start()
    asyncio.run(main())