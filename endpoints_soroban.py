# endpoints_soroban.py - Enhanced Version
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from decimal import Decimal
import asyncio
import logging
from contextlib import asynccontextmanager
import redis
from pydantic import BaseModel, validator
import os

from stellar_sdk import Keypair
from soroban_integration import (
    contract_manager, 
    event_listener, 
    setup_enhanced_soroban_integration,
    ContractCallResult,
    xlm_to_stroops,
    stroops_to_xlm
)

from utils import calculate_athlete_valuation
from pydantic_models import (
    CreateAthleteTokenRequest,
    InvestmentRequest,
    RevenueDistribution,
    PerformanceMetrics,
    AthleteData,
    SportType,
    TokenStatus,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Security
security = HTTPBearer()

# Redis for caching (fallback to in-memory if not available)
try:
    redis_client = redis.Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        decode_responses=True
    )
    redis_client.ping()
    REDIS_AVAILABLE = True
except:
    REDIS_AVAILABLE = False
    logger.warning("Redis not available, using in-memory cache")

# Cache implementations
class CacheManager:
    def __init__(self):
        self.memory_cache = {}
        self.redis_client = redis_client if REDIS_AVAILABLE else None
    
    async def get(self, key: str) -> Optional[dict]:
        if self.redis_client:
            try:
                data = self.redis_client.get(key)
                return json.loads(data) if data else None
            except Exception as e:
                logger.warning(f"Redis get error: {e}")
        
        return self.memory_cache.get(key)
    
    async def set(self, key: str, value: dict, ttl: int = 3600):
        if self.redis_client:
            try:
                self.redis_client.setex(key, ttl, json.dumps(value, default=str))
            except Exception as e:
                logger.warning(f"Redis set error: {e}")
        
        self.memory_cache[key] = value
    
    async def delete(self, key: str):
        if self.redis_client:
            try:
                self.redis_client.delete(key)
            except Exception as e:
                logger.warning(f"Redis delete error: {e}")
        
        self.memory_cache.pop(key, None)
    
    async def get_pattern(self, pattern: str) -> Dict[str, dict]:
        results = {}
        
        if self.redis_client:
            try:
                keys = self.redis_client.keys(pattern)
                for key in keys:
                    data = self.redis_client.get(key)
                    if data:
                        results[key] = json.loads(data)
            except Exception as e:
                logger.warning(f"Redis pattern get error: {e}")
        
        # Fallback to memory cache
        for key, value in self.memory_cache.items():
            if pattern.replace('*', '') in key:
                results[key] = value
        
        return results

cache_manager = CacheManager()

# Enhanced Request Models
class InvestmentRequestEnhanced(BaseModel):
    token_id: str
    amount_xlm: Decimal
    investor_public_key: str  # Public key only for security
    
    @validator('amount_xlm')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('Investment amount must be positive')
        if v < Decimal('10'):  # Minimum investment
            raise ValueError('Minimum investment is 10 XLM')
        return v
    
    @validator('investor_public_key')
    def validate_public_key(cls, v):
        try:
            Keypair.from_public_key(v)
        except:
            raise ValueError('Invalid Stellar public key')
        return v

class TokenActivationRequest(BaseModel):
    min_investment: Optional[Decimal] = Decimal('10.0')
    early_bird_discount: Optional[Decimal] = None
    
    @validator('min_investment')
    def validate_min_investment(cls, v):
        if v and v < Decimal('1'):
            raise ValueError('Minimum investment must be at least 1 XLM')
        return v

# Dependency for authentication (placeholder - implement based on your auth system)
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Validate JWT token and return user info"""
    # Implement your authentication logic here
    # For now, returning a mock user
    return {"user_id": "mock_user", "role": "admin"}

# Dependency for rate limiting
class RateLimiter:
    def __init__(self, max_requests: int = 100, window_seconds: int = 3600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = {}
    
    async def check_rate_limit(self, identifier: str):
        now = datetime.now()
        window_start = now - timedelta(seconds=self.window_seconds)
        
        if identifier not in self.requests:
            self.requests[identifier] = []
        
        # Clean old requests
        self.requests[identifier] = [
            req_time for req_time in self.requests[identifier] 
            if req_time > window_start
        ]
        
        if len(self.requests[identifier]) >= self.max_requests:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded"
            )
        
        self.requests[identifier].append(now)

rate_limiter = RateLimiter()

# Router setup
router = APIRouter()

@router.on_event("startup")
async def startup_event():
    """Configure Soroban on initialization"""
    try:
        result = await setup_enhanced_soroban_integration()
        logger.info(f"Startup completed: {result}")
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise

@router.on_event("shutdown")
async def shutdown_event():
    """Clean resources on shutdown"""
    try:
        await event_listener.stop_listening()
        logger.info("Shutdown completed successfully")
    except Exception as e:
        logger.error(f"Shutdown error: {e}")

@router.get("/")
async def root():
    """API root with system information"""
    return {
        "message": "SportToken API - Athlete Tokenization with Soroban",
        "version": "2.1.0",
        "blockchain": "Stellar with Soroban Smart Contracts",
        "contract_address": contract_manager.contract_address,
        "features": {
            "smart_contracts": True,
            "real_time_events": True,
            "revenue_distribution": True,
            "performance_tracking": True
        }
    }

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Test contract connection
        test_result = await contract_manager.get_token_info("test")
        
        return {
            "status": "healthy",
            "blockchain_connected": True,
            "contract_responsive": True,
            "cache_available": REDIS_AVAILABLE,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "degraded",
            "blockchain_connected": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@router.post("/athletes/create-token")
async def create_athlete_token(
    request: CreateAthleteTokenRequest, 
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """Create a new token for an athlete using Soroban"""
    
    try:
        # Rate limiting
        await rate_limiter.check_rate_limit(current_user["user_id"])
        
        # Generate keypairs for the issuer (in production, use secure key management)
        issuer_keypair = Keypair.random()
        
        # Calculate athlete valuation
        athlete_valuation = calculate_athlete_valuation(
            request.athlete_data, 
            request.performance_metrics
        )
        
        # Calculate adjusted price based on valuation
        valuation_multiplier = max(0.5, min(2.0, athlete_valuation / 50.0))  # Cap between 0.5x and 2x
        adjusted_price = request.tokenomics.price_per_token * Decimal(str(valuation_multiplier))
        
        # Create token in Soroban contract
        contract_result = await contract_manager.create_athlete_token(
            athlete_data=request.athlete_data,
            total_supply=request.tokenomics.total_supply,
            price_per_token=adjusted_price,
            issuer_keypair=issuer_keypair
        )
        
        if not contract_result.success:
            raise HTTPException(
                status_code=400, 
                detail=f"Contract error: {contract_result.error_message}"
            )
        
        token_id = contract_result.result_data["token_id"]
        
        # Prepare token data for cache
        token_data = {
            "id": token_id,
            "athlete_data": request.athlete_data.dict(),
            "performance_metrics": request.performance_metrics.dict(),
            "tokenomics": request.tokenomics.dict(),
            "athlete_valuation": athlete_valuation,
            "adjusted_price_per_token": float(adjusted_price),
            "funding_goal": float(request.funding_goal),
            "campaign_duration_days": request.campaign_duration_days,
            "issuer_public_key": issuer_keypair.public_key,
            # DON'T store secret key in cache for security
            "status": TokenStatus.DRAFT,
            "created_at": datetime.now().isoformat(),
            "campaign_end_date": (datetime.now() + timedelta(days=request.campaign_duration_days)).isoformat(),
            "contract_token_id": token_id,
            "blockchain_created": True,
            "created_by": current_user["user_id"],
            "valuation_multiplier": valuation_multiplier
        }
        
        # Store in cache
        await cache_manager.set(f"token:{token_id}", token_data)
        
        # Store issuer key securely (implement proper key management)
        await cache_manager.set(
            f"token:key:{token_id}", 
            {"issuer_secret": issuer_keypair.secret},
            ttl=86400  # 24 hours
        )
        
        # Update performance in background
        background_tasks.add_task(
            update_performance_in_background,
            token_id,
            request.performance_metrics
        )
        
        logger.info(f"Token created successfully: {token_id} by user {current_user['user_id']}")
        
        return {
            "token_id": token_id,
            "athlete_name": request.athlete_data.name,
            "token_symbol": contract_result.result_data["token_symbol"],
            "athlete_valuation": athlete_valuation,
            "adjusted_price_per_token": float(adjusted_price),
            "valuation_multiplier": valuation_multiplier,
            "issuer_address": issuer_keypair.public_key,
            "contract_address": contract_manager.contract_address,
            "blockchain_transaction": contract_result.transaction_hash,
            "status": "created",
            "message": "Token created successfully on blockchain! Next step: activate token to start campaign."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating token: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating token: {str(e)}")

@router.post("/tokens/{token_id}/activate")
async def activate_token(
    token_id: str, 
    request: TokenActivationRequest = TokenActivationRequest(),
    current_user: dict = Depends(get_current_user)
):
    """Activate a token to allow investments by creating a campaign"""
    
    token_data = await cache_manager.get(f"token:{token_id}")
    if not token_data:
        raise HTTPException(status_code=404, detail="Token not found")
    
    if token_data["status"] != TokenStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Token already activated or finalized")
    
    # Check ownership (in production, implement proper authorization)
    if token_data.get("created_by") != current_user["user_id"] and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to activate this token")
    
    try:
        # Create campaign in Soroban contract
        contract_result = await contract_manager.create_campaign(
            token_id=token_id,
            funding_goal=Decimal(str(token_data["funding_goal"])),
            duration_days=token_data["campaign_duration_days"],
            min_investment=request.min_investment
        )
        
        if not contract_result.success:
            raise HTTPException(
                status_code=400, 
                detail=f"Error creating campaign: {contract_result.error_message}"
            )
        
        # Update cache
        token_data["status"] = TokenStatus.ACTIVE
        token_data["campaign_transaction"] = contract_result.transaction_hash
        token_data["min_investment"] = float(request.min_investment)
        token_data["activated_at"] = datetime.now().isoformat()
        
        await cache_manager.set(f"token:{token_id}", token_data)
        
        # Cache campaign data
        campaign_data = {
            "token_id": token_id,
            "funding_goal": contract_result.result_data["funding_goal"],
            "duration_days": contract_result.result_data["duration_days"],
            "min_investment": contract_result.result_data["min_investment"],
            "total_raised": 0.0,
            "tokens_sold": 0,
            "investors_count": 0,
            "blockchain_created": True
        }
        
        await cache_manager.set(f"campaign:{token_id}", campaign_data)
        
        logger.info(f"Token activated: {token_id}")
        
        return {
            "token_id": token_id,
            "status": "active",
            "campaign_transaction": contract_result.transaction_hash,
            "funding_goal": contract_result.result_data["funding_goal"],
            "min_investment": float(request.min_investment),
            "message": "Token activated successfully on blockchain! Now accepting investments."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error activating token {token_id}: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error activating token: {str(e)}")

@router.get("/tokens")
async def list_tokens(
    sport: Optional[SportType] = None, 
    status: Optional[TokenStatus] = None,
    limit: int = 50,
    offset: int = 0
):
    """List all available tokens with blockchain data"""
    
    try:
        # Get all token keys from cache
        all_tokens = await cache_manager.get_pattern("token:*")
        
        filtered_tokens = []
        
        for cache_key, token_data in all_tokens.items():
            # Skip non-token keys (like token:key:*)
            if ":key:" in cache_key:
                continue
                
            # Apply filters
            if sport and token_data.get("athlete_data", {}).get("sport") != sport:
                continue
                
            if status and token_data.get("status") != status:
                continue
            
            # Try to get updated data from contract
            token_id = token_data.get("id") or token_data.get("contract_token_id")
            if not token_id:
                continue
            
            try:
                contract_token_info = await contract_manager.get_token_info(token_id)
                contract_campaign_info = await contract_manager.get_campaign_info(token_id)
                
                blockchain_verified = contract_token_info.success
                
                # Use contract data if available, otherwise fall back to cache
                total_raised = 0
                investors_count = 0
                
                if contract_campaign_info.success and contract_campaign_info.result_data:
                    campaign_data = contract_campaign_info.result_data
                    total_raised = stroops_to_xlm(campaign_data.get("total_raised", 0))
                    investors_count = campaign_data.get("investors_count", 0)
                
            except Exception as e:
                logger.warning(f"Error fetching contract data for token {token_id}: {e}")
                blockchain_verified = False
                total_raised = token_data.get("total_raised", 0)
                investors_count = token_data.get("investors_count", 0)
            
            filtered_token = {
                "token_id": token_id,
                "athlete_name": token_data.get("athlete_data", {}).get("name", "Unknown"),
                "sport": token_data.get("athlete_data", {}).get("sport", "Unknown"),
                "athlete_valuation": token_data.get("athlete_valuation", 0),
                "price_per_token": token_data.get("adjusted_price_per_token", 0),
                "funding_goal": token_data.get("funding_goal", 0),
                "total_raised": float(total_raised),
                "investors_count": investors_count,
                "status": token_data.get("status", "unknown"),
                "campaign_end_date": token_data.get("campaign_end_date"),
                "blockchain_verified": blockchain_verified,
                "created_at": token_data.get("created_at")
            }
            
            filtered_tokens.append(filtered_token)
        
        # Sort by creation date (newest first)
        filtered_tokens.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        # Apply pagination
        total_count = len(filtered_tokens)
        paginated_tokens = filtered_tokens[offset:offset + limit]
        
        return {
            "tokens": paginated_tokens,
            "pagination": {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_next": offset + limit < total_count
            },
            "blockchain_integration": True
        }
        
    except Exception as e:
        logger.error(f"Error listing tokens: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving tokens")

@router.get("/tokens/{token_id}")
async def get_token_details(token_id: str):
    """Get complete token details from blockchain"""
    
    token_data = await cache_manager.get(f"token:{token_id}")
    if not token_data:
        raise HTTPException(status_code=404, detail="Token not found")
    
    try:
        # Fetch updated data from contract
        contract_token_info = await contract_manager.get_token_info(token_id)
        contract_campaign_info = await contract_manager.get_campaign_info(token_id)
        
        # Merge cache data with contract data
        response_data = {
            **token_data,
            "blockchain_data": {
                "token_info": contract_token_info.result_data if contract_token_info.success else None,
                "campaign_info": contract_campaign_info.result_data if contract_campaign_info.success else None,
                "blockchain_verified": contract_token_info.success
            }
        }
        
        # Use contract data as primary source if available
        if contract_campaign_info.success and contract_campaign_info.result_data:
            campaign_data = contract_campaign_info.result_data
            response_data["total_raised"] = float(stroops_to_xlm(campaign_data.get("total_raised", 0)))
            response_data["tokens_sold"] = campaign_data.get("tokens_sold", 0)
            response_data["investors_count"] = campaign_data.get("investors_count", 0)
        
        # Remove sensitive data
        response_data.pop("issuer_secret", None)
        
        return response_data
        
    except Exception as e:
        logger.warning(f"Error fetching contract data for token {token_id}: {e}")
        # Return cache data without sensitive information
        safe_data = {k: v for k, v in token_data.items() if k != "issuer_secret"}
        return safe_data

@router.post("/investments/invest")
async def invest_in_athlete(
    investment: InvestmentRequestEnhanced,
    current_user: dict = Depends(get_current_user)
):
    """Allow an investor to buy tokens using Soroban"""
    
    token_data = await cache_manager.get(f"token:{investment.token_id}")
    if not token_data:
        raise HTTPException(status_code=404, detail="Token not found")
    
    if token_data["status"] != TokenStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Token not active for investments")
    
    # Rate limiting
    await rate_limiter.check_rate_limit(f"invest:{current_user['user_id']}")
    
    try:
        # Create keypair from public key (investor must provide their own keypair)
        # In production, implement proper key management/signing
        investor_keypair = Keypair.from_public_key(investment.investor_public_key)
        
        # Validate minimum investment
        min_investment = Decimal(str(token_data.get("min_investment", 10)))
        if investment.amount_xlm < min_investment:
            raise HTTPException(
                status_code=400, 
                detail=f"Minimum investment is {min_investment} XLM"
            )
        
        # Investment through Soroban contract
        contract_result = await contract_manager.invest_in_token(
            investor_keypair=investor_keypair,
            token_id=investment.token_id,
            xlm_amount=investment.amount_xlm
        )
        
        if not contract_result.success:
            raise HTTPException(
                status_code=400, 
                detail=f"Investment error: {contract_result.error_message}"
            )
        
        # Fetch updated campaign data
        campaign_info = await contract_manager.get_campaign_info(investment.token_id)
        
        if campaign_info.success and campaign_info.result_data:
            # Update campaign cache
            await cache_manager.set(f"campaign:{investment.token_id}", campaign_info.result_data)
            
            # Check if funding goal reached
            total_raised = stroops_to_xlm(campaign_info.result_data.get("total_raised", 0))
            funding_goal = Decimal(str(token_data["funding_goal"]))
            
            if total_raised >= funding_goal:
                token_data["status"] = TokenStatus.COMPLETED
                await cache_manager.set(f"token:{investment.token_id}", token_data)
        
        # Calculate tokens purchased (approximation)
        price_per_token = Decimal(str(token_data["adjusted_price_per_token"]))
        tokens_purchased_approx = int(investment.amount_xlm / price_per_token)
        
        logger.info(f"Investment processed: {investment.amount_xlm} XLM in token {investment.token_id}")
        
        return {
            "transaction_hash": contract_result.transaction_hash,
            "tokens_purchased": tokens_purchased_approx,
            "total_cost_xlm": float(investment.amount_xlm),
            "investor_address": investment.investor_public_key,
            "blockchain_confirmed": True,
            "timestamp": datetime.now().isoformat(),
            "message": "Investment processed successfully on blockchain!"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing investment: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error processing investment: {str(e)}")

# Background task for performance updates
async def update_performance_in_background(token_id: str, metrics: PerformanceMetrics):
    """Background task to update performance metrics"""
    try:
        await asyncio.sleep(2)  # Small delay to ensure token is fully created
        
        result = await contract_manager.update_performance_metrics(token_id, metrics)
        
        if result.success:
            logger.info(f"Performance updated for token {token_id}")
        else:
            logger.error(f"Failed to update performance for token {token_id}: {result.error_message}")
            
    except Exception as e:
        logger.error(f"Background performance update failed for token {token_id}: {str(e)}")

# Additional endpoints would follow similar patterns...

@router.post("/revenue/distribute")
async def distribute_revenue(
    revenue: RevenueDistribution,
    current_user: dict = Depends(get_current_user)
):
    """Distribute revenue to token holders using Soroban"""
    
    if not await cache_manager.get(f"token:{revenue.token_id}"):
        raise HTTPException(status_code=404, detail="Token not found")
    
    # Rate limiting for revenue distribution
    await rate_limiter.check_rate_limit(f"revenue:{current_user['user_id']}")
    
    try:
        contract_result = await contract_manager.distribute_revenue(
            token_id=revenue.token_id,
            total_amount=revenue.revenue_amount,
            source=revenue.source
        )
        
        if not contract_result.success:
            raise HTTPException(
                status_code=400, 
                detail=f"Distribution error: {contract_result.error_message}"
            )
        
        logger.info(f"Revenue distributed for token {revenue.token_id}: {revenue.revenue_amount} XLM")
        
        return {
            "distribution_id": f"dist_{int(datetime.now().timestamp())}",
            "transaction_hash": contract_result.transaction_hash,
            "total_revenue": float(revenue.revenue_amount),
            "source": revenue.source,
            "blockchain_confirmed": True,
            "timestamp": datetime.now().isoformat(),
            "message": "Revenue distributed successfully on blockchain!"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error distributing revenue: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error distributing revenue: {str(e)}")