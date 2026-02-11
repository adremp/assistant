"""HTTP handlers - FastAPI routes for health check and OAuth callback."""

import logging

from aiogram import Bot
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pkg.token_storage import TokenStorage

from core.config import Settings
from core.services.auth_service import AuthService

logger = logging.getLogger(__name__)


def setup_routes(app: FastAPI) -> None:
    """Register HTTP routes on the FastAPI app."""

    @app.get("/health")
    async def health_check():
        return {"status": "ok"}

    @app.get("/oauth/callback")
    async def oauth_callback(request: Request, code: str, state: str):
        auth_service: AuthService = request.app.state.workflow_data["auth_service"]
        bot: Bot = request.app.state.bot

        try:
            success, user_id = await auth_service.handle_callback(code, state)

            if success and user_id:
                await bot.send_message(
                    user_id,
                    "✅ Авторизация прошла успешно! Теперь вы можете использовать Google Calendar и Tasks.",
                )

                return HTMLResponse(
                    content="""
                    <html>
                    <head><title>Авторизация</title></head>
                    <body style="font-family: sans-serif; text-align: center; margin-top: 50px;">
                        <h1>✅ Успешно!</h1>
                        <p>Авторизация завершена. Вернитесь в Telegram.</p>
                    </body>
                    </html>
                    """,
                    status_code=200,
                )
            else:
                return HTMLResponse(
                    content="<h1>Ошибка авторизации</h1>",
                    status_code=400,
                )

        except Exception as e:
            logger.error(f"OAuth callback error: {e}")
            return HTMLResponse(
                content=f"<h1>Ошибка</h1><p>{str(e)}</p>",
                status_code=500,
            )
