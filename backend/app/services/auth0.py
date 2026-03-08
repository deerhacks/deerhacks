import logging
import httpx
import base64
import urllib.parse
from email.message import EmailMessage
from typing import Optional, Dict, Any
from app.core.config import settings

logger = logging.getLogger(__name__)

class Auth0Service:
    def __init__(self):
        self.domain = settings.AUTH0_DOMAIN
        self.client_id = settings.AUTH0_CLIENT_ID
        self.client_secret = settings.AUTH0_CLIENT_SECRET
        self.audience = settings.AUTH0_AUDIENCE
        
    async def get_management_token(self) -> Optional[str]:
        """Fetch a Machine-to-Machine token for the Auth0 Management API."""
        if not all([self.domain, self.client_id, self.client_secret]):
            logger.warning("Auth0 configuration missing. Cannot fetch management token.")
            return None
            
        url = f"https://{self.domain}/oauth/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "audience": f"https://{self.domain}/api/v2/",
            "grant_type": "client_credentials"
        }
        
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json().get("access_token")
        except Exception as e:
            logger.error(f"Failed to get Auth0 Management token: {e}")
            return None

    async def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """Retrieve user metadata from Auth0 to personalize agent weights."""
        if not user_id:
            return {}

        token = await self.get_management_token()
        if not token:
            return {}

        safe_user_id = urllib.parse.quote(user_id)
        url = f"https://{self.domain}/api/v2/users/{safe_user_id}"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                user_data = resp.json()
                return {
                    "user_id": user_data.get("user_id"),
                    "email": user_data.get("email"),
                    "name": user_data.get("name"),
                    "picture": user_data.get("picture"),
                    "app_metadata": user_data.get("app_metadata", {}),
                    "user_metadata": user_data.get("user_metadata", {}),
                }
        except Exception as e:
            logger.error(f"Failed to fetch user profile for {user_id}: {e}")
            return {}

    async def update_app_metadata(self, user_id: str, app_metadata: Dict[str, Any]) -> bool:
        """Update a user's app_metadata in Auth0 (merges with existing data)."""
        if not user_id:
            return False

        token = await self.get_management_token()
        if not token:
            return False

        safe_user_id = urllib.parse.quote(user_id)
        url = f"https://{self.domain}/api/v2/users/{safe_user_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.patch(url, json={"app_metadata": app_metadata}, headers=headers)
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Failed to update app_metadata for {user_id}: {e}")
            return False

    async def get_idp_token(self, user_id: str, provider: str = "google-oauth2") -> Optional[str]:
        """Retrieve a third-party Identity Provider token (e.g., Google Calendar) via Token Vault."""
        if not user_id:
            return None
            
        token = await self.get_management_token()
        if not token:
            return None
            
        safe_user_id = urllib.parse.quote(user_id)
        url = f"https://{self.domain}/api/v2/users/{safe_user_id}"
        headers = {"Authorization": f"Bearer {token}"}
        
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                user_data = resp.json()
                identities = user_data.get("identities", [])
                
                # Find the requested identity provider
                for ext_id in identities:
                    if ext_id.get("provider") == provider:
                        return ext_id.get("access_token")
                        
                logger.warning(f"No active {provider} identity found for {user_id}")
                return None
        except Exception as e:
            logger.error(f"Failed to fetch {provider} token from Auth0 Vault: {e}")
            return None

    async def trigger_ciba_auth(self, user_id: str, message: str) -> Optional[str]:
        """
        Trigger an Asynchronous Authorization (CIBA) push notification to the user's device.
        Returns an 'auth_req_id' string if successful, which must be polled later.
        """
        if not all([self.domain, self.client_id, self.client_secret]):
            return None
            
        url = f"https://{self.domain}/oauth/bc-authorize"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "audience": self.audience,
            "login_hint": user_id, 
            "binding_message": message
        }
        
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, data=payload)
                resp.raise_for_status()
                return resp.json().get("auth_req_id")
        except Exception as e:
            logger.error(f"Failed to trigger CIBA for {user_id}: {e}")
            return None

    async def poll_ciba_status(self, auth_req_id: str) -> Dict[str, Any]:
        """
        Poll the status of a pending CIBA authorization.
        Returns a dictionary with status: "pending", "approved", or "rejected".
        """
        if not all([self.domain, self.client_id, self.client_secret]):
            return {"status": "error", "detail": "Missing Auth0 Config"}
            
        url = f"https://{self.domain}/oauth/token"
        payload = {
            "grant_type": "urn:openid:params:grant-type:ciba",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "auth_req_id": auth_req_id
        }
        
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, data=payload)
                
                if resp.status_code == 200:
                    # Token granted = Approved by user
                    return {"status": "approved", "access_token": resp.json().get("access_token")}
                    
                # 400 Bad Request indicates it's still pending, rejected, or expired
                err_data = resp.json()
                error_type = err_data.get("error")
                
                if error_type == "authorization_pending":
                    return {"status": "pending"}
                elif error_type == "access_denied":
                    return {"status": "rejected", "detail": "User denied the request"}
                elif error_type == "expired_token":
                    return {"status": "error", "detail": "CIBA request expired"}
                else:
                    return {"status": "error", "detail": error_type}
                    
        except Exception as e:
            logger.error(f"CIBA polling failed: {e}")
            return {"status": "error", "detail": str(e)}

    async def send_gmail_message(self, token: str, recipient: str, subject: str, html_body: str) -> bool:
        """
        Send an email via the Gmail API using an OAuth2 token retrieved from Auth0's Token Vault.
        """
        try:
            # 1. Construct the MIME message
            msg = EmailMessage()
            msg["To"] = recipient
            msg["Subject"] = subject
            msg.set_content(html_body, subtype="html")
            
            # 2. Base64url encode the raw byte string (required by Gmail API)
            raw_msg = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            
            # 3. Fire the POST request to Gmail
            url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            body = {
                "raw": raw_msg
            }
            
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                logger.info(f"Successfully sent automated Gmail to {recipient}!")
                return True
                
        except httpx.HTTPError as he:
            logger.error(f"HTTP Error sending Gmail: {he.response.text if hasattr(he, 'response') else he}")
            return False
        except Exception as e:
            logger.error(f"Failed to send automated Gmail: {e}")
            return False

# Export an instance
auth0_service = Auth0Service()
