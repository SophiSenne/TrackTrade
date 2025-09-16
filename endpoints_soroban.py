from fastapi import APIRouter, HTTPException, status
from typing import Optional
import logging
from datetime import datetime
from pydantic import BaseModel, validator
from stellar_sdk import StrKey, Keypair, Address
from stellar_sdk.exceptions import Ed25519PublicKeyInvalidError

from soroban_integration import contract_manager

# Configure o logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuração do Router
router = APIRouter()

@router.on_event("startup")
async def startup_event():
    """Configura o Soroban na inicialização"""
    try:
        result = await contract_manager.setup()
        logger.info(f"Inicialização concluída: {result}")
    except Exception as e:
        logger.error(f"Falha na inicialização: {e}")
        raise

@router.on_event("shutdown")
async def shutdown_event():
    """Limpa recursos ao desligar"""
    logger.info("Desligamento concluído com sucesso")

@router.get("/")
async def root():
    """Raiz da API com informações do sistema"""
    return {
        "message": "Athlete Token API com Soroban",
        "version": "1.0.1",
        "blockchain": "Stellar com Smart Contracts Soroban",
        "contract_address": contract_manager.contract_address,
    }

@router.get("/health")
async def health_check():
    """Endpoint de verificação de saúde do serviço"""
    try:
        # Tenta obter o saldo da conta admin do contrato para testar a responsividade
        admin_address = contract_manager.admin_keypair.public_key
        await contract_manager.balance(admin_address)
        
        return {
            "status": "healthy",
            "blockchain_connected": True,
            "contract_responsive": True,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Verificação de saúde falhou: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "degraded",
                "blockchain_connected": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
        )

class MintRequest(BaseModel):
    to_address: str
    amount: int

    @validator("to_address")
    def validate_to_address(cls, v):
        v = v.strip()
        # Valida tanto chaves públicas (G...) quanto IDs de contrato (C...)
        if v.startswith("G"):
            if not StrKey.is_valid_ed25519_public_key(v):
                raise ValueError("Chave pública Stellar inválida para o destinatário")
        elif v.startswith("C"):
            if not StrKey.is_valid_contract_id(v):
                raise ValueError("ID de contrato Soroban inválido")
        else:
            raise ValueError("O endereço deve começar com 'G' (conta) ou 'C' (contrato)")
        return v

    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('A quantidade para mintar deve ser positiva')
        return v

class TransferRequest(BaseModel):
    from_address: str
    to_address: str
    amount: int

    @validator('from_address', 'to_address')
    def validate_addresses(cls, v):
        if not StrKey.is_valid_ed25519_public_key(v):
            raise ValueError('Endereço Stellar (chave pública) inválido')
        return v

    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('A quantidade para transferir deve ser positiva')
        return v

@router.get("/balance/{owner_address}")
async def get_balance(owner_address: str):
    """Obtém o saldo de tokens de um endereço"""
    if not StrKey.is_valid_ed25519_public_key(owner_address):
        raise HTTPException(status_code=400, detail="Formato de chave pública Stellar inválido")

    try:
        result = await contract_manager.balance(owner_address)
        
        if result.success:
            balance_data = result.result_data
            balance_value = balance_data.get('balance', 0)
            
            logger.info(f"Saldo de {owner_address}: {balance_value}")
            return {"owner_address": owner_address, "balance": balance_value}
        else:
            error_msg = result.error_message or 'Erro desconhecido'
            logger.error(f"Consulta de saldo falhou para {owner_address}: {error_msg}")
            raise HTTPException(status_code=400, detail=f"Falha ao obter saldo: {error_msg}")
            
    except Exception as e:
        logger.error(f"Erro inesperado ao obter saldo para {owner_address}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao recuperar saldo: {str(e)}")

@router.post("/mint", status_code=status.HTTP_201_CREATED)
async def mint_tokens(request: MintRequest):
    """Cunha (mint) novos tokens para um endereço especificado"""
    try:
        logger.info(f"Tentando mintar {request.amount} tokens para {request.to_address}")
        
        # A função `mint` agora aceita o endereço como string
        result = await contract_manager.mint(request.to_address, request.amount)
        
        if result.success:
            logger.info(f"Mint de {request.amount} tokens para {request.to_address} bem-sucedido")
            return {
                "message": "Tokens mintados com sucesso",
                "to_address": request.to_address,
                "amount": request.amount,
                "transaction_hash": result.transaction_hash
            }
        else:
            error_msg = result.error_message or 'Erro desconhecido na cunhagem'
            logger.error(f"Falha na cunhagem: {error_msg}")
            raise HTTPException(status_code=400, detail=f"Falha na cunhagem: {error_msg}")
            
    except Exception as e:
        logger.error(f"Erro inesperado ao mintar tokens: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao mintar tokens: {str(e)}")

@router.post("/transfer")
async def transfer_tokens(request: TransferRequest):
    """Transfere tokens de um endereço para outro"""
    try:
        logger.info(f"Tentando transferir {request.amount} tokens de {request.from_address} para {request.to_address}")
        
        result = await contract_manager.transfer(request.from_address, request.to_address, request.amount)
        
        if result.success:
            logger.info(f"Transferência de {request.amount} tokens de {request.from_address} para {request.to_address} bem-sucedida")
            return {
                "message": "Tokens transferidos com sucesso",
                "from_address": request.from_address,
                "to_address": request.to_address,
                "amount": request.amount,
                "transaction_hash": result.transaction_hash
            }
        else:
            error_msg = result.error_message or 'Erro desconhecido na transferência'
            logger.error(f"Falha na transferência: {error_msg}")
            raise HTTPException(status_code=400, detail=f"Falha na transferência: {error_msg}")
            
    except Exception as e:
        logger.error(f"Erro inesperado ao transferir tokens: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao transferir tokens: {str(e)}")