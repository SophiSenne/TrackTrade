from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from stellar_sdk import Server, Keypair, TransactionBuilder, Network, Asset
from stellar_sdk.exceptions import Ed25519PublicKeyInvalidError, BadRequestError
import httpx
import json
import uvicorn
from decimal import Decimal
import asyncio
from endpoints import router
from database_endpoints import router as db_router

# Configuração da aplicação
app = FastAPI(
    title="TrackTrade",
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

# Incluir routers
app.include_router(router)  # Endpoints originais
app.include_router(db_router, prefix="/api/v1")  # Novos endpoints com prefixo

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)