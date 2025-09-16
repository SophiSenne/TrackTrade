# soroban_integration.py - Improved Version
import asyncio
from typing import Dict, Optional, List, Union
import json
from decimal import Decimal
from datetime import datetime
import hashlib
import logging
from dataclasses import dataclass
from enum import Enum
from dotenv import load_dotenv
import os

load_dotenv()

from stellar_sdk import (
    Server, Keypair, Network, TransactionBuilder, 
    SorobanServer, Address as StellarAddress,
    scval, xdr as stellar_xdr
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import your existing modules
from stellar_config import HORIZON_URL, SOROBAN_RPC_URL, NETWORK_PASSPHRASE

# Constants
STROOPS_PER_XLM = 10_000_000
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


@dataclass
class ContractCallResult:
    """Structured result for contract calls"""
    success: bool
    transaction_hash: Optional[str] = None
    result_data: Optional[Dict] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None


class ContractError(Exception):
    """Custom exception for contract-related errors"""
    def __init__(self, message: str, error_code: str = None):
        super().__init__(message)
        self.error_code = error_code


class SorobanContractManager:
    """Enhanced Soroban contract manager with better error handling and utilities"""
    
    def __init__(self, contract_address: str, admin_keypair: Keypair):
        self.contract_address = contract_address
        self.admin_keypair = admin_keypair
        self.horizon_server = Server(HORIZON_URL)
        self.soroban_server = SorobanServer(SOROBAN_RPC_URL)
        
        # Determine network based on URL
        self.network = (
            Network.TESTNET_NETWORK_PASSPHRASE 
            if "testnet" in HORIZON_URL.lower() 
            else Network.PUBLIC_NETWORK_PASSPHRASE
        )
        
        logger.info(f"Initialized SorobanContractManager for contract {contract_address}")
    
    
    async def _execute_contract_function(
        self, 
        function_name: str, 
        args: List, 
        signer_keypair: Keypair = None,
        read_only: bool = False
    ) -> ContractCallResult:
        """
        Execute a contract function with proper error handling and retries
        
        Args:
            function_name: Name of the contract function
            args: Arguments for the function
            signer_keypair: Keypair to sign the transaction (defaults to admin)
            read_only: If True, only simulate the transaction
        """
        if signer_keypair is None:
            signer_keypair = self.admin_keypair
        
        for attempt in range(MAX_RETRIES):
            try:
                # Load source account
                source_account = await asyncio.to_thread(
                    self.horizon_server.load_account, 
                    signer_keypair.public_key
                )
                
                # Build transaction
                transaction = (
                    TransactionBuilder(source_account, self.network)
                    .add_host_function_op(
                        host_function=scval.InvokeContract(
                            contract_address=self.contract_address,
                            function_name=function_name,
                            args=args
                        )
                    )
                    .set_timeout(30)
                    .build()
                )
                
                # Simulate transaction
                simulated = await asyncio.to_thread(
                    self.soroban_server.simulate_transaction, 
                    transaction
                )
                
                # Check for simulation errors
                if hasattr(simulated, 'error') and simulated.error:
                    raise ContractError(f"Simulation failed: {simulated.error}", "SIMULATION_ERROR")
                
                # For read-only operations, return simulation result
                if read_only:
                    if simulated.results and len(simulated.results) > 0:
                        result_data = self._process_simulation_result(simulated.results[0])
                        return ContractCallResult(
                            success=True,
                            result_data=result_data
                        )
                    return ContractCallResult(success=False, error_message="No results from simulation")
                
                # Prepare and sign transaction
                prepared_tx = await asyncio.to_thread(
                    self.soroban_server.prepare_transaction,
                    transaction, 
                    simulated
                )
                prepared_tx.sign(signer_keypair)
                
                # Submit transaction
                response = await asyncio.to_thread(
                    self.horizon_server.submit_transaction,
                    prepared_tx
                )
                
                return ContractCallResult(
                    success=True,
                    transaction_hash=response.get("hash"),
                    result_data={"response": response}
                )
                
            except ContractError:
                raise
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {function_name}: {str(e)}")
                
                if attempt == MAX_RETRIES - 1:
                    return ContractCallResult(
                        success=False,
                        error_message=str(e),
                        error_code="EXECUTION_ERROR"
                    )
                
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
        
        return ContractCallResult(
            success=False,
            error_message="Max retries exceeded",
            error_code="MAX_RETRIES_EXCEEDED"
        )
    
    def _process_simulation_result(self, result) -> Dict:
        """Process simulation result into readable format"""
        try:
            # This is a simplified processor - you'd need to adapt based on your contract's return types
            if hasattr(result, 'xdr'):
                # Try to decode XDR result
                decoded = scval.from_xdr(result.xdr)
                return {"decoded_value": decoded, "raw_xdr": result.xdr}
            return {"raw_result": str(result)}
        except Exception as e:
            logger.warning(f"Failed to process simulation result: {e}")
            return {"error": str(e), "raw_result": str(result)}
    
    async def balance(self, owner_address: str) -> ContractCallResult:
        """Get token balance for an owner (read-only)"""
        try:
            args = [scval.Address(StellarAddress(owner_address))]
            return await self._execute_contract_function("balance", args, read_only=True)
        except Exception as e:
            return ContractCallResult(
                success=False,
                error_message=str(e),
                error_code="READ_ERROR"
            )

    async def mint(self, to_address: str, amount: int) -> ContractCallResult:
        """Mint new tokens to an address"""
        try:
            if amount <= 0:
                raise ValueError("Amount to mint must be positive")
            
            args = [
                scval.Address(StellarAddress(to_address)),
                scval.I128(amount)
            ]
            
            result = await self._execute_contract_function("mint", args, signer_keypair=self.admin_keypair)
            
            if result.success:
                result.result_data.update({
                    "to_address": to_address,
                    "amount": amount
                })
            
            return result
            
        except ValueError as e:
            return ContractCallResult(
                success=False,
                error_message=str(e),
                error_code="INVALID_INPUT"
            )
        except Exception as e:
            return ContractCallResult(
                success=False,
                error_message=str(e),
                error_code="UNEXPECTED_ERROR"
            )

    async def transfer(self, from_address: str, to_address: str, amount: int) -> ContractCallResult:
        """Transfer tokens from one address to another"""
        try:
            if amount <= 0:
                raise ValueError("Amount to transfer must be positive")
            
            args = [
                scval.Address(StellarAddress(from_address)),
                scval.Address(StellarAddress(to_address)),
                scval.I128(amount)
            ]
            
            # The 'from' address should sign the transfer
            # For now, we'll use the admin_keypair, but in a real scenario, 'from' should sign
            result = await self._execute_contract_function("transfer", args, signer_keypair=self.admin_keypair) 
            
            if result.success:
                result.result_data.update({
                    "from_address": from_address,
                    "to_address": to_address,
                    "amount": amount
                })
            
            return result
            
        except ValueError as e:
            return ContractCallResult(
                success=False,
                error_message=str(e),
                error_code="INVALID_INPUT"
            )
        except Exception as e:
            return ContractCallResult(
                success=False,
                error_message=str(e),
                error_code="UNEXPECTED_ERROR"
            )
    
    async def invest_in_token(
        self,
        investor_keypair: Keypair,
        token_id: str,
        xlm_amount: Decimal
    ) -> ContractCallResult:
        """Allow an investor to buy tokens"""
        try:
            if xlm_amount <= 0:
                raise ValueError("Investment amount must be positive")
            
            amount_stroops = int(xlm_amount * STROOPS_PER_XLM)
            
            args = [
                scval.Bytes(bytes.fromhex(token_id)),
                scval.U64(amount_stroops)
            ]
            
            result = await self._execute_contract_function(
                "invest", 
                args, 
                signer_keypair=investor_keypair
            )
            
            if result.success:
                result.result_data.update({
                    "investor": investor_keypair.public_key,
                    "token_id": token_id,
                    "xlm_amount": float(xlm_amount)
                })
            
            return result
            
        except ValueError as e:
            return ContractCallResult(
                success=False,
                error_message=str(e),
                error_code="INVALID_INPUT"
            )
        except Exception as e:
            return ContractCallResult(
                success=False,
                error_message=str(e),
                error_code="UNEXPECTED_ERROR"
            )
    
    async def get_token_info(self, token_id: str) -> ContractCallResult:
        """Get token information (read-only)"""
        try:
            args = [scval.Bytes(bytes.fromhex(token_id))]
            return await self._execute_contract_function("get_token_info", args, read_only=True)
        except Exception as e:
            return ContractCallResult(
                success=False,
                error_message=str(e),
                error_code="READ_ERROR"
            )
    
    async def get_campaign_info(self, token_id: str) -> ContractCallResult:
        """Get campaign information (read-only)"""
        try:
            args = [scval.Bytes(bytes.fromhex(token_id))]
            return await self._execute_contract_function("get_campaign_info", args, read_only=True)
        except Exception as e:
            return ContractCallResult(
                success=False,
                error_message=str(e),
                error_code="READ_ERROR"
            )
    
    async def get_investor_tokens(self, investor_address: str, token_id: str) -> ContractCallResult:
        """Get investor's token balance (read-only)"""
        try:
            args = [
                scval.Address(StellarAddress(investor_address)),
                scval.Bytes(bytes.fromhex(token_id))
            ]
            return await self._execute_contract_function("get_investor_tokens", args, read_only=True)
        except Exception as e:
            return ContractCallResult(
                success=False,
                error_message=str(e),
                error_code="READ_ERROR"
            )


class EnhancedEventListener:
    """Enhanced event listener with better error handling and filtering"""
    
    def __init__(self, contract_address: str, callback_handlers: Dict[str, callable] = None):
        self.contract_address = contract_address
        self.soroban_server = SorobanServer(SOROBAN_RPC_URL)
        self.is_listening = False
        self.callback_handlers = callback_handlers or {}
        self.last_processed_ledger = None
        
    async def start_listening(self, poll_interval: int = 5):
        """Start listening for contract events"""
        self.is_listening = True
        logger.info(f"Started listening for events on contract {self.contract_address}")
        
        while self.is_listening:
            try:
                events = await self._fetch_recent_events()
                
                for event in events:
                    await self._process_event(event)
                
                await asyncio.sleep(poll_interval)
                
            except Exception as e:
                logger.error(f"Error in event listener: {e}")
                await asyncio.sleep(poll_interval * 2)  # Longer delay on error
    
    async def stop_listening(self):
        """Stop listening for events"""
        self.is_listening = False
        logger.info("Stopped listening for contract events")
    
    async def _fetch_recent_events(self) -> List[Dict]:
        """Fetch recent contract events"""
        # Implement actual event fetching logic based on Soroban RPC capabilities
        # This is a placeholder implementation
        try:
            # In a real implementation, you'd use the Soroban RPC to fetch events
            # filtered by contract address and since last processed ledger
            return []
        except Exception as e:
            logger.error(f"Failed to fetch events: {e}")
            return []
    
    async def _process_event(self, event: Dict):
        """Process a single event"""
        try:
            event_type = event.get("type", "unknown")
            
            # Call specific handler if available
            if event_type in self.callback_handlers:
                await self.callback_handlers[event_type](event)
            else:
                await self._default_event_handler(event)
                
        except Exception as e:
            logger.error(f"Error processing event {event}: {e}")
    
    async def _default_event_handler(self, event: Dict):
        """Default event handler"""
        logger.info(f"Received event: {event}")


class BatchOperationManager:
    """Manager for batch operations on the contract"""
    
    def __init__(self, contract_manager: SorobanContractManager):
        self.contract_manager = contract_manager
    
    async def batch_create_tokens(
        self, 
        token_configs: List[Dict],
        max_concurrent: int = 3
    ) -> Dict[str, ContractCallResult]:
        """Create multiple tokens concurrently"""
        semaphore = asyncio.Semaphore(max_concurrent)
        results = {}
        
        async def create_single_token(config):
            async with semaphore:
                try:
                    return await self.contract_manager.create_athlete_token(**config)
                except Exception as e:
                    return ContractCallResult(
                        success=False,
                        error_message=str(e),
                        error_code="BATCH_ERROR"
                    )
        
        tasks = [
            create_single_token(config) 
            for config in token_configs
        ]
        
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results_list):
            if isinstance(result, Exception):
                results[f"token_{i}"] = ContractCallResult(
                    success=False,
                    error_message=str(result),
                    error_code="BATCH_EXCEPTION"
                )
            else:
                results[f"token_{i}"] = result
        
        return results


# Utility functions
def xlm_to_stroops(xlm_amount: Union[Decimal, float, int]) -> int:
    """Convert XLM to stroops"""
    return int(Decimal(str(xlm_amount)) * STROOPS_PER_XLM)


def stroops_to_xlm(stroops: int) -> Decimal:
    """Convert stroops to XLM"""
    return Decimal(stroops) / STROOPS_PER_XLM

# Global instances
contract_manager = SorobanContractManager(
    os.getenv("ATHLETE_TOKEN_CONTRACT"),
    Keypair.from_secret(os.getenv("ADMIN_SECRET_KEY"))
)

# Setup function
async def setup_enhanced_soroban_integration():
    """Setup the enhanced Soroban integration"""
    try:
        # The AthleteToken contract does not have an 'initialize' function.
        # We only need to ensure the contract manager is ready.
        logger.info("Soroban integration setup completed")
        
        return {
            "status": "success",
            "contract_address": CONTRACT_ADDRESS,
            "admin_address": contract_manager.admin_keypair.public_key,
            "message": "Contract manager initialized."
        }
        
    except Exception as e:
        logger.error(f"Setup failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


# Example usage
async def example_usage():
    """Example of how to use the AthleteToken contract functions"""
    
    test_account_1 = Keypair.random().public_key
    test_account_2 = Keypair.random().public_key

    # Mint tokens to test_account_1
    logger.info(f"Minting 1000 tokens to {test_account_1}")
    mint_result = await contract_manager.mint(test_account_1, 1000)

    if mint_result.success:
        logger.info(f"Mint successful: {mint_result.result_data}")

        # Check balance of test_account_1
        balance_result_1 = await contract_manager.balance(test_account_1)
        if balance_result_1.success:
            logger.info(f"Balance of {test_account_1}: {balance_result_1.result_data}")
        else:
            logger.error(f"Failed to get balance for {test_account_1}: {balance_result_1.error_message}")

        # Transfer tokens from test_account_1 to test_account_2
        logger.info(f"Transferring 200 tokens from {test_account_1} to {test_account_2}")
        transfer_result = await contract_manager.transfer(test_account_1, test_account_2, 200)

        if transfer_result.success:
            logger.info(f"Transfer successful: {transfer_result.result_data}")

            # Check balances after transfer
            balance_result_1_after = await contract_manager.balance(test_account_1)
            balance_result_2_after = await contract_manager.balance(test_account_2)

            if balance_result_1_after.success:
                logger.info(f"Balance of {test_account_1} after transfer: {balance_result_1_after.result_data}")
            else:
                logger.error(f"Failed to get balance for {test_account_1} after transfer: {balance_result_1_after.error_message}")
            
            if balance_result_2_after.success:
                logger.info(f"Balance of {test_account_2} after transfer: {balance_result_2_after.result_data}")
            else:
                logger.error(f"Failed to get balance for {test_account_2} after transfer: {balance_result_2_after.error_message}")

        else:
            logger.error(f"Transfer failed: {transfer_result.error_message}")
    else:
        logger.error(f"Mint failed: {mint_result.error_message}")

if __name__ == "__main__":
    # Run example
    asyncio.run(example_usage())