import asyncio
import aiohttp
import logging
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Float
from database import Base, get_db
from database import WebhookLogDB  # Add this import for WebhookLogDB
from database import WebhookConfigDB  # Add this import for WebhookConfigDB
import json

logger = logging.getLogger(__name__)

@dataclass
class WebhookConfig:
    id: str
    url: str
    secret: str
    active: bool
    events: List[str]
    retry_count: int = 3
    timeout: int = 10

class WebhookManager:
    def __init__(self):
        self.db = get_db()
        self.session = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def send_signal_webhook(self, signal_data: Dict):
        payload = {
            "event": "signal_created",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "token_symbol": signal_data['token_symbol'],
                "token_mint": signal_data['token_mint'],
                "recommendation": signal_data['recommendation'],
                "score": signal_data['score'],
                "wallet_address": signal_data['wallet_address'],
                "wallet_tier": signal_data['wallet_tier'],
                "wallet_score": signal_data['wallet_score'],
                "sol_amount": signal_data['sol_amount'],
                "similar_wallets": signal_data.get('similar_wallets', 1),
                "risk_level": signal_data.get('risk_level', 'UNKNOWN')
            }
        }
        await self._send_to_all_webhooks("signal_created", payload)
    
    async def send_portfolio_update(self, portfolio_summary: Dict):
        payload = {
            "event": "portfolio_update",
            "timestamp": datetime.utcnow().isoformat(),
            "data": portfolio_summary
        }
        await self._send_to_all_webhooks("portfolio_update", payload)
    
    async def send_performance_alert(self, alert_data: Dict):
        payload = {
            "event": "performance_alert",
            "timestamp": datetime.utcnow().isoformat(),
            "data": alert_data
        }
        await self._send_to_all_webhooks("performance_alert", payload)
    
    async def _send_to_all_webhooks(self, event_type: str, payload: Dict):
        try:
            webhooks = self._get_active_webhooks(event_type)
            if not webhooks:
                return
            tasks = [self._send_webhook_with_retry(webhook, payload) for webhook in webhooks]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            success_count = sum(1 for r in results if not isinstance(r, Exception))
            logger.info(f"Webhook delivery: {success_count}/{len(webhooks)} successful")
        except Exception as e:
            logger.error(f"Error sending webhooks: {e}")
    
    async def _send_webhook_with_retry(self, webhook: WebhookConfig, payload: Dict) -> bool:
        if not self.session:
            self.session = aiohttp.ClientSession()
        for attempt in range(webhook.retry_count):
            try:
                headers = {
                    'Content-Type': 'application/json',
                    'User-Agent': 'SmartMoneyHunter/1.0',
                    'X-Webhook-Secret': webhook.secret
                }
                async with self.session.post(
                    webhook.url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=webhook.timeout)
                ) as response:
                    if 200 <= response.status < 300:
                        log = WebhookLogDB(
                            webhook_id=webhook.id,
                            event_type=payload["event"],
                            payload=json.dumps(payload),
                            success=True,
                            status_code=response.status,
                            delivered_at=datetime.utcnow()
                        )
                        self.db.add(log)
                        self.db.commit()
                        return True
                    else:
                        log = WebhookLogDB(
                            webhook_id=webhook.id,
                            event_type=payload["event"],
                            payload=json.dumps(payload),
                            success=False,
                            status_code=response.status,
                            delivered_at=datetime.utcnow()
                        )
                        self.db.add(log)
                        self.db.commit()
                        if attempt == webhook.retry_count - 1:
                            return False
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"Webhook attempt {attempt + 1} failed: {e}")
                if attempt == webhook.retry_count - 1:
                    log = WebhookLogDB(
                        webhook_id=webhook.id,
                        event_type=payload["event"],
                        payload=json.dumps(payload),
                        success=False,
                        status_code=0,
                        delivered_at=datetime.utcnow()
                    )
                    self.db.add(log)
                    self.db.commit()
                    return False
                await asyncio.sleep(2 ** attempt)
        return False
    
    def _get_active_webhooks(self, event_type: str) -> List[WebhookConfig]:
        try:
            configs = self.db.query(WebhookConfigDB).filter_by(active=True).all()
            return [WebhookConfig(
                id=c.id,
                url=c.url,
                secret=c.secret,
                active=c.active,
                events=c.events.split(','),
                retry_count=c.retry_count,
                timeout=c.timeout
            ) for c in configs if event_type in c.events.split(',')]
        except Exception as e:
            logger.error(f"Error getting active webhooks: {e}")
            return []