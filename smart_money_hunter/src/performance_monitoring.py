import logging
from datetime import datetime, timedelta
from database import get_db

logger = logging.getLogger(__name__)

class PerformanceMonitor:
    def __init__(self):
        self.db = get_db()
        self.error_count = 0
        self.last_reset = datetime.utcnow()

    def record_error(self):
        """Zapisuje informacje o błędzie."""
        self.error_count += 1
        logger.warning(f"Recorded error. Total errors since last reset: {self.error_count}")

    async def generate_performance_report(self):
        """Generuje prosty raport o wydajności (np. liczba błędów)."""
        elapsed_time = (datetime.utcnow() - self.last_reset).total_seconds() / 3600  # w godzinach
        error_rate = self.error_count / elapsed_time if elapsed_time > 0 else 0

        report = {
            "system": {
                "uptime_hours": elapsed_time,
            },
            "bot_performance": {
                "total_errors": self.error_count,
                "error_rate_per_hour": error_rate,
            },
            "alerts": [
                {"type": "HIGH_ERROR_RATE", "message": f"Error rate: {error_rate:.1f}/hour", "severity": "WARNING"}
                if error_rate > 5 else {}
                for _ in range(1 if error_rate > 5 else 0)
            ]
        }

        logger.info(f"Generated performance report: {report}")
        return report

    def reset_metrics(self):
        """Resetuje liczniki po określonym czasie (np. co 24h)."""
        if (datetime.utcnow() - self.last_reset) >= timedelta(hours=24):
            self.error_count = 0
            self.last_reset = datetime.utcnow()
            logger.info("Performance metrics reset.")

# Przykład użycia (dla testów)
if __name__ == "__main__":
    monitor = PerformanceMonitor()
    monitor.record_error()
    import asyncio
    asyncio.run(monitor.generate_performance_report())