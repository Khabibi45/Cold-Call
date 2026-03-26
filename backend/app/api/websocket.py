"""
WebSocket temps reel — Diffuse les resultats du scraper aux clients connectes.
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    """Gere les connexions WebSocket actives."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accepte et enregistre une nouvelle connexion WebSocket."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket connecte (%d clients actifs)", len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        """Retire une connexion WebSocket deconnectee."""
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass
        logger.info("WebSocket deconnecte (%d clients actifs)", len(self.active_connections))

    async def broadcast(self, data: dict):
        """Envoie des donnees JSON a tous les clients connectes."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception:
                disconnected.append(connection)

        # Nettoyer les connexions mortes
        for conn in disconnected:
            try:
                self.active_connections.remove(conn)
            except ValueError:
                pass


# Instance globale du manager (importee par scraper.py)
manager = ConnectionManager()


@router.websocket("/ws/scraper")
async def scraper_websocket(websocket: WebSocket):
    """WebSocket pour recevoir les resultats du scraper en temps reel."""
    await manager.connect(websocket)
    try:
        while True:
            # Garder la connexion ouverte, recevoir des commandes si besoin
            data = await websocket.receive_text()
            # Ping/pong keepalive
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
