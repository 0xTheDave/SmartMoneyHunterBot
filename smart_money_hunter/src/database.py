from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from config import config

Base = declarative_base()

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
    total_volume = Column(Float, default=0.0)  # Added with default
    last_active = Column(DateTime, default=datetime.utcnow)  # Added with default
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
    price_sol = Column(Float, default=0.0)  # Added with default
    timestamp = Column(DateTime)
    signature = Column(String, unique=True)

class Signal(Base):
    __tablename__ = 'signals'
    id = Column(Integer, primary_key=True)
    token_mint = Column(String)
    token_symbol = Column(String)
    score = Column(Integer)
    recommendation = Column(String)
    wallet_address = Column(String, default="")  # Added with default
    wallet_tier = Column(String, default="")  # Added with default
    wallet_score = Column(Float, default=0.0)  # Added with default
    sol_amount = Column(Float, default=0.0)  # Added with default
    similar_wallets = Column(Integer, default=1)  # Added with default
    created_at = Column(DateTime, default=datetime.utcnow)
    sent = Column(Boolean, default=False)
    is_successful = Column(Boolean, default=False)  # Added with default
    actual_return_1h = Column(Float, default=0.0)  # Added with default
    actual_return_24h = Column(Float, default=0.0)  # Added with default
    actual_return_7d = Column(Float, default=0.0)  # Added with default
    validated_at = Column(DateTime, default=None)  # Added

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

# Create engine and tables
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

# Drop all tables and recreate them to ensure clean structure
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)

def get_db():
    return Session()