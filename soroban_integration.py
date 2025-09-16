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
from pydantic_models import AthleteData, PerformanceMetrics, TokenStatus

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
    
    def generate_token_id(self, athlete_name: str, timestamp: int) -> bytes:
        """Generate a unique 32-byte token ID"""
        data = f"{athlete_name}_{timestamp}_{self.contract_address}".encode('utf-8')
        return hashlib.sha256(data).digest()
    
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
    
    async def initialize_contract(self) -> ContractCallResult:
        """Initialize the contract with admin"""
        logger.info("Initializing contract...")
        
        args = [scval.Address(StellarAddress(self.admin_keypair.public_key))]
        
        result = await self._execute_contract_function("initialize", args)
        
        if result.success:
            logger.info(f"Contract initialized successfully: {result.transaction_hash}")
        else:
            logger.error(f"Contract initialization failed: {result.error_message}")
        
        return result
    
    async def create_athlete_token(
        self, 
        athlete_data: AthleteData, 
        total_supply: int,
        price_per_token: Decimal,
        issuer_keypair: Keypair
    ) -> ContractCallResult:
        """Create a new athlete token"""
        try:
            timestamp = int(datetime.now().timestamp())
            token_id = self.generate_token_id(athlete_data.name, timestamp)
            
            # Validate inputs
            if total_supply <= 0:
                raise ValueError("Total supply must be positive")
            if price_per_token <= 0:
                raise ValueError("Price per token must be positive")
            
            price_stroops = int(price_per_token * STROOPS_PER_XLM)
            
            args = [
                scval.Bytes(token_id),
                scval.String(athlete_data.name),
                scval.String(athlete_data.sport.value),
                scval.String(f"{athlete_data.name[:3].upper()}{timestamp}"),
                scval.U64(total_supply),
                scval.U64(price_stroops),
                scval.Address(StellarAddress(issuer_keypair.public_key))
            ]
            
            result = await self._execute_contract_function("create_athlete_token", args)
            
            if result.success:
                # Enhance result with token metadata
                result.result_data.update({
                    "token_id": token_id.hex(),
                    "athlete_name": athlete_data.name,
                    "token_symbol": f"{athlete_data.name[:3].upper()}{timestamp}",
                    "price_per_token": float(price_per_token),
                    "total_supply": total_supply,
                    "issuer_address": issuer_keypair.public_key
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
    
    async def create_campaign(
        self,
        token_id: str,
        funding_goal: Decimal,
        duration_days: int,
        min_investment: Decimal
    ) -> ContractCallResult:
        """Create a funding campaign"""
        try:
            # Validate inputs
            if funding_goal <= 0:
                raise ValueError("Funding goal must be positive")
            if duration_days <= 0 or duration_days > 365:
                raise ValueError("Duration must be between 1 and 365 days")
            if min_investment <= 0:
                raise ValueError("Minimum investment must be positive")
            
            funding_goal_stroops = int(funding_goal * STROOPS_PER_XLM)
            min_investment_stroops = int(min_investment * STROOPS_PER_XLM)
            
            args = [
                scval.Bytes(bytes.fromhex(token_id)),
                scval.U64(funding_goal_stroops),
                scval.U32(duration_days),
                scval.U64(min_investment_stroops)
            ]
            
            result = await self._execute_contract_function("create_campaign", args)
            
            if result.success:
                result.result_data.update({
                    "token_id": token_id,
                    "funding_goal": float(funding_goal),
                    "duration_days": duration_days,
                    "min_investment": float(min_investment)
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


# Configuration
CONTRACT_ADDRESS = "CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQAHHAGK7Q"
ADMIN_SECRET_KEY = "SAIPPNG3AGHSK2CLHIYQMVBPHISOOPT64MMW2PQGER2NIANN6TJU7"

# Global instances
contract_manager = SorobanContractManager(
    CONTRACT_ADDRESS,
    Keypair.from_secret(ADMIN_SECRET_KEY)
)

# Event handlers
async def handle_investment_event(event: Dict):
    """Handle investment events"""
    logger.info(f"Investment event: {event}")
    # Add custom logic here

async def handle_revenue_event(event: Dict):
    """Handle revenue distribution events"""
    logger.info(f"Revenue distribution event: {event}")
    # Add custom logic here

event_listener = EnhancedEventListener(
    CONTRACT_ADDRESS,
    callback_handlers={
        "investment": handle_investment_event,
        "revenue_distribution": handle_revenue_event
    }
)

batch_manager = BatchOperationManager(contract_manager)


# Setup function
async def setup_enhanced_soroban_integration():
    """Setup the enhanced Soroban integration"""
    try:
        # Initialize contract
        init_result = await contract_manager.initialize_contract()
        
        # Start event listener
        asyncio.create_task(event_listener.start_listening())
        
        logger.info("Soroban integration setup completed")
        
        return {
            "status": "success",
            "contract_address": CONTRACT_ADDRESS,
            "admin_address": contract_manager.admin_keypair.public_key,
            "initialization": init_result,
            "event_listener": "started"
        }
        
    except Exception as e:
        logger.error(f"Setup failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


# Example usage
async def example_usage():
    """Example of how to use the enhanced integration"""
    
    # Create an athlete token
    athlete_data = AthleteData(
        name="Example Athlete",
        sport="football",  # Adjust based on your enum
        age=25,
        country="Brazil"
    )
    
    issuer_keypair = Keypair.random()
    
    result = await contract_manager.create_athlete_token(
        athlete_data=athlete_data,
        total_supply=1000000,
        price_per_token=Decimal("0.1"),
        issuer_keypair=issuer_keypair
    )
    
    if result.success:
        logger.info(f"Token created successfully: {result.result_data}")
        
        # Create a campaign for the token
        campaign_result = await contract_manager.create_campaign(
            token_id=result.result_data["token_id"],
            funding_goal=Decimal("100000"),
            duration_days=30,
            min_investment=Decimal("10.0")
        )
        
        if campaign_result.success:
            logger.info(f"Campaign created: {campaign_result.result_data}")
        else:
            logger.error(f"Campaign creation failed: {campaign_result.error_message}")
    else:
        logger.error(f"Token creation failed: {result.error_message}")


if __name__ == "__main__":
    # Run example
    asyncio.run(example_usage())