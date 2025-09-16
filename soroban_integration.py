import asyncio
from typing import Dict, Optional, List, Any
import logging
from dataclasses import dataclass
from dotenv import load_dotenv
import os

from stellar_sdk import (
    Server, Keypair, Network, TransactionBuilder, 
    SorobanServer, scval, xdr as stellar_xdr
)

# Carrega variáveis de ambiente do .env
load_dotenv()

# Configure o logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurações da rede Stellar
HORIZON_URL = os.getenv("HORIZON_URL", "https://horizon-testnet.stellar.org")
SOROBAN_RPC_URL = os.getenv("SOROBAN_RPC_URL", "https://soroban-testnet.stellar.org:443")
NETWORK_PASSPHRASE = os.getenv("NETWORK_PASSPHRASE", Network.TESTNET_NETWORK_PASSPHRASE)

# Constantes
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2

@dataclass
class ContractCallResult:
    """Estrutura para o resultado de chamadas de contrato"""
    success: bool
    transaction_hash: Optional[str] = None
    result_data: Optional[Any] = None
    error_message: Optional[str] = None

class ContractError(Exception):
    """Exceção customizada para erros de contrato"""
    pass

class SorobanContractManager:
    """Gerenciador para interagir com o contrato Soroban"""
    
    def __init__(self, contract_address: str, admin_keypair: Keypair):
        if not contract_address or not admin_keypair:
            raise ValueError("Endereço do contrato e keypair do admin são obrigatórios")
        self.contract_address = contract_address
        self.admin_keypair = admin_keypair
        self.horizon_server = Server(HORIZON_URL)
        self.soroban_server = SorobanServer(SOROBAN_RPC_URL)
        self.network_passphrase = NETWORK_PASSPHRASE
        logger.info(f"Gerenciador de Contrato Soroban inicializado para {contract_address}")

    async def _execute_contract_function(
        self, 
        function_name: str, 
        args: List, 
        signer_keypair: Keypair,
        read_only: bool = False
    ) -> ContractCallResult:
        """Motor central para executar funções de contrato (leitura e escrita)"""
        for attempt in range(MAX_RETRIES):
            try:
                source_account = await asyncio.to_thread(
                    self.horizon_server.load_account, 
                    signer_keypair.public_key
                )
                
                transaction = (
                    TransactionBuilder(source_account, self.network_passphrase, base_fee=100)
                    .append_invoke_contract_function_op(
                        contract_id=self.contract_address,
                        function_name=function_name,
                        parameters=args,
                        source=signer_keypair.public_key,
                    )
                    .set_timeout(30)
                    .build()
                )
                
                simulated = await asyncio.to_thread(self.soroban_server.simulate_transaction, transaction)
                
                if hasattr(simulated, 'error') and simulated.error:
                    raise ContractError(f"Simulação falhou: {simulated.error}")
                
                if read_only:
                    if simulated.results and len(simulated.results) > 0:
                        result_value = self._process_simulation_result(simulated.results[0])
                        return ContractCallResult(success=True, result_data=result_value)
                    return ContractCallResult(success=False, error_message="Nenhum resultado da simulação")
                
                prepared_transaction = await asyncio.to_thread(
                    self.soroban_server.prepare_transaction, 
                    transaction, 
                    simulated
                )
                
                prepared_transaction.sign(signer_keypair)
                
                send_tx_response = await asyncio.to_thread(self.soroban_server.send_transaction, prepared_transaction)

                # --- SEÇÃO CORRIGIDA ---
                # Trata a resposta da submissão de forma mais robusta, sem usar o atributo '.error'
                if send_tx_response.status == "ERROR":
                    error_details = getattr(send_tx_response, 'result_xdr', 'Nenhum detalhe de erro disponível')
                    raise ContractError(f"Submissão da transação falhou com status 'ERROR'. Detalhes: {error_details}")
                elif send_tx_response.status != "PENDING":
                    raise ContractError(f"Submissão da transação retornou status inesperado: {send_tx_response.status}")
                # --- FIM DA SEÇÃO CORRIGIDA ---
                
                tx_hash = send_tx_response.hash
                
                for _ in range(15):  # Tenta por até 30 segundos
                    await asyncio.sleep(2)
                    tx_status = await asyncio.to_thread(self.soroban_server.get_transaction, tx_hash)
                    
                    if tx_status.status == "SUCCESS":
                        result_value = self._extract_transaction_result(tx_status)
                        return ContractCallResult(success=True, transaction_hash=tx_hash, result_data=result_value)
                    elif tx_status.status == "FAILED":
                        raise ContractError(f"Transação falhou na blockchain: {tx_status.result_xdr}")
                
                raise ContractError("Timeout: A transação não foi confirmada a tempo.")

            except Exception as e:
                logger.warning(f"Tentativa {attempt + 1} para '{function_name}' falhou: {str(e)}")
                if attempt == MAX_RETRIES - 1:
                    return ContractCallResult(success=False, error_message=str(e))
                await asyncio.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
        
        return ContractCallResult(success=False, error_message="Máximo de tentativas excedido")

    def _scval_to_python(self, scval_obj: stellar_xdr.SCVal) -> Any:
        return scval.from_xdr(scval_obj.to_xdr())

    def _extract_transaction_result(self, tx_status) -> Any:
        try:
            if tx_status.result_meta_xdr:
                meta = stellar_xdr.TransactionMeta.from_xdr(tx_status.result_meta_xdr)
                if meta.v3 and meta.v3.soroban_meta and meta.v3.soroban_meta.return_value:
                    return self._scval_to_python(meta.v3.soroban_meta.return_value)
            return None
        except Exception as e:
            logger.warning(f"Falha ao extrair resultado da transação: {e}")
            return None

    def _process_simulation_result(self, result) -> Any:
        try:
            if hasattr(result, 'xdr'):
                scval_decoded = stellar_xdr.SCVal.from_xdr(result.xdr)
                return self._scval_to_python(scval_decoded)
            return None
        except Exception as e:
            logger.warning(f"Falha ao processar resultado da simulação: {e}")
            return None

    async def balance(self, owner_address: str) -> ContractCallResult:
        try:
            args = [scval.to_address(owner_address)]
            result = await self._execute_contract_function("balance", args, self.admin_keypair, read_only=True)
            if result.success:
                result.result_data = {"balance": result.result_data}
            return result
        except Exception as e:
            return ContractCallResult(success=False, error_message=str(e))

    async def mint(self, to_address: str, amount: int) -> ContractCallResult:
        try:
            if amount <= 0:
                raise ValueError("A quantidade para mintar deve ser positiva")
            args = [
                scval.to_address(to_address),
                scval.to_int128(amount)
            ]
            return await self._execute_contract_function("mint", args, signer_keypair=self.admin_keypair)
        except Exception as e:
            logger.error(f"Operação de mint falhou: {e}")
            return ContractCallResult(success=False, error_message=str(e))

    async def transfer(self, from_address: str, to_address: str, amount: int) -> ContractCallResult:
        try:
            args = [
                scval.to_address(from_address),
                scval.to_address(to_address),
                scval.to_int128(amount)
            ]
            return await self._execute_contract_function("transfer", args, signer_keypair=self.admin_keypair)
        except Exception as e:
            return ContractCallResult(success=False, error_message=str(e))

    async def setup(self):
        logger.info("Configuração da integração com Soroban concluída.")
        return {
            "status": "success",
            "contract_address": self.contract_address,
            "admin_address": self.admin_keypair.public_key,
            "message": "Gerenciador de contrato inicializado."
        }

try:
    logger.info("Inicializando o SorobanContractManager...")
    contract_id = os.getenv("ATHLETE_TOKEN_CONTRACT")
    admin_secret = os.getenv("ADMIN_SECRET_KEY")

    if not contract_id or not admin_secret:
        raise ValueError("As variáveis de ambiente ATHLETE_TOKEN_CONTRACT e ADMIN_SECRET_KEY devem ser definidas.")

    contract_manager = SorobanContractManager(
        contract_address=contract_id,
        admin_keypair=Keypair.from_secret(admin_secret)
    )
    logger.info("SorobanContractManager inicializado com sucesso.")

except Exception as e:
    logger.critical(f"FALHA CRÍTICA AO INICIALIZAR O SorobanContractManager: {e}")
    logger.critical("A aplicação não pode iniciar corretamente. Verifique as variáveis de ambiente e a chave secreta.")
    raise e