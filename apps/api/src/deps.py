"""
FastAPI dependencies: DB session, current user.
M1.3. Reference: ImplementationPlan.md Section 3.1.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_session

DbSession = Annotated[AsyncSession, Depends(get_session)]
