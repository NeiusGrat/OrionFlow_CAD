"""
Onshape API Client - Handles communication with Onshape REST API.

Enables "Live CAD" by pushing generated FeatureScript to an Onshape FeatureStudio.
"""
import os
import base64
import hmac
import hashlib
import string
import random
import time
import logging
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class OnshapeClient:
    """
    Minimal Onshape API Client.
    Authentication: API Keys (Access/Secret)
    """
    
    BASE_URL = "https://cad.onshape.com"
    
    def __init__(self, access_key: Optional[str] = None, secret_key: Optional[str] = None):
        self.access_key = access_key or os.getenv("ONSHAPE_ACCESS_KEY")
        self.secret_key = secret_key or os.getenv("ONSHAPE_SECRET_KEY")
        
        if not self.access_key or not self.secret_key:
            logger.warning("Onshape API keys not found. Live sync will be disabled.")
            
    def is_configured(self) -> bool:
        return bool(self.access_key and self.secret_key)

    def _make_auth_headers(self, method: str, path: str, query: Dict = {}, headers: Dict = {}) -> Dict:
        """Sign request for Onshape API."""
        if not self.is_configured():
            return {}
            
        access_key = self.access_key.encode('utf-8')
        secret_key = self.secret_key.encode('utf-8')
        
        # Nonce and Date
        nonce = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(25))
        date_str = requests.utils.formatdate(usegmt=True)
        
        # Signature Construction
        # https://onshape-public.github.io/docs/auth/#api-keys
        # (method + \n + nonce + \n + date + \n + content-type + \n + path + \n + query + \n)
        
        ctype = headers.get('Content-Type', 'application/json')
        q_str = "&".join([f"{k}={v}" for k,v in query.items()])
        
        msg = (method.upper() + '\n' + nonce + '\n' + date_str + '\n' + 
               ctype + '\n' + path + '\n' + q_str + '\n').lower().encode('utf-8')
               
        signature = base64.b64encode(hmac.new(secret_key, msg, digestmod=hashlib.sha256).digest()).decode('utf-8')
        
        return {
            'On-Nonce': nonce,
            'Date': date_str,
            'Authorization': f"On {self.access_key}:HmacSHA256:{signature}",
            'Content-Type': ctype
        }

    def update_featurescript(
        self, 
        did: str, 
        wid: str, 
        eid: str, 
        script_content: str
    ) -> bool:
        """
        Update the content of a FeatureStudio tab.
        
        Args:
            did: Document ID
            wid: Workspace ID
            eid: Element ID (FeatureStudio)
            script_content: The full FeatureScript code
            
        Returns:
            True if successful
        """
        if not self.is_configured():
            return False
            
        logger.info(f"Pushing FeatureScript to Onshape: {did}/{wid}/{eid}")
        
        path = f"/api/featurestudios/d/{did}/w/{wid}/e/{eid}"
        
        # Payload for updating FeatureStudio contents
        payload = {
            "contents": script_content,
            "lines": [] # Optional: send as lines
        }
        
        headers = {'Content-Type': 'application/json'}
        headers.update(self._make_auth_headers('POST', path, {}, headers))
        
        try:
            # Note: The endpoint to update FS is strictly "update" or "set contents"
            # Getting exact endpoint right is tricky without docs.
            # Usually: POST /api/featurestudios/d/{did}/w/{wid}/e/{eid} with 'contents' body updates it.
            res = requests.post(f"{self.BASE_URL}{path}", json=payload, headers=headers)
            
            if res.status_code == 200:
                logger.info("Onshape push successful")
                return True
            else:
                logger.error(f"Onshape push failed: {res.status_code} - {res.text}")
                return False
                
        except Exception as e:
            logger.error(f"Onshape connection error: {e}")
            return False

    def update_variables(
        self,
        did: str,
        wid: str,
        eid: str,
        variables: Dict[str, float]
    ) -> bool:
        """
        Update variables in a PartStudio (Step 6).
        
        Note: This usually requires a PartStudio element ID, NOT the FeatureStudio.
        """
        # Implementation for Step 6 (Variable Sync)
        # Assuming PartStudio API: /api/variables/...
        # Simplified: We might just regenerate the FeatureScript with new defaults
        # since our compiler embeds params as defaults.
        # But for "Real-time sync" we might want to set configuration inputs.
        pass
