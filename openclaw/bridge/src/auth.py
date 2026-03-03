"""
X-Bridge-Token authentication. M1.7.
"""
from fastapi import Header, HTTPException, status

from src.config import settings


def validate_bridge_token(x_bridge_token: str = Header(..., alias="X-Bridge-Token")) -> str:
    if not x_bridge_token or x_bridge_token != settings.BRIDGE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bridge token",
        )
    return x_bridge_token
