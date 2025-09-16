# endpoints_soroban.py - Athlete Token API with Soroban

from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict
import logging
from datetime import datetime
from pydantic import BaseModel, validator

from stellar_sdk import Keypair
from soroban_integration import (
    contract_manager, 
    setup_enhanced_soroban_integration,
    ContractCallResult
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Security
security = HTTPBearer()

# Dependency for authentication (placeholder - implement based on your auth system)
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Validate JWT token and return user info"""
    # Implement your authentication logic here
    # For now, returning a mock user
    return {"user_id": "mock_user", "role": "admin"}

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
    logger.info("Shutdown completed successfully")

@router.get("/")
async def root():
    """API root with system information"""
    return {
        "message": "Athlete Token API with Soroban",
        "version": "1.0.0",
        "blockchain": "Stellar with Soroban Smart Contracts",
        "contract_address": contract_manager.contract_address,
        "features": {
            "balance": True,
            "mint": True,
            "transfer": True
        }
    }

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Attempt to get balance of a dummy address to test contract responsiveness
        dummy_address = "GBDXN2P3D5S74W5YJKK425O332U2CBA2O4WJ4R4O3P4F4C4V4K4L4I4"
        await contract_manager.balance(dummy_address)
        
        return {
            "status": "healthy",
            "blockchain_connected": True,
            "contract_responsive": True,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "degraded",
            "blockchain_connected": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


class MintRequest(BaseModel):
    to_address: str
    amount: int

    @validator('to_address')
    def validate_to_address(cls, v):
        try:
            Keypair.from_public_key(v)
        except:
            raise ValueError('Invalid Stellar public key for recipient')
        return v

    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('Amount to mint must be positive')
        return v


class TransferRequest(BaseModel):
    from_address: str
    to_address: str
    amount: int

    @validator('from_address', 'to_address')
    def validate_addresses(cls, v):
        try:
            Keypair.from_public_key(v)
        except:
            raise ValueError('Invalid Stellar public key')
        return v

    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('Amount to transfer must be positive')
        return v


@router.get("/balance/{owner_address}")
async def get_balance(
    owner_address: str,
    current_user: dict = Depends(get_current_user)
):
    """Get the token balance of an owner address"""
    try:
        # Validate owner_address
        Keypair.from_public_key(owner_address)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid owner public key")

    try:
        result = await contract_manager.balance(owner_address)
        if result.success:
            # The balance function returns a raw i128. Convert to float for API consistency.
            balance_value = float(result.result_data.get("decoded_value", 0))
            logger.info(f"Balance of {owner_address}: {balance_value}")
            return {"owner_address": owner_address, "balance": balance_value}
        else:
            raise HTTPException(status_code=400, detail=f"Failed to get balance: {result.error_message}")
    except Exception as e:
        logger.error(f"Error getting balance for {owner_address}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving balance: {str(e)}")


@router.post("/mint")
async def mint_tokens(
    request: MintRequest,
    current_user: dict = Depends(get_current_user)
):
    """Mint new tokens to a specified address"""
    # In a real application, implement proper authorization for minting
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can mint tokens")

    try:
        result = await contract_manager.mint(request.to_address, request.amount)
        if result.success:
            logger.info(f"Minted {request.amount} tokens to {request.to_address}")
            return {
                "message": "Tokens minted successfully",
                "to_address": request.to_address,
                "amount": request.amount,
                "transaction_hash": result.transaction_hash
            }
        else:
            raise HTTPException(status_code=400, detail=f"Minting failed: {result.error_message}")
    except Exception as e:
        logger.error(f"Error minting tokens: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error minting tokens: {str(e)}")


@router.post("/transfer")
async def transfer_tokens(
    request: TransferRequest,
    current_user: dict = Depends(get_current_user)
):
    """Transfer tokens from one address to another"""
    # In a real application, ensure the 'from_address' is authorized to transfer
    # For simplicity, using admin to sign, but a user's keypair should be used for 'from_address'
    if current_user["user_id"] != "mock_user" and current_user["role"] != "admin": # Simplified auth check
         # Here you would typically verify the `from_address` somehow, e.g. with a signature
        raise HTTPException(status_code=403, detail="Not authorized to transfer from this address")

    try:
        result = await contract_manager.transfer(request.from_address, request.to_address, request.amount)
        if result.success:
            logger.info(f"Transferred {request.amount} tokens from {request.from_address} to {request.to_address}")
            return {
                "message": "Tokens transferred successfully",
                "from_address": request.from_address,
                "to_address": request.to_address,
                "amount": request.amount,
                "transaction_hash": result.transaction_hash
            }
        else:
            raise HTTPException(status_code=400, detail=f"Transfer failed: {result.error_message}")
    except Exception as e:
        logger.error(f"Error transferring tokens: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error transferring tokens: {str(e)}")