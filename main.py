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
from endpoints import router as router_endpoints
from endpoints_soroban import router as soroban_router
import os

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

@app.get("/")
async def root():
    return {"message": "TrackTrade API", "status": "healthy", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow(),
        "version": "1.0.0"
    }

# app.include_router(router_endpoints)
app.include_router(soroban_router)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", 8000)),
        reload=os.getenv("API_RELOAD", "false").lower() == "true"
    )