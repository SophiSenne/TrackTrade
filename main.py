from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from enum import Enum
import stellar_sdk
from stellar_sdk import Server, Keypair, TransactionBuilder, Network, Asset
from stellar_sdk.exceptions import Ed25519PublicKeyInvalidError, BadRequestError
import httpx
import json
import uvicorn
from decimal import Decimal
import asyncio

# Configuração da aplicação
app = FastAPI(
    title="SportToken API",
    description="API para tokenização de atletas usando Stellar Blockchain",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuração Stellar
STELLAR_NETWORK = Network.TESTNET_NETWORK_PASSPHRASE  # Use MAINNET para produção
HORIZON_URL = "https://horizon-testnet.stellar.org"  # Use horizon.stellar.org para produção
server = Server(HORIZON_URL)

# Modelos Pydantic

class SportType(str, Enum):
    FOOTBALL = "football"
    BASKETBALL = "basketball"
    TENNIS = "tennis"
    SWIMMING = "swimming"
    ATHLETICS = "athletics"
    VOLLEYBALL = "volleyball"
    PARALYMPIC = "paralympic"

class AthleteLevel(str, Enum):
    AMATEUR = "amateur"
    SEMI_PROFESSIONAL = "semi_professional"
    PROFESSIONAL = "professional"
    ELITE = "elite"

class TokenStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"

class AthleteData(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    age: int = Field(..., ge=14, le=50)
    sport: SportType
    level: AthleteLevel
    height: Optional[float] = Field(None, ge=1.0, le=3.0)
    weight: Optional[float] = Field(None, ge=30.0, le=200.0)
    country: str = Field(..., min_length=2, max_length=3)
    bio: Optional[str] = Field(None, max_length=1000)
    achievements: Optional[List[str]] = []
    social_media: Optional[Dict[str, str]] = {}

class PerformanceMetrics(BaseModel):
    wins: int = Field(default=0, ge=0)
    losses: int = Field(default=0, ge=0)
    ranking_position: Optional[int] = Field(None, ge=1)
    recent_performance_score: float = Field(..., ge=0.0, le=100.0)
    potential_score: float = Field(..., ge=0.0, le=100.0)
    media_exposure_score: float = Field(default=0.0, ge=0.0, le=100.0)

class TokenomicsConfig(BaseModel):
    total_supply: int = Field(..., ge=1000, le=10000000)
    price_per_token: Decimal = Field(..., ge=Decimal("0.01"), le=Decimal("1000.00"))
    minimum_investment: Optional[Decimal] = Field(default=Decimal("10.00"), ge=Decimal("1.00"))
    revenue_share_percentage: float = Field(..., ge=5.0, le=50.0)
    token_symbol: str = Field(..., min_length=3, max_length=12, pattern=r'^[A-Z][A-Z0-9]*$')

class CreateAthleteTokenRequest(BaseModel):
    athlete_data: AthleteData
    performance_metrics: PerformanceMetrics
    tokenomics: TokenomicsConfig
    funding_goal: Decimal = Field(..., ge=Decimal("1000.00"))
    campaign_duration_days: int = Field(..., ge=30, le=365)

class InvestmentRequest(BaseModel):
    token_id: str
    amount_xlm: Decimal = Field(..., ge=Decimal("1.00"))
    investor_stellar_address: str

class RevenueDistribution(BaseModel):
    token_id: str
    revenue_amount: Decimal
    source: str  # "prize", "marketing", "events", "other"
    description: Optional[str] = None

# Armazenamento em memória (em produção, use um banco de dados)
athletes_db: Dict[str, dict] = {}
tokens_db: Dict[str, dict] = {}
investments_db: Dict[str, list] = {}

# Funções auxiliares

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

# Endpoints da API

@app.get("/")
async def root():
    return {
        "message": "SportToken API - Tokenização de Atletas",
        "version": "1.0.0",
        "network": "Stellar Testnet" if "testnet" in HORIZON_URL else "Stellar Mainnet"
    }

@app.post("/athletes/create-token")
async def create_athlete_token(request: CreateAthleteTokenRequest):
    """Cria um novo token para um atleta"""
    
    # Gerar keypairs para o emissor e distribuidor
    issuer_keypair = Keypair.random()
    distributor_keypair = Keypair.random()
    
    # Calcular valorização do atleta
    athlete_valuation = calculate_athlete_valuation(
        request.athlete_data, 
        request.performance_metrics
    )
    
    # Criar ID único para o token
    token_id = f"{request.tokenomics.token_symbol}_{int(datetime.now().timestamp())}"
    
    # Calcular preço ajustado baseado na valorização
    adjusted_price = request.tokenomics.price_per_token * Decimal(str(athlete_valuation / 50.0))
    
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
        "issuer_secret": issuer_keypair.secret,  # Em produção, armazene com segurança
        "distributor_public_key": distributor_keypair.public_key,
        "distributor_secret": distributor_keypair.secret,  # Em produção, armazene com segurança
        "status": TokenStatus.DRAFT,
        "created_at": datetime.now().isoformat(),
        "campaign_end_date": (datetime.now() + timedelta(days=request.campaign_duration_days)).isoformat(),
        "total_raised": 0.0,
        "investors_count": 0,
        "tokens_sold": 0
    }
    
    tokens_db[token_id] = token_data
    investments_db[token_id] = []
    
    return {
        "token_id": token_id,
        "athlete_name": request.athlete_data.name,
        "token_symbol": request.tokenomics.token_symbol,
        "athlete_valuation": athlete_valuation,
        "adjusted_price_per_token": float(adjusted_price),
        "issuer_address": issuer_keypair.public_key,
        "distributor_address": distributor_keypair.public_key,
        "status": "created",
        "message": "Token criado com sucesso! Próximo passo: ativar o token para começar a campanha."
    }

@app.post("/tokens/{token_id}/activate")
async def activate_token(token_id: str):
    """Ativa um token para permitir investimentos"""
    
    if token_id not in tokens_db:
        raise HTTPException(status_code=404, detail="Token não encontrado")
    
    token_data = tokens_db[token_id]
    
    if token_data["status"] != TokenStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Token já foi ativado ou finalizado")
    
    try:
        # Criar asset na Stellar
        issuer_keypair = Keypair.from_secret(token_data["issuer_secret"])
        asset = Asset(token_data["tokenomics"]["token_symbol"], issuer_keypair.public_key)
        
        # Simular criação das contas na testnet (em produção, as contas precisam ser financiadas)
        
        tokens_db[token_id]["status"] = TokenStatus.ACTIVE
        tokens_db[token_id]["stellar_asset"] = {
            "code": token_data["tokenomics"]["token_symbol"],
            "issuer": issuer_keypair.public_key
        }
        
        return {
            "token_id": token_id,
            "status": "active",
            "asset_code": token_data["tokenomics"]["token_symbol"],
            "asset_issuer": issuer_keypair.public_key,
            "message": "Token ativado com sucesso! Agora pode receber investimentos."
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao ativar token: {str(e)}")

@app.get("/tokens")
async def list_tokens(sport: Optional[SportType] = None, status: Optional[TokenStatus] = None):
    """Lista todos os tokens disponíveis"""
    
    filtered_tokens = []
    
    for token_id, token_data in tokens_db.items():
        # Filtrar por esporte se especificado
        if sport and token_data["athlete_data"]["sport"] != sport:
            continue
            
        # Filtrar por status se especificado
        if status and token_data["status"] != status:
            continue
        
        filtered_token = {
            "token_id": token_id,
            "athlete_name": token_data["athlete_data"]["name"],
            "sport": token_data["athlete_data"]["sport"],
            "token_symbol": token_data["tokenomics"]["token_symbol"],
            "athlete_valuation": token_data["athlete_valuation"],
            "price_per_token": token_data["adjusted_price_per_token"],
            "funding_goal": token_data["funding_goal"],
            "total_raised": token_data["total_raised"],
            "investors_count": token_data["investors_count"],
            "status": token_data["status"],
            "campaign_end_date": token_data["campaign_end_date"]
        }
        
        filtered_tokens.append(filtered_token)
    
    return {
        "tokens": filtered_tokens,
        "total": len(filtered_tokens)
    }

@app.get("/tokens/{token_id}")
async def get_token_details(token_id: str):
    """Obtém detalhes completos de um token"""
    
    if token_id not in tokens_db:
        raise HTTPException(status_code=404, detail="Token não encontrado")
    
    token_data = tokens_db[token_id]
    
    # Adicionar lista de investidores (sem dados sensíveis)
    investors = []
    if token_id in investments_db:
        for investment in investments_db[token_id]:
            investors.append({
                "amount_xlm": investment["amount_xlm"],
                "tokens_purchased": investment["tokens_purchased"],
                "timestamp": investment["timestamp"]
            })
    
    return {
        **token_data,
        "investors": investors
    }

@app.post("/investments/invest")
async def invest_in_athlete(investment: InvestmentRequest):
    """Permite que um investidor compre tokens de um atleta"""
    
    if investment.token_id not in tokens_db:
        raise HTTPException(status_code=404, detail="Token não encontrado")
    
    token_data = tokens_db[investment.token_id]
    
    if token_data["status"] != TokenStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Token não está ativo para investimentos")
    
    # Verificar se a campanha ainda está ativa
    campaign_end = datetime.fromisoformat(token_data["campaign_end_date"])
    if datetime.now() > campaign_end:
        raise HTTPException(status_code=400, detail="Campanha de financiamento já encerrou")
    
    # Verificar investimento mínimo
    minimum_investment = Decimal(str(token_data["tokenomics"].get("minimum_investment", "10.00")))
    if investment.amount_xlm < minimum_investment:
        raise HTTPException(
            status_code=400, 
            detail=f"Investimento mínimo é {minimum_investment} XLM"
        )
    
    # Calcular quantidade de tokens a ser comprada
    price_per_token = Decimal(str(token_data["adjusted_price_per_token"]))
    tokens_to_purchase = int(investment.amount_xlm / price_per_token)
    
    if tokens_to_purchase == 0:
        raise HTTPException(status_code=400, detail="Valor muito baixo para comprar pelo menos 1 token")
    
    # Verificar se há tokens suficientes disponíveis
    tokens_available = token_data["tokenomics"]["total_supply"] - token_data["tokens_sold"]
    if tokens_to_purchase > tokens_available:
        raise HTTPException(status_code=400, detail=f"Apenas {tokens_available} tokens disponíveis")
    
    # Registrar investimento
    investment_data = {
        "investor_address": investment.investor_stellar_address,
        "amount_xlm": float(investment.amount_xlm),
        "tokens_purchased": tokens_to_purchase,
        "timestamp": datetime.now().isoformat(),
        "transaction_id": f"inv_{int(datetime.now().timestamp())}"
    }
    
    # Atualizar dados do token
    tokens_db[investment.token_id]["total_raised"] += float(investment.amount_xlm)
    tokens_db[investment.token_id]["tokens_sold"] += tokens_to_purchase
    tokens_db[investment.token_id]["investors_count"] += 1
    
    # Adicionar à lista de investimentos
    investments_db[investment.token_id].append(investment_data)
    
    # Verificar se atingiu a meta de financiamento
    if tokens_db[investment.token_id]["total_raised"] >= token_data["funding_goal"]:
        tokens_db[investment.token_id]["status"] = TokenStatus.COMPLETED
    
    return {
        "transaction_id": investment_data["transaction_id"],
        "tokens_purchased": tokens_to_purchase,
        "total_cost_xlm": float(investment.amount_xlm),
        "remaining_tokens": tokens_available - tokens_to_purchase,
        "campaign_progress": f"{(tokens_db[investment.token_id]['total_raised'] / token_data['funding_goal']) * 100:.2f}%",
        "message": "Investimento realizado com sucesso!"
    }

@app.post("/revenue/distribute")
async def distribute_revenue(revenue: RevenueDistribution):
    """Distribui receita para os detentores de tokens"""
    
    if revenue.token_id not in tokens_db:
        raise HTTPException(status_code=404, detail="Token não encontrado")
    
    token_data = tokens_db[revenue.token_id]
    
    if not investments_db.get(revenue.token_id):
        raise HTTPException(status_code=400, detail="Não há investidores neste token")
    
    # Calcular distribuição por token
    total_tokens_sold = token_data["tokens_sold"]
    revenue_per_token = revenue.revenue_amount / Decimal(str(total_tokens_sold))
    
    distributions = []
    total_distributed = Decimal("0")
    
    # Calcular distribuição para cada investidor
    for investment in investments_db[revenue.token_id]:
        investor_tokens = investment["tokens_purchased"]
        investor_revenue = revenue_per_token * Decimal(str(investor_tokens))
        
        distributions.append({
            "investor_address": investment["investor_address"],
            "tokens_owned": investor_tokens,
            "revenue_share": float(investor_revenue),
            "percentage": f"{(investor_tokens / total_tokens_sold) * 100:.2f}%"
        })
        
        total_distributed += investor_revenue
    
    # Registrar distribuição
    distribution_record = {
        "token_id": revenue.token_id,
        "total_revenue": float(revenue.revenue_amount),
        "source": revenue.source,
        "description": revenue.description,
        "distributions": distributions,
        "timestamp": datetime.now().isoformat()
    }
    
    return {
        "distribution_id": f"dist_{int(datetime.now().timestamp())}",
        "total_revenue": float(revenue.revenue_amount),
        "total_distributed": float(total_distributed),
        "revenue_per_token": float(revenue_per_token),
        "investors_count": len(distributions),
        "distributions": distributions,
        "message": "Receita distribuída com sucesso!"
    }

@app.get("/athletes/{token_id}/performance")
async def update_performance_metrics(token_id: str, metrics: PerformanceMetrics):
    """Atualiza métricas de performance de um atleta"""
    
    if token_id not in tokens_db:
        raise HTTPException(status_code=404, detail="Token não encontrado")
    
    # Atualizar métricas
    tokens_db[token_id]["performance_metrics"] = metrics.dict()
    
    # Recalcular valorização
    athlete_data = AthleteData(**tokens_db[token_id]["athlete_data"])
    new_valuation = calculate_athlete_valuation(athlete_data, metrics)
    tokens_db[token_id]["athlete_valuation"] = new_valuation
    
    return {
        "token_id": token_id,
        "new_valuation": new_valuation,
        "previous_valuation": tokens_db[token_id].get("previous_valuation", 0),
        "change_percentage": f"{((new_valuation / tokens_db[token_id].get('previous_valuation', new_valuation)) - 1) * 100:.2f}%",
        "updated_metrics": metrics.dict(),
        "message": "Métricas de performance atualizadas com sucesso!"
    }

@app.get("/dashboard/summary")
async def get_dashboard_summary():
    """Retorna resumo geral da plataforma"""
    
    total_tokens = len(tokens_db)
    active_tokens = len([t for t in tokens_db.values() if t["status"] == TokenStatus.ACTIVE])
    total_raised = sum(t["total_raised"] for t in tokens_db.values())
    total_investors = sum(t["investors_count"] for t in tokens_db.values())
    
    # Estatísticas por esporte
    sports_stats = {}
    for token in tokens_db.values():
        sport = token["athlete_data"]["sport"]
        if sport not in sports_stats:
            sports_stats[sport] = {"count": 0, "total_raised": 0}
        sports_stats[sport]["count"] += 1
        sports_stats[sport]["total_raised"] += token["total_raised"]
    
    return {
        "platform_stats": {
            "total_tokens": total_tokens,
            "active_campaigns": active_tokens,
            "total_raised_xlm": total_raised,
            "total_investors": total_investors,
            "average_raised_per_token": total_raised / max(total_tokens, 1)
        },
        "sports_breakdown": sports_stats,
        "recent_tokens": list(tokens_db.values())[-5:] if tokens_db else []
    }

# Background task para verificar campanhas expiradas
@app.on_event("startup")
async def startup_event():
    print("SportToken API iniciada!")
    print(f"Rede Stellar: {'Testnet' if 'testnet' in HORIZON_URL else 'Mainnet'}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=2000)