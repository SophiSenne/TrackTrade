from pydantic_models import AthleteData, AthleteLevel, PerformanceMetrics
from stellar_sdk import Keypair, Asset, TransactionBuilder
from stellar_config import server, STELLAR_NETWORK
from fastapi import HTTPException

def calculate_athlete_valuation(athlete: AthleteData, performance: PerformanceMetrics) -> float:
    """Calcula a valorização do atleta baseada em dados objetivos"""
    base_score = performance.recent_performance_score * 0.3
    potential_score = performance.potential_score * 0.25
    media_score = performance.media_exposure_score * 0.15
    
    # Fator idade (atletas mais jovens têm maior potencial)
    age_factor = max(0.5, (35 - athlete.age) / 20) * 0.15
    
    # Fator nível
    level_multipliers = {
        AthleteLevel.AMATEUR: 0.5,
        AthleteLevel.SEMI_PROFESSIONAL: 0.7,
        AthleteLevel.PROFESSIONAL: 1.0,
        AthleteLevel.ELITE: 1.3
    }
    level_factor = level_multipliers[athlete.level] * 0.15
    
    total_score = base_score + potential_score + media_score + age_factor + level_factor
    return min(100.0, total_score)

async def create_stellar_asset(token_symbol: str, issuer_keypair: Keypair) -> Asset:
    """Cria um novo asset na rede Stellar"""
    return Asset(token_symbol, issuer_keypair.public_key)

async def issue_tokens(asset: Asset, amount: str, issuer_keypair: Keypair, distributor_public_key: str):
    """Emite tokens para o distribuidor"""
    try:
        issuer_account = server.load_account(issuer_keypair.public_key)
        
        transaction = (
            TransactionBuilder(
                source_account=issuer_account,
                network_passphrase=STELLAR_NETWORK,
                base_fee=100,
            )
            .append_payment_op(
                destination=distributor_public_key,
                asset=asset,
                amount=amount,
            )
            .set_timeout(30)
            .build()
        )
        
        transaction.sign(issuer_keypair)
        response = server.submit_transaction(transaction)
        return response
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao emitir tokens: {str(e)}")