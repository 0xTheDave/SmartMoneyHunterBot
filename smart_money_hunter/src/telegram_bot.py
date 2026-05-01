from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from datetime import datetime, timedelta
import asyncio
import logging
from database import SmartWallet, Signal, TelegramUser, get_db
from config import config

logger = logging.getLogger(__name__)

class SmartMoneyTelegramBot:
    def __init__(self):
        if not config.TELEGRAM_TOKEN:
            raise ValueError("TELEGRAM_TOKEN not set in .env file")
        
        self.application = Application.builder().token(config.TELEGRAM_TOKEN).build()
        self.db = get_db()
        self._setup_handlers()
        
        logger.info("Telegram bot initialized")
    
    def _setup_handlers(self):
        """Setup command handlers"""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("top", self.top_wallets_command))
        self.application.add_handler(CommandHandler("signals", self.signals_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("wallet", self.wallet_command))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        
        # Save user to database
        try:
            existing_user = self.db.query(TelegramUser).filter_by(user_id=str(user.id)).first()
            if not existing_user:
                new_user = TelegramUser(
                    user_id=str(user.id),
                    username=user.username or "",
                    first_name=user.first_name or ""
                )
                self.db.add(new_user)
                self.db.commit()
                logger.info(f"New user registered: {user.id}")
            
        except Exception as e:
            logger.error(f"Error saving user: {e}")
            self.db.rollback()
        
        welcome_msg = """
🤖 **Welcome to Smart Money Hunter Bot!**

I track the smartest Solana wallets and notify you of their moves.

**Commands:**
/help - Show all commands
/top - Top performing wallets
/signals - Recent trading signals  
/stats - Bot statistics
/wallet <address> - Analyze specific wallet

Bot is running and monitoring smart wallets 24/7!
        """
        
        await update.message.reply_text(welcome_msg, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = """
📚 **Smart Money Hunter Commands:**

**/start** - Start the bot
**/help** - Show this help message  
**/top** - Show top 10 smart wallets with their scores
**/signals** - Show recent trading signals (last 24h)
**/stats** - Show bot statistics and database info
**/wallet <address>** - Analyze a specific wallet address

**How it works:**
• Bot discovers wallets that consistently make profitable trades
• Ranks them by win rate, ROI, timing, and consistency  
• Monitors their transactions in real-time
• Sends trading signals when they buy tokens

**Wallet Tiers:**
🏆 **S-Tier** (90-100): Elite traders
🥇 **A-Tier** (80-89): Excellent traders  
🥈 **B-Tier** (70-79): Good traders
🥉 **C-Tier** (60-69): Average traders

Stay tuned for trading signals! 📈
        """
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def top_wallets_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /top command - show top wallets"""
        try:
            top_wallets = (self.db.query(SmartWallet)
                         .filter(SmartWallet.active == True)
                         .order_by(SmartWallet.score.desc())
                         .limit(10)
                         .all())
            
            if not top_wallets:
                await update.message.reply_text("No smart wallets found yet. Bot is still discovering...")
                return
            
            message = "🏆 **Top Smart Wallets:**\n\n"
            
            tier_emoji = {'S': '🏆', 'A': '🥇', 'B': '🥈', 'C': '🥉'}
            
            for i, wallet in enumerate(top_wallets, 1):
                emoji = tier_emoji.get(wallet.tier, '📊')
                address_short = f"{wallet.address[:4]}...{wallet.address[-4:]}"
                
                message += f"{emoji} **#{i} - {wallet.tier}-Tier** ({wallet.score:.1f})\n"
                message += f"   `{address_short}`\n"
                message += f"   Win Rate: {wallet.win_rate:.1f}% | ROI: {wallet.avg_roi:.1f}%\n"
                message += f"   Trades: {wallet.total_trades} | Updated: {wallet.last_updated.strftime('%m/%d')}\n\n"
            
            message += f"📊 Total wallets tracked: {len(top_wallets)}"
            
        except Exception as e:
            logger.error(f"Error in top_wallets_command: {e}")
            message = "❌ Error retrieving wallet data. Please try again."
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def signals_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /signals command - show recent signals"""
        try:
            # Get signals from last 24 hours
            since = datetime.utcnow() - timedelta(hours=24)
            recent_signals = (self.db.query(Signal)
                            .filter(Signal.created_at >= since)
                            .order_by(Signal.created_at.desc())
                            .limit(10)
                            .all())
            
            if not recent_signals:
                await update.message.reply_text("📭 No trading signals in the last 24 hours.")
                return
            
            message = "🚨 **Recent Trading Signals (24h):**\n\n"
            
            for signal in recent_signals:
                recommendation_emoji = {
                    'HOT_BUY': '🔥',
                    'STRONG_BUY': '💪', 
                    'WATCH': '👀'
                }.get(signal.recommendation, '📊')
                
                time_ago = datetime.utcnow() - signal.created_at
                if time_ago.seconds < 3600:
                    time_str = f"{time_ago.seconds // 60}m ago"
                else:
                    time_str = f"{time_ago.seconds // 3600}h ago"
                
                message += f"{recommendation_emoji} **{signal.recommendation}** - Score: {signal.score}\n"
                message += f"   Token: `{signal.token_symbol}` | {time_str}\n"
                message += f"   Smart wallets: {signal.smart_wallets_count} | Volume: {signal.total_volume:.1f} SOL\n\n"
            
            message += "💡 Higher scores = stronger signals!"
            
        except Exception as e:
            logger.error(f"Error in signals_command: {e}")
            message = "❌ Error retrieving signals. Please try again."
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command - show bot statistics"""
        try:
            # Count wallets by tier
            total_wallets = self.db.query(SmartWallet).filter(SmartWallet.active == True).count()
            s_tier = self.db.query(SmartWallet).filter(SmartWallet.tier == 'S', SmartWallet.active == True).count()
            a_tier = self.db.query(SmartWallet).filter(SmartWallet.tier == 'A', SmartWallet.active == True).count()
            b_tier = self.db.query(SmartWallet).filter(SmartWallet.tier == 'B', SmartWallet.active == True).count()
            c_tier = self.db.query(SmartWallet).filter(SmartWallet.tier == 'C', SmartWallet.active == True).count()
            
            # Count signals
            today = datetime.utcnow().date()
            signals_today = self.db.query(Signal).filter(
                Signal.created_at >= datetime.combine(today, datetime.min.time())
            ).count()
            
            total_signals = self.db.query(Signal).count()
            
            # Count users
            total_users = self.db.query(TelegramUser).filter(TelegramUser.active == True).count()
            
            # Get average wallet score
            from sqlalchemy import func
            wallets = self.db.query(SmartWallet).filter(SmartWallet.active == True).all()
            if wallets:
                avg_score = sum(w.score for w in wallets) / len(wallets)
            else:
                avg_score = 0
            
            message = f"""
📊 **Smart Money Hunter Statistics:**

**Smart Wallets Tracked:**
🏆 S-Tier: {s_tier} wallets
🥇 A-Tier: {a_tier} wallets  
🥈 B-Tier: {b_tier} wallets
🥉 C-Tier: {c_tier} wallets
📊 **Total: {total_wallets} wallets**

**Trading Signals:**
🚨 Today: {signals_today} signals
📈 All time: {total_signals} signals

**Users:**
👥 Active users: {total_users}

**Performance:**
⭐ Average wallet score: {avg_score:.1f}
🎯 Minimum signal threshold: {config.MIN_SIGNAL_SCORE}

Bot is actively monitoring wallets! 🤖
            """
            
        except Exception as e:
            logger.error(f"Error in stats_command: {e}")
            message = "❌ Error retrieving statistics. Please try again."
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def wallet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /wallet command - analyze specific wallet"""
        if not context.args:
            await update.message.reply_text("Please provide a wallet address.\nUsage: `/wallet <address>`", parse_mode='Markdown')
            return
        
        wallet_address = context.args[0].strip()
        
        if len(wallet_address) < 32:
            await update.message.reply_text("❌ Invalid wallet address format.")
            return
        
        try:
            wallet = self.db.query(SmartWallet).filter_by(address=wallet_address).first()
            
            if wallet:
                tier_emoji = {'S': '🏆', 'A': '🥇', 'B': '🥈', 'C': '🥉'}.get(wallet.tier, '📊')
                
                message = f"""
{tier_emoji} **Smart Wallet Analysis**

**Address:** `{wallet.address[:8]}...{wallet.address[-8:]}`
**Tier:** {wallet.tier} | **Score:** {wallet.score:.1f}/100

**Performance Metrics:**
📊 Win Rate: {wallet.win_rate:.1f}%
💰 Average ROI: {wallet.avg_roi:.1f}%  
🎯 Timing Score: {wallet.timing_score:.1f}/100
🔄 Consistency: {wallet.consistency:.1f}/100
📈 Total Trades: {wallet.total_trades}

**Tracking Info:**
📅 Discovered: {wallet.discovered_at.strftime('%Y-%m-%d')}
🔄 Last Updated: {wallet.last_updated.strftime('%Y-%m-%d %H:%M')}
✅ Status: {"Active" if wallet.active else "Inactive"}

This wallet is being monitored for trading signals! 🚨
                """
            else:
                message = f"""
❌ **Wallet Not Found**

Address `{wallet_address[:8]}...{wallet_address[-8:]}` is not in our smart wallet database.

This could mean:
• Wallet hasn't been discovered yet
• Wallet doesn't meet our performance criteria  
• Address is invalid

The bot discovers new wallets continuously. Check back later! 🔍
                """
        
        except Exception as e:
            logger.error(f"Error in wallet_command: {e}")
            message = "❌ Error analyzing wallet. Please try again."
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def send_signal_notification(self, signal_data: dict):
        """Send trading signal to all users"""
        try:
            users = self.db.query(TelegramUser).filter(TelegramUser.active == True).all()
            
            recommendation_emoji = {
                'HOT_BUY': '🔥',
                'STRONG_BUY': '💪',
                'WATCH': '👀'
            }.get(signal_data['recommendation'], '📊')
            
            message = f"""
{recommendation_emoji} **{signal_data['recommendation']} SIGNAL** - Score: {signal_data['score']}

**Token:** `{signal_data['token_symbol']}`
**Smart Wallet:** {signal_data['wallet_tier']}-Tier ({signal_data['wallet_score']:.1f})
**Amount:** {signal_data['sol_amount']} SOL
**Similar Actions:** {signal_data.get('similar_wallets', 0)} wallets

`{signal_data['wallet_address'][:8]}...{signal_data['wallet_address'][-8:]}`

⏰ {datetime.now().strftime('%H:%M:%S')}
            """
            
            sent_count = 0
            for user in users:
                try:
                    await self.application.bot.send_message(
                        chat_id=user.user_id,
                        text=message,
                        parse_mode='Markdown'
                    )
                    sent_count += 1
                    await asyncio.sleep(0.1)  # Rate limiting
                    
                except Exception as e:
                    logger.error(f"Failed to send message to user {user.user_id}: {e}")
            
            logger.info(f"Signal sent to {sent_count}/{len(users)} users")
            
        except Exception as e:
            logger.error(f"Error sending signal notification: {e}")
    
    async def start_bot(self):
        """Start the telegram bot"""
        logger.info("Starting Telegram bot...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        logger.info("Telegram bot started successfully!")
    
    async def stop_bot(self):
        """Stop the telegram bot"""
        logger.info("Stopping Telegram bot...")
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()
        logger.info("Telegram bot stopped!")