from fastapi import APIRouter, HTTPException
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt
import json
from pydantic import BaseModel
from pydantic_models import AthleteData, PerformanceMetrics, SportType, AthleteLevel

# Configuração do banco
DATABASE_URL = "postgresql://postgres:VeYzFsTFjyYfYjwxPnmCfYetRwyUaWoV@switchback.proxy.rlwy.net:42316/railway"

# Modelos Pydantic para os novos endpoints
class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: str = "user"
    stellar_address: Optional[str] = None

class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str
    stellar_address: Optional[str]
    created_at: datetime

class AthleteCreate(BaseModel):
    athlete_data: AthleteData
    performance_metrics: PerformanceMetrics
    created_by: int

class AthleteResponse(BaseModel):
    id: int
    athlete_data: dict
    performance_metrics: dict
    created_by: int
    created_at: datetime

# Função para conectar ao banco
def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao conectar ao banco: {str(e)}")

# Função para hash de senha
def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

# Função para verificar senha
def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

router = APIRouter()

@router.post("/users", response_model=UserResponse)
async def create_user(user: UserCreate):
    """Cria um novo usuário"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Verificar se email já existe
            cur.execute("SELECT id FROM users WHERE email = %s", (user.email,))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="Email já cadastrado")
            
            # Hash da senha
            hashed_password = hash_password(user.password)
            
            # Inserir usuário
            cur.execute("""
                INSERT INTO users (name, email, password_hash, role, stellar_address)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, email, role, stellar_address, created_at
            """, (user.name, user.email, hashed_password, user.role, user.stellar_address))
            
            result = cur.fetchone()
            conn.commit()
            
            return UserResponse(
                id=result["id"],
                name=result["name"],
                email=result["email"],
                role=result["role"],
                stellar_address=result["stellar_address"],
                created_at=result["created_at"]
            )
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao criar usuário: {str(e)}")
    finally:
        conn.close()

@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int):
    """Busca um usuário por ID"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, email, role, stellar_address, created_at
                FROM users WHERE id = %s
            """, (user_id,))
            
            result = cur.fetchone()
            if not result:
                raise HTTPException(status_code=404, detail="Usuário não encontrado")
            
            return UserResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar usuário: {str(e)}")
    finally:
        conn.close()

@router.post("/athletes", response_model=AthleteResponse)
async def create_athlete(athlete: AthleteCreate):
    """Cria um novo atleta"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Verificar se usuário existe
            cur.execute("SELECT id FROM users WHERE id = %s", (athlete.created_by,))
            if not cur.fetchone():
                raise HTTPException(status_code=400, detail="Usuário não encontrado")
            
            # Converter para JSON
            achievements_json = json.dumps(athlete.athlete_data.achievements or [])
            social_media_json = json.dumps(athlete.athlete_data.social_media or {})
            
            # Inserir atleta
            cur.execute("""
                INSERT INTO athletes (
                    name, age, sport, level, height, weight, country, bio,
                    achievements, social_media, wins, losses, ranking_position,
                    recent_performance_score, potential_score, media_exposure_score,
                    created_by
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) RETURNING id, created_at
            """, (
                athlete.athlete_data.name,
                athlete.athlete_data.age,
                athlete.athlete_data.sport.value,
                athlete.athlete_data.level.value,
                athlete.athlete_data.height,
                athlete.athlete_data.weight,
                athlete.athlete_data.country,
                athlete.athlete_data.bio,
                achievements_json,
                social_media_json,
                athlete.performance_metrics.wins,
                athlete.performance_metrics.losses,
                athlete.performance_metrics.ranking_position,
                athlete.performance_metrics.recent_performance_score,
                athlete.performance_metrics.potential_score,
                athlete.performance_metrics.media_exposure_score,
                athlete.created_by
            ))
            
            result = cur.fetchone()
            conn.commit()
            
            return AthleteResponse(
                id=result["id"],
                athlete_data=athlete.athlete_data.dict(),
                performance_metrics=athlete.performance_metrics.dict(),
                created_by=athlete.created_by,
                created_at=result["created_at"]
            )
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao criar atleta: {str(e)}")
    finally:
        conn.close()

@router.get("/athletes", response_model=List[AthleteResponse])
async def list_athletes(
    sport: Optional[SportType] = None,
    level: Optional[AthleteLevel] = None,
    created_by: Optional[int] = None,
    limit: int = 50,
    offset: int = 0
):
    """Lista atletas com filtros opcionais"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Construir query com filtros
            query = """
                SELECT id, name, age, sport, level, height, weight, country, bio,
                       achievements, social_media, wins, losses, ranking_position,
                       recent_performance_score, potential_score, media_exposure_score,
                       created_by, created_at
                FROM athletes WHERE 1=1
            """
            params = []
            
            if sport:
                query += " AND sport = %s"
                params.append(sport.value)
            
            if level:
                query += " AND level = %s"
                params.append(level.value)
            
            if created_by:
                query += " AND created_by = %s"
                params.append(created_by)
            
            query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            
            cur.execute(query, params)
            results = cur.fetchall()
            
            athletes = []
            for result in results:
                # Reconstruir athlete_data
                athlete_data = {
                    "name": result["name"],
                    "age": result["age"],
                    "sport": result["sport"],
                    "level": result["level"],
                    "height": result["height"],
                    "weight": result["weight"],
                    "country": result["country"],
                    "bio": result["bio"],
                    "achievements": result["achievements"] or [],
                    "social_media": result["social_media"] or {}
                }
                
                # Reconstruir performance_metrics
                performance_metrics = {
                    "wins": result["wins"],
                    "losses": result["losses"],
                    "ranking_position": result["ranking_position"],
                    "recent_performance_score": float(result["recent_performance_score"]),
                    "potential_score": float(result["potential_score"]),
                    "media_exposure_score": float(result["media_exposure_score"])
                }
                
                athletes.append(AthleteResponse(
                    id=result["id"],
                    athlete_data=athlete_data,
                    performance_metrics=performance_metrics,
                    created_by=result["created_by"],
                    created_at=result["created_at"]
                ))
            
            return athletes
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao listar atletas: {str(e)}")
    finally:
        conn.close()

@router.get("/athletes/{athlete_id}", response_model=AthleteResponse)
async def get_athlete(athlete_id: int):
    """Busca um atleta por ID"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, age, sport, level, height, weight, country, bio,
                       achievements, social_media, wins, losses, ranking_position,
                       recent_performance_score, potential_score, media_exposure_score,
                       created_by, created_at
                FROM athletes WHERE id = %s
            """, (athlete_id,))
            
            result = cur.fetchone()
            if not result:
                raise HTTPException(status_code=404, detail="Atleta não encontrado")
            
            # Reconstruir athlete_data
            athlete_data = {
                "name": result["name"],
                "age": result["age"],
                "sport": result["sport"],
                "level": result["level"],
                "height": result["height"],
                "weight": result["weight"],
                "country": result["country"],
                "bio": result["bio"],
                "achievements": result["achievements"] or [],
                "social_media": result["social_media"] or {}
            }
            
            # Reconstruir performance_metrics
            performance_metrics = {
                "wins": result["wins"],
                "losses": result["losses"],
                "ranking_position": result["ranking_position"],
                "recent_performance_score": float(result["recent_performance_score"]),
                "potential_score": float(result["potential_score"]),
                "media_exposure_score": float(result["media_exposure_score"])
            }
            
            return AthleteResponse(
                id=result["id"],
                athlete_data=athlete_data,
                performance_metrics=performance_metrics,
                created_by=result["created_by"],
                created_at=result["created_at"]
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar atleta: {str(e)}")
    finally:
        conn.close()

@router.put("/athletes/{athlete_id}/performance")
async def update_athlete_performance(athlete_id: int, metrics: PerformanceMetrics):
    """Atualiza métricas de performance de um atleta"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Verificar se atleta existe
            cur.execute("SELECT id FROM athletes WHERE id = %s", (athlete_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Atleta não encontrado")
            
            # Atualizar métricas
            cur.execute("""
                UPDATE athletes SET
                    wins = %s,
                    losses = %s,
                    ranking_position = %s,
                    recent_performance_score = %s,
                    potential_score = %s,
                    media_exposure_score = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (
                metrics.wins,
                metrics.losses,
                metrics.ranking_position,
                metrics.recent_performance_score,
                metrics.potential_score,
                metrics.media_exposure_score,
                athlete_id
            ))
            
            conn.commit()
            
            return {
                "message": "Métricas de performance atualizadas com sucesso!",
                "athlete_id": athlete_id,
                "updated_metrics": metrics.dict()
            }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar métricas: {str(e)}")
    finally:
        conn.close() 