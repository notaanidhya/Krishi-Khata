from pydantic import BaseModel, Field

class RegisterRequest(BaseModel):
    device_id: str = Field(..., description="Unique device identifier")
    pin: str = Field(..., min_length=4, max_length=6, description="User PIN code")
    display_name: str = Field(..., description="User's display name")

class LoginRequest(BaseModel):
    username: str = Field(..., description="User's display name")
    pin: str = Field(..., min_length=4, max_length=6, description="User PIN code")

class AuthResponse(BaseModel):
    token: str
    user: dict
    device_id: str = None
