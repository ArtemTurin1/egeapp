"""
GitHub webhook для автоматического deployment.
"""

import hmac
import hashlib
import subprocess
import os

from fastapi import APIRouter, HTTPException, Request
from config import GITHUB_SECRET, get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["webhook"])


@router.post("/webhook")
async def github_webhook(request: Request):
    """GitHub webhook для автоматического deployment."""
    try:
        body = await request.body()

        # Проверяем подпись
        signature = request.headers.get("X-Hub-Signature-256", "")
        if GITHUB_SECRET:
            expected_signature = "sha256=" + hmac.new(
                GITHUB_SECRET.encode(),
                body,
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(signature, expected_signature):
                logger.error("❌ Invalid GitHub webhook signature")
                raise HTTPException(status_code=401, detail="Invalid signature")

        payload = await request.json()
        event = request.headers.get("X-GitHub-Event", "")

        logger.info("🔔 GitHub webhook received: %s", event)
        logger.info("   Ref: %s", payload.get("ref", "unknown"))

        # Запускаем deployment только для push в main
        deploy_script = os.getenv("DEPLOY_SCRIPT_PATH")
        if event == "push" and payload.get("ref") == "refs/heads/main":
            logger.info("🚀 Triggering deployment...")

            if deploy_script and os.path.exists(deploy_script):
                subprocess.Popen(["/bin/bash", deploy_script])

            return {
                "status": "deployment_triggered",
                "message": "✅ Deployment started",
                "event": event,
            }
        else:
            logger.info("⏭️  Skipping deployment (not main branch push)")
            return {"status": "skipped", "message": "Event skipped", "event": event}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("❌ Webhook error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
