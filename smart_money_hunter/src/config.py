import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '')
    HELIUS_API_KEY = os.getenv('HELIUS_API_KEY', '')
    BIRDEYE_API_KEY = os.getenv('BIRDEYE_API_KEY', '')
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///smart_money.db')
    
    # Optimized settings for small group
    MIN_SIGNAL_SCORE = 85  # Higher threshold for quality
    MAX_MONITORED_WALLETS = 150
    MONITOR_INTERVAL = 300  # 5 minutes
    DISCOVERY_INTERVAL = 172800  # 2 days
    MIN_WALLET_TRADES = 10
    MIN_WIN_RATE = 60
    MIN_VOLUME_SOL = 1.0  # Minimum trade size
    MAX_SIGNALS_PER_DAY = 10
    
    # API rate limiting
    HELIUS_DAILY_LIMIT = 3000
    BIRDEYE_DAILY_LIMIT = 90
    
    # Caching settings
    PRICE_CACHE_MINUTES = 10
    TOKEN_INFO_CACHE_HOURS = 24

config = Config()

# database.py
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from config import config

Base = declarative_base()
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

class SmartWallet(Base):
    __tablename__ = 'smart_wallets'
    address = Column(String, primary_key=True)
    tier = Column(String)
    score = Column(Float)
    win_rate = Column(Float)
    avg_roi = Column(Float)
    total_trades = Column(Integer)
    timing_score = Column(Float)
    consistency = Column(Float)
    total_volume = Column(Float)
    last_active = Column(DateTime)
    discovered_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow)
    active = Column(Boolean, default=True)

class Transaction(Base):
    __tablename__ = 'transactions'
    id = Column(Integer, primary_key=True)
    wallet_address = Column(String)
    token_mint = Column(String)
    token_symbol = Column(String)
    action = Column(String)  # BUY/SELL
    sol_amount = Column(Float)
    token_amount = Column(Float)
    price_sol = Column(Float)
    timestamp = Column(DateTime)
    signature = Column(String, unique=True)

class Signal(Base):
    __tablename__ = 'signals'
    id = Column(Integer, primary_key=True)
    token_mint = Column(String)
    token_symbol = Column(String)
    score = Column(Integer)
    recommendation = Column(String)
    wallet_address = Column(String)
    wallet_tier = Column(String)
    wallet_score = Column(Float)
    sol_amount = Column(Float)
    similar_wallets = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    sent = Column(Boolean, default=False)

class TelegramUser(Base):
    __tablename__ = 'telegram_users'
    user_id = Column(String, primary_key=True)
    username = Column(String)
    first_name = Column(String)
    joined_at = Column(DateTime, default=datetime.utcnow)
    active = Column(Boolean, default=True)

class APIUsage(Base):
    __tablename__ = 'api_usage'
    id = Column(Integer, primary_key=True)
    service = Column(String)  # helius/birdeye
    date = Column(DateTime)
    calls_made = Column(Integer)

class TokenCache(Base):
    __tablename__ = 'token_cache'
    mint = Column(String, primary_key=True)
    symbol = Column(String)
    name = Column(String)
    price_sol = Column(Float)
    volume_24h = Column(Float)
    market_cap = Column(Float)
    liquidity = Column(Float)
    cached_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)

def get_db():
    return Session()
