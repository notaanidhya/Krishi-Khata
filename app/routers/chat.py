"""
Community Chat routes — REST endpoints + WebSocket for real-time messaging.

Endpoints:
  GET  /chat/history    — last 50 messages
  POST /chat/upload     — image upload, returns static URL
  WS   /ws/chat         — real-time bidirectional chat
"""

import os
import json
import uuid
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from typing import List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, UploadFile, File, Depends, HTTPException, status
from sqlalchemy.orm import Session
import jwt

from app.database import get_db, SessionLocal
from app.models.chat import CommunityMessage
from app.schemas.chat import ChatMessageResponse
from app.config import settings
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


# ═══════════════════════════════════════════════════════════════
#  WEBSOCKET CONNECTION MANAGER
# ═══════════════════════════════════════════════════════════════

class ConnectionManager:
    """Tracks active WebSocket connections and broadcasts messages."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        self.active_connections.append(websocket)
        logger.info(f"WS connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WS disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Send a message dict to every connected client."""
        payload = json.dumps(message)
        disconnected = []
        for conn in self.active_connections:
            try:
                await conn.send_text(payload)
            except Exception:
                disconnected.append(conn)
        # Clean up broken connections
        for conn in disconnected:
            try:
                self.active_connections.remove(conn)
            except ValueError:
                pass


manager = ConnectionManager()


# ═══════════════════════════════════════════════════════════════
#  REST ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@router.get("/history", response_model=List[ChatMessageResponse])
async def get_chat_history(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Return the last 50 community messages, oldest first."""
    messages = (
        db.query(CommunityMessage)
        .order_by(CommunityMessage.created_at.desc())
        .limit(50)
        .all()
    )
    # Reverse so oldest is first (chat order)
    messages.reverse()
    return [msg.to_dict() for msg in messages]


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload an image for the community chat.
    Returns the static URL to embed in a chat message.
    """
    # Validate extension
    ext = Path(file.filename).suffix.lower() if file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{ext}' not allowed. Use: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Read and validate size
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)} MB",
        )

    # Save with unique filename
    unique_name = f"{uuid.uuid4().hex}{ext}"
    filepath = UPLOAD_DIR / unique_name
    with open(filepath, "wb") as f:
        f.write(contents)

    return {"url": f"/uploads/{unique_name}"}


# ═══════════════════════════════════════════════════════════════
#  WEBSOCKET ENDPOINT
# ═══════════════════════════════════════════════════════════════

@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    Real-time community chat WebSocket.
    Authenticates via first-message payload over the socket.
    """
    await websocket.accept()

    try:
        raw_auth = await asyncio.wait_for(websocket.receive_text(), timeout=3.0)
        auth_data = json.loads(raw_auth)
        
        if auth_data.get("type") != "auth":
            return await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            
        token = auth_data.get("token")
        if not token:
            if not settings.ENABLE_DEV_BYPASS:
                return await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        else:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
            uid = payload.get("uid")
            if not uid:
                return await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                
    except asyncio.TimeoutError:
        logger.warning("WebSocket authentication timed out")
        return await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    except (json.JSONDecodeError, jwt.ExpiredSignatureError, jwt.InvalidTokenError) as e:
        logger.warning(f"WebSocket auth failed: {e}")
        return await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    except Exception as e:
        logger.error(f"Unexpected error during WS auth: {e}", exc_info=True)
        return await websocket.close(code=status.WS_1011_INTERNAL_ERROR)

    await manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"error": "Invalid JSON"}))
                continue

            # Ignore duplicate auth payloads safely
            if data.get("type") == "auth":
                continue

            # Validate required fields
            device_id = (data.get("device_id") or "").strip()
            sender_name = (data.get("sender_name") or "").strip()
            content = (data.get("content") or "").strip() or None
            image_url = (data.get("image_url") or "").strip() or None

            if not device_id or not sender_name:
                await websocket.send_text(json.dumps({"error": "device_id and sender_name are required"}))
                continue

            if not content and not image_url:
                await websocket.send_text(json.dumps({"error": "Message must have content or image_url"}))
                continue

            # Save to database
            db = SessionLocal()
            try:
                msg = CommunityMessage(
                    device_id=device_id,
                    sender_name=sender_name,
                    content=content,
                    image_url=image_url,
                    created_at=datetime.utcnow(),
                )
                db.add(msg)
                db.commit()
                db.refresh(msg)
                saved = msg.to_dict()
            except Exception as db_err:
                logger.error(f"DB error saving chat message: {db_err}")
                db.rollback()
                await websocket.send_text(json.dumps({"error": "Failed to save message"}))
                continue
            finally:
                db.close()

            # Broadcast to all connected clients
            await manager.broadcast(saved)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            manager.disconnect(websocket)
        except ValueError:
            pass
