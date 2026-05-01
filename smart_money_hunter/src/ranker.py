from datetime import datetime
import logging
from database import SmartWallet, get_db

logger = logging.getLogger(__name__)

class WalletRanker:
    def __init__(self):
        self.db = get_db()
    
    def calculate_wallet_score(self, metrics):
        score = 0
        win_rate = metrics.get('win_rate', 0)
        if win_rate >= 80: score += 40
        elif win_rate >= 70: score += 35
        elif win_rate >= 60: score += 25
        elif win_rate >= 50: score += 15
        avg_roi = metrics.get('avg_roi', 0)
        if avg_roi >= 300: score += 25
        elif avg_roi >= 200: score += 20
        elif avg_roi >= 100: score += 15
        elif avg_roi >= 50: score += 10
        timing = metrics.get('timing_score', 0)
        score += min(timing * 0.2, 20)
        consistency = metrics.get('consistency', 0)
        score += min(consistency * 0.15, 15)
        final_score = min(score, 100)
        if final_score >= 90: tier = 'S'
        elif final_score >= 80: tier = 'A'
        elif final_score >= 70: tier = 'B'
        else: tier = 'C'
        return {'score': final_score, 'tier': tier, 'metrics': metrics}
    
    def save_smart_wallet(self, address, ranking):
        try:
            existing = self.db.query(SmartWallet).filter_by(address=address).first()
            if existing:
                existing.score = ranking['score']
                existing.tier = ranking['tier']
                existing.win_rate = ranking['metrics']['win_rate']
                existing.avg_roi = ranking['metrics']['avg_roi']
                existing.total_trades = ranking['metrics']['total_trades']
                existing.timing_score = ranking['metrics']['timing_score']
                existing.consistency = ranking['metrics']['consistency']
                existing.last_updated = datetime.utcnow()
            else:
                wallet = SmartWallet(address=address, score=ranking['score'], tier=ranking['tier'],
                    win_rate=ranking['metrics']['win_rate'], avg_roi=ranking['metrics']['avg_roi'],
                    total_trades=ranking['metrics']['total_trades'], timing_score=ranking['metrics']['timing_score'],
                    consistency=ranking['metrics']['consistency'])
                self.db.add(wallet)
            self.db.commit()
            logger.info(f"Saved wallet {address[:8]}... score {ranking['score']} tier {ranking['tier']}")
        except Exception as e:
            logger.error(f"Error saving wallet {address}: {e}")
            self.db.rollback()
