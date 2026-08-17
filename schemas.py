from enum import Enum
from pydantic import BaseModel
from typing import List, Optional, Any

class InteractionType(str, Enum):
    VIEW = "VIEW"
    SEARCH = "SEARCH"
    ADD_TO_CART = "ADD_TO_CART"
    FAVORITE = "FAVORITE"
    PURCHASE = "PURCHASE"

INTERACTION_WEIGHTS = {
    InteractionType.VIEW: 1,
    InteractionType.SEARCH: 2,
    InteractionType.ADD_TO_CART: 5,
    InteractionType.FAVORITE: 7,
    InteractionType.PURCHASE: 10,
}

class User(BaseModel):
    id: Optional[int] = None
    username: str
    attributes: Optional[dict] = {}
    preferred_genres: Optional[List[str]] = None

class UserCreate(BaseModel):
    username: str
    attributes: Optional[dict] = {}
    preferred_genres: Optional[List[str]] = None

class Item(BaseModel):
    id: int
    name: str
    genre: Optional[str] = None
    attributes: Optional[dict] = {}
    recommendation_source: Optional[str] = "unknown"
    score: Optional[float] = 0.0

class ItemArray(BaseModel):
    items: List[Item]

class Error(BaseModel):
    code: str
    message: str

class PreferenceInput(BaseModel):
    userId: int
    itemId: int
    interactionType: InteractionType