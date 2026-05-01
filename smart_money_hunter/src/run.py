import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("SMH BOT running..")
from main import SmartMoneyHunter

logger.info("SMH BOT running..")

if __name__ == "__main__":
    async def runner():
        bot = SmartMoneyHunter()
        try:
            await bot.start()
        except KeyboardInterrupt:
            logger.info("Stopped by user")
        except Exception as e:
            logger.error(f"Bot error: {e}")
    
    asyncio.run(runner())