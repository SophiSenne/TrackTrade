from fastapi import APIRouter, HTTPException
from typing import Optional, Dict
from datetime import datetime, timedelta
from decimal import Decimal
import json

from stellar_sdk import Keypair, Asset
from stellar_config import HORIZON_URL

from utils import calculate_athlete_valuation
from database_config import execute_query, execute_single_query, init_database
from pydantic_models import (
    CreateAthleteTokenRequest,
    InvestmentRequest,
    RevenueDistribution,
    PerformanceMetrics,
    AthleteData,
    SportType,
    TokenStatus,
)

router = APIRouter()

# Verificar banco de dados na primeira execução
try:
    init_database()
except Exception as e:
    print(f"Aviso: {e}")

@router.get("/")
async def root():
    return {
        "message": "SportToken API - Tokenização de Atletas",
        "version": "1.0.0",
        "network": "Stellar Testnet" if "testnet" in HORIZON_URL else "Stellar Mainnet"
    }

@router.post("/athletes/create")
async def create_athlete(request: CreateAthleteTokenRequest):
    """Cria um novo atleta e seu token"""
    
    try:
        # Primeiro, criar o atleta
        athlete_query = """
            INSERT INTO athletes (
                name, age, sport, level, country, bio, 
                wins, losses, ranking_position, recent_performance_score,
                potential_score, media_exposure_score
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        
        # Extrair dados do request
        athlete_data = request.athlete_data
        performance = request.performance_metrics
        
        athlete_params = (
            athlete_data.name,
            athlete_data.age,
            athlete_data.sport.value,
            "professional",  # nível padrão
            athlete_data.country,
            athlete_data.bio,
            performance.wins if hasattr(performance, 'wins') else 0,
            performance.losses if hasattr(performance, 'losses') else 0,
            performance.ranking if hasattr(performance, 'ranking') else None,
            performance.recent_performance if hasattr(performance, 'recent_performance') else 50.0,
            performance.potential if hasattr(performance, 'potential') else 50.0,
            performance.social_media_followers / 1000000 * 10 if hasattr(performance, 'social_media_followers') else 25.0  # converter para score
        )
        
        athlete_result = execute_single_query(athlete_query, athlete_params)
        athlete_id = athlete_result['id']
        
        # Gerar keypairs para o emissor e distribuidor
        issuer_keypair = Keypair.random()
        distributor_keypair = Keypair.random()
        
        # Calcular valorização do atleta
        athlete_valuation = calculate_athlete_valuation(athlete_data, performance)
        
        # Calcular preço ajustado
        adjusted_price = request.tokenomics.price_per_token * Decimal(str(athlete_valuation / 50.0))
        
        # Criar o token do atleta
        token_query = """
            INSERT INTO athlete_tokens (
                athlete_id, created_by, token_symbol, total_supply, price_per_token,
                minimum_investment, revenue_share_percentage, funding_goal, 
                campaign_duration_days, status, campaign_end_date,
                issuer_public_key, distributor_public_key, athlete_valuation,
                adjusted_price_per_token
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        
        campaign_end_date = datetime.now() + timedelta(days=request.campaign_duration_days)
        
        token_params = (
            athlete_id,
            1,  # created_by - usuário padrão
            request.tokenomics.token_symbol,
            request.tokenomics.total_supply,
            float(adjusted_price),
            float(request.tokenomics.minimum_investment) if hasattr(request.tokenomics, 'minimum_investment') else 10.0,
            float(request.tokenomics.revenue_share_percentage) if hasattr(request.tokenomics, 'revenue_share_percentage') else 20.0,
            float(request.funding_goal),
            request.campaign_duration_days,
            'draft',
            campaign_end_date,
            issuer_keypair.public_key,
            distributor_keypair.public_key,
            float(athlete_valuation),
            float(adjusted_price)
        )
        
        token_result = execute_single_query(token_query, token_params)
        token_id = token_result['id']
        
        return {
            "athlete_id": athlete_id,
            "token_id": token_id,
            "athlete_name": athlete_data.name,
            "token_symbol": request.tokenomics.token_symbol,
            "athlete_valuation": athlete_valuation,
            "adjusted_price_per_token": float(adjusted_price),
            "issuer_address": issuer_keypair.public_key,
            "distributor_address": distributor_keypair.public_key,
            "status": "created",
            "message": "Atleta e token criados com sucesso!"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao criar atleta: {str(e)}")

@router.get("/athletes")
async def get_athletes():
    """Lista todos os atletas cadastrados"""
    
    query = """
        SELECT 
            a.id, a.name, a.age, a.sport, a.country, a.bio,
            a.wins, a.losses, a.ranking_position, a.recent_performance_score,
            a.potential_score, a.media_exposure_score, a.created_at,
            at.id as token_id, at.token_symbol, at.status as token_status,
            at.total_raised, at.funding_goal, at.athlete_valuation,
            at.adjusted_price_per_token, at.investors_count
        FROM athletes a
        LEFT JOIN athlete_tokens at ON a.id = at.athlete_id
        ORDER BY a.created_at DESC
    """
    
    athletes = execute_query(query)
    
    return {
        "athletes": [
            {
                "id": athlete["id"],
                "name": athlete["name"],
                "age": athlete["age"],
                "sport": athlete["sport"],
                "country": athlete["country"],
                "bio": athlete["bio"],
                "wins": athlete["wins"],
                "losses": athlete["losses"],
                "ranking_position": athlete["ranking_position"],
                "recent_performance_score": float(athlete["recent_performance_score"]) if athlete["recent_performance_score"] else 0,
                "potential_score": float(athlete["potential_score"]) if athlete["potential_score"] else 0,
                "media_exposure_score": float(athlete["media_exposure_score"]) if athlete["media_exposure_score"] else 0,
                "created_at": athlete["created_at"].isoformat() if athlete["created_at"] else None,
                "token": {
                    "id": athlete["token_id"],
                    "symbol": athlete["token_symbol"],
                    "status": athlete["token_status"],
                    "total_raised": float(athlete["total_raised"]) if athlete["total_raised"] else 0,
                    "funding_goal": float(athlete["funding_goal"]) if athlete["funding_goal"] else 0,
                    "valuation": float(athlete["athlete_valuation"]) if athlete["athlete_valuation"] else 0,
                    "price_per_token": float(athlete["adjusted_price_per_token"]) if athlete["adjusted_price_per_token"] else 0,
                    "investors_count": athlete["investors_count"] if athlete["investors_count"] else 0
                } if athlete["token_id"] else None
            }
            for athlete in athletes
        ],
        "total": len(athletes)
    }

@router.get("/tokens")
async def get_all_tokens(status: Optional[str] = None, sport: Optional[str] = None):
    """Lista todos os tokens disponíveis com filtros opcionais"""
    
    query = """
        SELECT 
            at.id, at.token_symbol, at.total_supply, at.price_per_token,
            at.funding_goal, at.campaign_duration_days, at.status,
            at.created_at, at.campaign_end_date, at.total_raised,
            at.tokens_sold, at.investors_count, at.athlete_valuation,
            at.adjusted_price_per_token,
            a.name as athlete_name, a.age, a.sport, a.country, a.bio,
            a.wins, a.losses, a.recent_performance_score
        FROM athlete_tokens at
        JOIN athletes a ON at.athlete_id = a.id
        WHERE 1=1
    """
    params = []
    
    if status:
        query += " AND at.status = %s"
        params.append(status)
    
    if sport:
        query += " AND a.sport = %s"
        params.append(sport)
    
    query += " ORDER BY at.created_at DESC"
    
    tokens = execute_query(query, tuple(params))
    
    return {
        "tokens": [
            {
                "id": token["id"],
                "token_symbol": token["token_symbol"],
                "athlete_name": token["athlete_name"],
                "athlete_sport": token["sport"],
                "athlete_country": token["country"],
                "athlete_bio": token["bio"],
                "athlete_valuation": float(token["athlete_valuation"]) if token["athlete_valuation"] else 0,
                "adjusted_price_per_token": float(token["adjusted_price_per_token"]) if token["adjusted_price_per_token"] else 0,
                "funding_goal": float(token["funding_goal"]),
                "total_raised": float(token["total_raised"]),
                "investors_count": token["investors_count"],
                "status": token["status"],
                "campaign_end_date": token["campaign_end_date"].isoformat() if token["campaign_end_date"] else None,
                "created_at": token["created_at"].isoformat() if token["created_at"] else None,
                "athlete_stats": {
                    "wins": token["wins"],
                    "losses": token["losses"],
                    "performance_score": float(token["recent_performance_score"]) if token["recent_performance_score"] else 0
                }
            }
            for token in tokens
        ],
        "total": len(tokens)
    }

@router.post("/tokens/{token_id}/activate")
async def activate_token(token_id: int):
    """Ativa um token para permitir investimentos"""
    
    # Buscar token no banco
    token_query = """
        SELECT at.*, a.name as athlete_name 
        FROM athlete_tokens at
        JOIN athletes a ON at.athlete_id = a.id
        WHERE at.id = %s
    """
    token = execute_single_query(token_query, (token_id,))
    
    if not token:
        raise HTTPException(status_code=404, detail="Token não encontrado")
    
    if token["status"] != 'draft':
        raise HTTPException(status_code=400, detail="Token já foi ativado ou está em outro estado")
    
    # Verificar se a campanha ainda está dentro do prazo
    if datetime.now() > token["campaign_end_date"]:
        raise HTTPException(status_code=400, detail="Campanha expirada")
    
    try:
        # Atualizar status para active
        update_query = "UPDATE athlete_tokens SET status = 'active' WHERE id = %s"
        execute_query(update_query, (token_id,), fetch=False)
        
        return {
            "token_id": token_id,
            "athlete_name": token["athlete_name"],
            "status": "activated",
            "campaign_end_date": token["campaign_end_date"].isoformat(),
            "message": f"Token ativado! Campanha ativa até {token['campaign_end_date'].strftime('%d/%m/%Y')}"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao ativar token: {str(e)}")

@router.post("/investments/invest")
async def invest_in_athlete(investment: InvestmentRequest):
    """Permite que um investidor compre tokens de um atleta"""
    
    # Buscar token
    token_query = """
        SELECT at.*, a.name as athlete_name 
        FROM athlete_tokens at
        JOIN athletes a ON at.athlete_id = a.id
        WHERE at.id = %s
    """
    token = execute_single_query(token_query, (investment.token_id,))
    
    if not token:
        raise HTTPException(status_code=404, detail="Token não encontrado")
    
    if token["status"] != 'active':
        raise HTTPException(status_code=400, detail="Token não está ativo para investimentos")
    
    # Verificar se a campanha ainda está ativa
    if datetime.now() > token["campaign_end_date"]:
        raise HTTPException(status_code=400, detail="Campanha expirada")
    
    # Verificar se ainda há espaço para mais investimento
    remaining_funding = float(token["funding_goal"]) - float(token["total_raised"])
    if investment.amount_xlm > remaining_funding:
        raise HTTPException(
            status_code=400, 
            detail=f"Valor de investimento excede o necessário. Restam apenas {remaining_funding} XLM"
        )
    
    # Calcular quantidade de tokens a comprar
    price_per_token = float(token["adjusted_price_per_token"])
    tokens_to_purchase = int(float(investment.amount_xlm) / price_per_token)
    
    try:
        # Inserir investimento
        investment_query = """
            INSERT INTO investments (
                athlete_token_id, user_id, amount_xlm, tokens_purchased,
                price_per_token_at_purchase, investor_stellar_address, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        
        investment_result = execute_single_query(investment_query, (
            investment.token_id,
            1,  # user_id padrão
            float(investment.amount_xlm),
            tokens_to_purchase,
            price_per_token,
            investment.investor_public_key,
            'confirmed'
        ))
        
        # Atualizar totais do token
        update_query = """
            UPDATE athlete_tokens 
            SET total_raised = total_raised + %s,
                tokens_sold = tokens_sold + %s,
                investors_count = investors_count + 1
            WHERE id = %s
        """
        execute_query(update_query, (
            float(investment.amount_xlm),
            tokens_to_purchase,
            investment.token_id
        ), fetch=False)
        
        # Verificar se atingiu a meta
        updated_token = execute_single_query(token_query, (investment.token_id,))
        
        if float(updated_token["total_raised"]) >= float(updated_token["funding_goal"]):
            complete_query = "UPDATE athlete_tokens SET status = 'completed' WHERE id = %s"
            execute_query(complete_query, (investment.token_id,), fetch=False)
        
        return {
            "investment_id": investment_result['id'],
            "token_id": investment.token_id,
            "athlete_name": token["athlete_name"],
            "amount_xlm": float(investment.amount_xlm),
            "tokens_purchased": tokens_to_purchase,
            "price_per_token": price_per_token,
            "total_raised": float(updated_token["total_raised"]),
            "campaign_progress": f"{(float(updated_token['total_raised']) / float(updated_token['funding_goal'])) * 100:.2f}%",
            "status": "success",
            "message": "Investimento realizado com sucesso!"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar investimento: {str(e)}")

@router.get("/dashboard/summary")
async def get_dashboard_summary():
    """Retorna resumo geral da plataforma"""
    
    # Estatísticas gerais
    total_tokens_query = "SELECT COUNT(*) as total FROM athlete_tokens"
    total_tokens = execute_single_query(total_tokens_query)["total"]
    
    active_tokens_query = "SELECT COUNT(*) as active FROM athlete_tokens WHERE status = 'active'"
    active_tokens = execute_single_query(active_tokens_query)["active"]
    
    totals_query = """
        SELECT 
            COALESCE(SUM(total_raised), 0) as total_raised,
            COALESCE(SUM(investors_count), 0) as total_investors
        FROM athlete_tokens
    """
    totals = execute_single_query(totals_query)
    
    # Estatísticas por esporte
    sports_query = """
        SELECT 
            a.sport,
            COUNT(*) as count,
            COALESCE(SUM(at.total_raised), 0) as total_raised
        FROM athlete_tokens at
        JOIN athletes a ON at.athlete_id = a.id
        GROUP BY a.sport
    """
    sports_stats = execute_query(sports_query)
    
    return {
        "platform_stats": {
            "total_tokens": total_tokens,
            "active_campaigns": active_tokens,
            "total_raised_xlm": float(totals["total_raised"]),
            "total_investors": totals["total_investors"],
            "average_raised_per_token": float(totals["total_raised"]) / max(total_tokens, 1)
        },
        "sports_breakdown": {
            sport["sport"]: {
                "count": sport["count"],
                "total_raised": float(sport["total_raised"])
            }
            for sport in sports_stats
        }
    }

@router.get("/athletes")
async def get_athletes():
    """Lista todos os atletas cadastrados"""
    
    query = """
        SELECT 
            a.id, a.name, a.age, a.sport, a.country, a.bio,
            a.wins, a.losses, a.ranking_position, a.recent_performance_score,
            a.potential_score, a.media_exposure_score, a.created_at,
            at.id as token_id, at.token_symbol, at.status as token_status,
            at.total_raised, at.funding_goal, at.athlete_valuation,
            at.adjusted_price_per_token, at.investors_count
        FROM athletes a
        LEFT JOIN athlete_tokens at ON a.id = at.athlete_id
        ORDER BY a.created_at DESC
    """
    
    athletes = execute_query(query)
    
    return {
        "athletes": [
            {
                "id": athlete["id"],
                "name": athlete["name"],
                "age": athlete["age"],
                "sport": athlete["sport"],
                "country": athlete["country"],
                "bio": athlete["bio"],
                "wins": athlete["wins"],
                "losses": athlete["losses"],
                "ranking_position": athlete["ranking_position"],
                "recent_performance_score": float(athlete["recent_performance_score"]) if athlete["recent_performance_score"] else 0,
                "potential_score": float(athlete["potential_score"]) if athlete["potential_score"] else 0,
                "media_exposure_score": float(athlete["media_exposure_score"]) if athlete["media_exposure_score"] else 0,
                "created_at": athlete["created_at"].isoformat() if athlete["created_at"] else None,
                "token": {
                    "id": athlete["token_id"],
                    "symbol": athlete["token_symbol"],
                    "status": athlete["token_status"],
                    "total_raised": float(athlete["total_raised"]) if athlete["total_raised"] else 0,
                    "funding_goal": float(athlete["funding_goal"]) if athlete["funding_goal"] else 0,
                    "valuation": float(athlete["athlete_valuation"]) if athlete["athlete_valuation"] else 0,
                    "price_per_token": float(athlete["adjusted_price_per_token"]) if athlete["adjusted_price_per_token"] else 0,
                    "investors_count": athlete["investors_count"] if athlete["investors_count"] else 0
                } if athlete["token_id"] else None
            }
            for athlete in athletes
        ],
        "total": len(athletes)
    }