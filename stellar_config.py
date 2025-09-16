# stellar_config.py - Testnet Configuration
import os
from stellar_sdk import Network, Server, SorobanServer
import logging
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Configuração Stellar Testnet
STELLAR_NETWORK = Network.TESTNET_NETWORK_PASSPHRASE
HORIZON_URL = "https://horizon-testnet.stellar.org"
SOROBAN_RPC_URL = "https://soroban-testnet.stellar.org"
NETWORK_PASSPHRASE = Network.TESTNET_NETWORK_PASSPHRASE
FRIENDBOT_URL = "https://friendbot.stellar.org"

# Configurações de conexão
REQUEST_TIMEOUT = int(os.getenv('STELLAR_REQUEST_TIMEOUT', '30'))
MAX_RETRIES = int(os.getenv('STELLAR_MAX_RETRIES', '3'))

# Instâncias dos servidores
server = Server(HORIZON_URL)
soroban_server = SorobanServer(SOROBAN_RPC_URL)

# Configuração do contrato
CONTRACT_ADDRESS = os.getenv('ATHLETE_TOKEN_CONTRACT')
ADMIN_SECRET_KEY = os.getenv('ADMIN_SECRET_KEY')

# Utilitários para testnet
async def fund_account_testnet(public_key: str) -> bool:
    """Financia uma conta na testnet usando o friendbot"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{FRIENDBOT_URL}?addr={public_key}",
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            logger.info(f"Conta financiada com sucesso na testnet: {public_key}")
            return True
    except Exception as e:
        logger.error(f"Falha ao financiar conta {public_key}: {str(e)}")
        return False

def get_testnet_explorer_url(transaction_hash: str = None, account_id: str = None, contract_id: str = None) -> str:
    """Retorna URL do explorer para testnet"""
    base_url = 'https://stellar.expert/explorer/testnet'
    
    if transaction_hash:
        return f"{base_url}/tx/{transaction_hash}"
    elif account_id:
        return f"{base_url}/account/{account_id}"
    elif contract_id:
        return f"{base_url}/contract/{contract_id}"
    else:
        return base_url

async def check_testnet_connection() -> dict:
    """Verifica conexão com os serviços da testnet"""
    results = {}
    
    # Testar Horizon
    try:
        ledger = server.ledgers().limit(1).call()
        results['horizon'] = {
            'connected': True,
            'latest_ledger': ledger['_embedded']['records'][0]['sequence']
        }
    except Exception as e:
        results['horizon'] = {
            'connected': False,
            'error': str(e)
        }
    
    # Testar Soroban RPC
    try:
        health = await soroban_server.get_health()
        results['soroban'] = {
            'connected': True,
            'status': 'healthy'
        }
    except Exception as e:
        results['soroban'] = {
            'connected': False,
            'error': str(e)
        }
    
    return results

# Constantes úteis
STROOPS_PER_XLM = 10_000_000
MIN_ACCOUNT_BALANCE = 1  # XLM mínimo para manter conta ativa
DEFAULT_BASE_FEE = 100  # stroops

logger.info("Configuração Stellar Testnet carregada")