import requests
import logging
import os
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import certifi

load_dotenv()

logger = logging.getLogger(__name__)

class PaystackHandler:
    def __init__(self):
        self.secret_key = os.getenv('PAYSTACK_SECRET_KEY')
        self.base_url = "https://api.paystack.co"
        self.verify_ssl = True
        disable_verify = os.getenv('PAYSTACK_DISABLE_TLS_VERIFY', 'false').lower() in ['1', 'true', 'yes']
        if disable_verify:
            logger.warning("PAYSTACK_DISABLE_TLS_VERIFY is enabled. SSL verification is disabled. Use only for local debugging!")
            self.verify_ssl = False

        # Prepare a resilient HTTP session with retries and CA bundle
        self.session = requests.Session()
        retries = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)
        
        self._validate_and_test_connection()

    def _validate_and_test_connection(self):
        """Validate secret key and test Paystack connection"""
        if not self.secret_key:
            raise ValueError("PAYSTACK_SECRET_KEY not found in environment variables!")
        
        if not self.secret_key.startswith('sk_'):
            raise ValueError("Invalid Paystack secret key format! Secret key should start with 'sk_'")
        
        # Test the connection
        if not self._test_connection():
            raise ConnectionError("Failed to connect to Paystack API! Check your secret key and internet connection.")
        
        logger.info("SUCCESS: Paystack connection validated successfully")

    def _test_connection(self):
        """Test connection to Paystack API"""
        url = f"{self.base_url}/bank"
        headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json"
        }
        
        try:
            response = self.session.get(
                url,
                headers=headers,
                timeout=10,
                verify=(certifi.where() if self.verify_ssl else False),
            )
            if response.status_code == 200:
                return True
            else:
                logger.error(f"Paystack API test failed with status {response.status_code}: {response.text}")
                return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack connection test failed: {e}")
            return False

    def initialize_payment(self, email, amount, reference, metadata=None, callback_url=None):
        """Initialize a payment with Paystack"""
        url = f"{self.base_url}/transaction/initialize"
        
        headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "email": email,
            "amount": amount,  # Amount in kobo
            "reference": reference,
            "currency": "NGN",
        }
        
        # Only add callback_url if it's a valid URL
        if callback_url:
            data["callback_url"] = callback_url
        
        if metadata:
            data["metadata"] = metadata
        
        logger.info(f"Initializing payment: {reference} for {amount} kobo")
        logger.info(f"Payment data being sent: {data}")  # Added detailed logging
        
        try:
            response = self.session.post(
                url,
                json=data,
                headers=headers,
                timeout=30,
                verify=(certifi.where() if self.verify_ssl else False),
            )
            
            logger.info(f"Paystack response status: {response.status_code}")
            logger.info(f"Paystack response body: {response.text}")  # Added response body logging
            
            if response.status_code != 200:
                logger.error(f"Paystack API error {response.status_code}: {response.text}")
                return None
            
            result = response.json()
            
            if result["status"]:
                logger.info(f"Payment initialized successfully: {reference}")
                return result["data"]
            else:
                logger.error(f"Payment initialization failed: {result.get('message')}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error("Paystack API timeout - request took too long")
            return None
        except requests.exceptions.SSLError as e:
            logger.error(f"Paystack API SSL error - TLS handshake failed: {e}. "
                         f"Try: update certifi (pip install -U certifi), ensure system time is correct, and network allows TLS 1.2+.")
            return None
        except requests.exceptions.ConnectionError:
            logger.error("Paystack API connection error - check internet connection")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack API error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during payment initialization: {e}")
            return None
    
    def verify_payment(self, reference):
        """Verify a payment with Paystack"""
        # Guard against placeholder/invalid references
        if not reference or str(reference).strip().lower() in {"reference", "<reference>", "ref", ""}:
            logger.warning("Paystack verify called with an invalid reference; ignoring.")
            return False

        url = f"{self.base_url}/transaction/verify/{reference}"
        
        headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json"
        }
        
        try:
            response = self.session.get(
                url,
                headers=headers,
                timeout=20,
                verify=(certifi.where() if self.verify_ssl else False),
            )

            if response.status_code != 200:
                # Do not raise; just warn and treat as not verified
                logger.warning(f"Paystack verify returned {response.status_code} for {reference}")
                return False

            result = response.json()
            if result.get("status") and result.get("data", {}).get("status") == "success":
                logger.info(f"Payment verified: {reference}")
                return True
            else:
                logger.info(f"Payment not successful: {reference}")
                return False

        except requests.exceptions.SSLError as e:
            logger.error(f"Payment verification SSL error: {e}. "
                         f"Consider updating certifi and ensuring TLS 1.2 is supported by your environment.")
            return False
        except requests.exceptions.RequestException as e:
            logger.warning(f"Payment verification request error: {e}")
            return False
    
    def get_transaction(self, reference):
        """Get transaction details"""
        url = f"{self.base_url}/transaction/verify/{reference}"
        
        headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json"
        }
        
        try:
            response = self.session.get(
                url,
                headers=headers,
                timeout=20,
                verify=(certifi.where() if self.verify_ssl else False),
            )

            if response.status_code != 200:
                logger.warning(f"Transaction fetch returned {response.status_code} for {reference}")
                return None

            result = response.json()
            if result.get("status"):
                return result.get("data")
            return None

        except requests.exceptions.SSLError as e:
            logger.error(f"Transaction fetch SSL error: {e}")
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"Transaction fetch error: {e}")
            return None
