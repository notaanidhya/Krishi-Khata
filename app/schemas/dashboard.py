from typing import List
from pydantic import BaseModel

class MandiPrice(BaseModel):
    commodity: str
    variety: str
    min_price: float
    max_price: float
    modal_price: float
    arrival_date: str

class MandiPricesResponse(BaseModel):
    last_updated: str
    prices: List[MandiPrice]
