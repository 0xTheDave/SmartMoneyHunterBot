# risk_scoring.py
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
from database import get_db, Signal, SmartWallet
from advanced_filtering import AdvancedFilteringSystem
from social_proof import SocialProofAnalyzer

logger = logging.getLogger(__name__)

class RiskLevel(Enum):
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"

@dataclass
class RiskAssessment:
    signal_id: int
    overall_risk_score: float  # 0-100
    risk_level: RiskLevel
    wallet_risk: float
    token_risk: float
    market_risk: float
    timing_risk: float
    social_proof_strength: float
    risk_factors: List[str]
    confidence: float

class RiskScoringSystem:
    def __init__(self):
        self.db = get_db()
        self.filtering_system = AdvancedFilteringSystem()
        self.social_analyzer = SocialProofAnalyzer()
        
    async def assess_signal_risk(self, signal_data: Dict) -> RiskAssessment:
        """Comprehensive risk assessment for a trading signal"""
        try:
            # Individual risk components
            wallet_risk = await self._assess_wallet_risk(signal_data['wallet_address'])
            token_risk = await self._assess_token_risk(signal_data['token_mint'])
            market_risk = await self._assess_market_risk()
            timing_risk = await self._assess_timing_risk(signal_data)
            social_proof = await self._assess_social_proof_strength(signal_data)
            
            # Calculate overall risk score
            overall_risk = self._calculate_overall_risk(
                wallet_risk, token_risk, market_risk, timing_risk, social_proof
            )
            
            # Determine risk level
            risk_level = self._determine_risk_level(overall_risk)
            
            # Collect risk factors
            risk_factors = self._collect_risk_factors(
                wallet_risk, token_risk, market_risk, timing_risk, social_proof
            )
            
            return RiskAssessment(
                signal_id=signal_data.get('signal_id', 0),
                overall_risk_score=overall_risk,
                risk_level=risk_level,
                wallet_risk=wallet_risk,
                token_risk=token_risk,
                market_risk=market_risk,
                timing_risk=timing_risk,
                social_proof_strength=social_proof,
                risk_factors=risk_factors,
                confidence=0.8
            )
            
        except Exception as e:
            logger.error(f"Error in risk assessment: {e}")
            return self._create_high_risk_assessment(signal_data)
    
    async def _assess_wallet_risk(self, wallet_address: str) -> float:
        """Assess risk based on wallet characteristics"""
        try:
            # Get wallet from database
            wallet = self.db.query(SmartWallet).filter_by(address=wallet_address).first()
            
            if not wallet:
                return 80.0  # High risk for unknown wallet
            
            risk_score = 0.0
            
            # Score based on tier (lower tier = higher risk)
            tier_risk = {'S': 5, 'A': 15, 'B': 30, 'C': 50}.get(wallet.tier, 70)
            risk_score += tier_risk
            
            # Win rate risk (lower win rate = higher risk)
            if wallet.win_rate < 60:
                risk_score += 25
            elif wallet.win_rate < 70:
                risk_score += 15
            elif wallet.win_rate < 80:
                risk_score += 5
            
            # Recent activity risk
            if wallet.last_active:
                days_inactive = (datetime.utcnow() - wallet.last_active).days
                if days_inactive > 7:
                    risk_score += min(days_inactive * 2, 20)
            
            # Check for suspicious patterns
            filter_result = await self.filtering_system.comprehensive_wallet_filter(wallet_address)
            if not filter_result.is_legitimate:
                risk_score += 40
            
            return min(risk_score, 100.0)
            
        except Exception as e:
            logger.error(f"Error assessing wallet risk: {e}")
            return 75.0
    
    async def _assess_token_risk(self, token_mint: str) -> float:
        """Assess risk based on token characteristics"""
        try:
            token_assessment = await self.filtering_system.assess_token_risk(token_mint)
            return token_assessment.risk_score
        except Exception as e:
            logger.error(f"Error assessing token risk: {e}")
            return 70.0
    
    async def _assess_market_risk(self) -> float:
        """Assess overall market conditions risk"""
        # Simplified market risk assessment
        # In production, this would analyze:
        # - Market volatility
        # - SOL price trends
        # - Overall market sentiment
        # - Recent rug pulls / scams
        
        # For now, return moderate risk
        return 40.0
    
    async def _assess_timing_risk(self, signal_data: Dict) -> float:
        """Assess timing-related risks"""
        risk_score = 0.0
        
        # Time of day risk (late night signals might be pump groups)
        current_hour = datetime.utcnow().hour
        if current_hour < 6 or current_hour > 22:  # Very early or very late
            risk_score += 15
        
        # Weekend risk (less liquidity, more manipulation)
        if datetime.utcnow().weekday() >= 5:  # Saturday or Sunday
            risk_score += 10
        
        # Signal frequency risk (too many signals = lower quality)
        today = datetime.utcnow().date()
        signals_today = self.db.query(Signal).filter(
            Signal.created_at >= datetime.combine(today, datetime.min.time())
        ).count()
        
        if signals_today >= 8:
            risk_score += 20
        elif signals_today >= 5:
            risk_score += 10
        
        return min(risk_score, 100.0)
    
    async def _assess_social_proof_strength(self, signal_data: Dict) -> float:
        """Assess strength of social proof (higher = lower risk)"""
        try:
            social_signal = await self.social_analyzer.analyze_social_proof(
                signal_data['token_mint'],
                signal_data['wallet_address'],
                datetime.utcnow()
            )
            
            # Convert confidence score to risk reduction
            return social_signal.confidence_score
            
        except Exception as e:
            logger.error(f"Error assessing social proof: {e}")
            return 20.0  # Low social proof = higher risk
    
    def _calculate_overall_risk(self, wallet_risk: float, token_risk: float, 
                              market_risk: float, timing_risk: float, 
                              social_proof: float) -> float:
        """Calculate weighted overall risk score"""
        
        # Weights for different risk components
        weights = {
            'wallet': 0.35,
            'token': 0.25,
            'market': 0.15,
            'timing': 0.10,
            'social_proof': 0.15
        }
        
        # Social proof reduces risk (inverse relationship)
        social_proof_risk = max(0, 100 - social_proof)
        
        overall_risk = (
            wallet_risk * weights['wallet'] +
            token_risk * weights['token'] +
            market_risk * weights['market'] +
            timing_risk * weights['timing'] +
            social_proof_risk * weights['social_proof']
        )
        
        return min(overall_risk, 100.0)
    
    def _determine_risk_level(self, risk_score: float) -> RiskLevel:
        """Convert numeric risk score to risk level"""
        if risk_score <= 20:
            return RiskLevel.VERY_LOW
        elif risk_score <= 40:
            return RiskLevel.LOW
        elif risk_score <= 60:
            return RiskLevel.MEDIUM
        elif risk_score <= 80:
            return RiskLevel.HIGH
        else:
            return RiskLevel.VERY_HIGH
    
    def _collect_risk_factors(self, wallet_risk: float, token_risk: float, 
                            market_risk: float, timing_risk: float, 
                            social_proof: float) -> List[str]:
        """Collect human-readable risk factors"""
        factors = []
        
        if wallet_risk > 60:
            factors.append("High wallet risk")
        if token_risk > 60:
            factors.append("High token risk")
        if market_risk > 60:
            factors.append("Adverse market conditions")
        if timing_risk > 30:
            factors.append("Suboptimal timing")
        if social_proof < 40:
            factors.append("Weak social proof")
        
        return factors
    
    def _create_high_risk_assessment(self, signal_data: Dict) -> RiskAssessment:
        """Create high-risk assessment for error cases"""
        return RiskAssessment(
            signal_id=signal_data.get('signal_id', 0),
            overall_risk_score=90.0,
            risk_level=RiskLevel.VERY_HIGH,
            wallet_risk=90.0,
            token_risk=90.0,
            market_risk=50.0,
            timing_risk=50.0,
            social_proof_strength=10.0,
            risk_factors=["Risk assessment failed"],
            confidence=0.3
        )