# -*- coding: utf-8 -*-
import sys
import io
# Set UTF-8 encoding for stdout/stderr to handle emojis on Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from flask import Flask, render_template, jsonify, send_from_directory
import time
import logging
from logging.handlers import RotatingFileHandler
import os
from datetime import datetime
import copy
from fusion_solar_py.client import FusionSolarClient
from fusion_solar_py.exceptions import FusionSolarException
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Configure logging with timestamps and detailed formatting
# Create logs directory if it doesn't exist
logs_dir = 'logs'
if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)

# Create formatter
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Console handler (stdout)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

# File handler with rotation (10MB per file, keep 5 backup files)
log_file = os.path.join(logs_dir, 'app.log')
file_handler = RotatingFileHandler(
    log_file,
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)

# Configure root logger with both handlers
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
# Clear any existing handlers to avoid duplicates
root_logger.handlers.clear()
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

# Get logger for this module
_LOGGER = logging.getLogger(__name__)

# Configure fusion_solar_py logger to capture CAPTCHA events
fusion_solar_logger = logging.getLogger('fusion_solar_py.client')
fusion_solar_logger.setLevel(logging.INFO)

# Create a custom handler to intercept CAPTCHA-related messages from fusion_solar_py
class CaptchaMessageHandler(logging.Handler):
    """Custom handler to detect and log CAPTCHA-related messages from fusion_solar_py"""
    def emit(self, record):
        try:
            msg = record.getMessage()
            msg_lower = msg.lower()
            
            # Check for CAPTCHA-related keywords
            captcha_keywords = ['captcha', 'solving captcha', 'verifycode', 'verification', 'solving', 'prevalidverify']
            if any(keyword in msg_lower for keyword in captcha_keywords):
                formatted_msg = self.format(record)
                _LOGGER.info(f"[CAPTCHA] 🔐 CAPTCHA detected from fusion_solar_py: {msg}")
                print(f"🔐 [CAPTCHA] {msg}")
        except Exception:
            # Don't let handler errors break logging
            self.handleError(record)

# Add the custom handler to fusion_solar_py logger
captcha_handler = CaptchaMessageHandler()
captcha_handler.setLevel(logging.INFO)
captcha_handler.setFormatter(formatter)
fusion_solar_logger.addHandler(captcha_handler)

# Also add a filter to catch any CAPTCHA messages
class CaptchaLogFilter(logging.Filter):
    """Filter to detect CAPTCHA-related log messages"""
    def filter(self, record):
        msg = record.getMessage().lower()
        if 'captcha' in msg or 'solving' in msg or 'verifycode' in msg:
            # This will be caught by our handler above
            return True
        return True  # Allow all messages

captcha_filter = CaptchaLogFilter()
fusion_solar_logger.addFilter(captcha_filter)

# Detect if running in production (gunicorn) or development
# When gunicorn imports the app, __name__ == "app", not "__main__"
# Also check for environment variable
is_production = os.environ.get('FLASK_ENV') == 'production' or os.environ.get('ENVIRONMENT') == 'production'

app = Flask(__name__)

# Set debug mode based on environment
# In production with gunicorn, debug should be False for security
if is_production:
    app.config['DEBUG'] = False
    app.config['TESTING'] = False
    _LOGGER.info("Running in PRODUCTION mode (debug=False)")
else:
    # Development mode - can use debug=True when running directly
    app.config['DEBUG'] = True
    _LOGGER.info("Running in DEVELOPMENT mode (debug=True)")

# Hybrid approach: Session pool + Data cache (optimized for Raspberry Pi)
# Session pool maintains persistent connections to reduce logins
# Using lazy approach: only check/keepalive when actually fetching data (not proactively)
_session_pool = {}  # account_name -> {"client": client, "last_used": timestamp, "lock": threading.Lock()}
# Note: We don't proactively keepalive. The @logged_in decorator handles session validation.
# Sessions are checked/refreshed only when we fetch data (every 5 min with cache)

# Data cache reduces API calls for data fetching
_data_cache = {
    "data": None,
    "timestamp": 0,
    "lock": threading.Lock()
}
CACHE_DURATION = 5 * 60  # 5 minutes in seconds

# Disconnected plant threshold: change to red if disconnected for more than X hours
DISCONNECTED_RED_THRESHOLD_HOURS = 8  # Hours

# CAPTCHA Configuration
# Path to the captcha model file (relative to app.py location)
CAPTCHA_MODEL_PATH = os.path.join("models", "captcha_huawei.onnx")

#Configuration
accounts = [
    ("DomusSocial", "UpacsDM@2023FNT", "uni004eu5"),  # Porto Solar
    ("AEdP_EDS", "AEdP@2024", "uni003eu5"),  # Parque da Trindade
    ("UPAC_AMIAL", "amial2023", "uni003eu5"),  # Agra do Amial
    ("Adeporto", "Tribunal-2030", "uni001eu5"),  # Tribunal
    ("mapadeporto", "info-2030", "uni005eu5"), # MAP funcional
]

def custom_get_station_list(self) -> list:
    """Get all stations with pagination support"""
    all_stations = []
    page_size = 50
    cur_page = 1
    
    while True:
        r = self._session.post(
            url=f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/station/v1/station/station-list",
            json={
                "curPage": cur_page,
                "pageSize": page_size,
                "gridConnectedTime": "",
                "queryTime": self._get_day_start_sec(),
                "timeZone": 2,
                "sortId": "createTime",
                "sortDir": "DESC",
                "locale": "en_US"
            }
        )
        r.raise_for_status()
        obj_tree = r.json()
        if not obj_tree["success"]:
            raise Exception("Failed to retrieve station list")
        
        stations = obj_tree["data"]["list"]
        if not stations:  # No more stations
            break
            
        all_stations.extend(stations)
        
        # Check if there are more pages
        total = obj_tree["data"].get("total", 0)
        total_pages = obj_tree["data"].get("pageCount", 0)
        
        # If we got fewer stations than page_size, we're on the last page
        if len(stations) < page_size:
            break
            
        # If total_pages is provided and we've reached it, stop
        if total_pages > 0 and cur_page >= total_pages:
            break
            
        # If we've fetched all stations based on total count, stop
        if total > 0 and len(all_stations) >= total:
            break
            
        cur_page += 1
    
    print(f"Fetched {len(all_stations)} stations (across {cur_page} page(s))")
    return all_stations

# Monkey-patch the class
FusionSolarClient.get_station_list = custom_get_station_list

'''
accounts = [
    ("ID1", "PASS1", "uni004eu5"),  
    ("ID2", "PASS2", "uni003eu5"),  
    ("ID3", "PASS3", "uni003eu5"),  
    ("ID4", "PASS4", "uni001eu5"),  
    ("ID5", "PASS5", "uni005eu5"), 
]
'''

list_of_plants = [
    ("Escola Básica Fonte da Moura", "0"),
    ("Viveiros Municipais", "0"),
    ("Escola Básica Vilarinha", "0"),
    ("Polícia Municipal do Porto", "0"),
    ("Oficinas Domus", "0"),
    ("Regimento de Sapadores Bombeiros do Porto", "0"),
    ("Escola Básica Corujeira", "0"),
    ("Escola Básica Monte Aventino", "0"),
    ("Escola Básica Lomba", "0"),
    ("Escola Básica Paulo da Gama", "0"),
    ("Escola Básica Fontinha", "0"),
    ("Escola Básica Fernão Magalhães", "0"),
    ("Escola Básica Covelo", "0"),
    ("Escola Básica Viso", "0"),
    ("Escola Básica São João da Foz", "0"),
    ("Escola Básica Campinas", "0"),
    ("Escola Básica Alegria", "0"),
    ("Escola Básica Pasteleira", "0"),
    ("Escola Básica Condominhas", "0"),
    ("Escola Básica Castelos", "0"),
    ("Escola Básica Constituição", "0"),
    ("Escola Básica Torrinha", "0"),
    ("Escola Básica Miosótis", "0"),
    ("Escola Básica Augusto Lessa", "0"),
    ("Escola Básica Bom Pastor", "0"),
    ("Escola Básica Costa Cabral", "0"),
    ("Escola Básica Bom Sucesso", "0"),
    ("Escola Básica São Tomé", "0"),
    ("Escola Básica do Falcão", "0"),    
    ("TEATRO RIVOLI", "0"),
    ("Escola Básica das Antas", "0"),
    ("ETAR DE SOBREIRAS", "0"),
    ("Parque da Trindade", "0"),
    ("Bloco F - N67", "0"),
    ("Bloco E - N15", "0"),
    ("Bloco G - N83", "0"),
    ("Bloco F - N63", "0"),
    ("Bloco E - N29", "0"),
    ("Bloco D - N34", "0"),
    ("Bloco C - N62", "0"),
    ("Bloco C - N58", "0"),
    ("Bloco B - N72", "0"),
    ("Bloco B - N90", "0"),
    ("UPAC Pavilhão da Água e Energia &#x28;Edificio Administrativo&#x29;", "0"),
    ("UPAC Pavilhão da Água e Energia &#x28;Parque da Cidade&#x29;", "0"),
    ("Bloco H - N111", "0"),
    ("Bloco H-N115", "0"),
    ("Bloco A -N142", "0"),
    ("Bloco A -N138", "0"),
    ("Bloco A - N134", "0"),
    ("Escola EB1 Agra do Amial", "0"),
    ("TRP", "0"),
    ("TRP Museu", "0"),
    ("TRP Elevadores", "0"),
    ("MAP UPAC 2", "0"),
    ("MAP UPAC 1", "0"),    
]

@app.route("/")
def index():
    return render_template("index.html")  # This looks in the 'templates/' folder
    
class PowerStatus:
    """Class representing the basic power status"""

    def __init__(
        self,
        current_power_kw: float,
        energy_today_kwh: float = None,
        energy_kwh: float = None,
        **kwargs
    ):
        """Create a new PowerStatus object
        :param current_power_kw: The currently produced power in kW
        :type current_power_kw: float
        :param energy_today_kwh: The total power produced that day in kWh
        :type energy_today_kwh: float
        :param energy_kwh: The total power ever produced
        :type energy_kwh: float
        :param kwargs: Deprecated parameters
        """
        self.current_power_kw = current_power_kw
        self.energy_today_kwh = energy_today_kwh
        self.energy_kwh = energy_kwh

        if 'total_power_today_kwh' in kwargs.keys() and not energy_today_kwh:
            _LOGGER.warning(
                "The parameter 'total_power_today_kwh' is deprecated. Please use "
                "'energy_today_kwh' instead.", DeprecationWarning
            )
            self.energy_today_kwh = kwargs['total_power_today_kwh']

        if 'total_power_kwh' in kwargs.keys() and not energy_kwh:
            _LOGGER.warning(
                "The parameter 'total_power_kwh' is deprecated. Please use "
                "'energy_kwh' instead.", DeprecationWarning
            )
            self.energy_kwh = kwargs['total_power_kwh']

    @property
    def total_power_today_kwh(self):
        """The total power produced that day in kWh"""
        _LOGGER.warning(
            "The parameter 'total_power_today_kwh' is deprecated. Please use "
            "'energy_today_kwh' instead.")
        return self.energy_today_kwh

    @property
    def total_power_kwh(self):
        """The total power ever produced"""
        _LOGGER.warning(
            "The parameter 'total_power_kwh' is deprecated. Please use "
            "'energy_kwh' instead.")
        return self.energy_kwh

    def __repr__(self):
        return (f"PowerStatus(current_power_kw={self.current_power_kw}, "
                f"energy_today_kwh={self.energy_today_kwh}, "
                f"energy_kwh={self.energy_kwh})")

def get_current_plant_data(self, plant_id: str) -> dict:
        """Retrieve the current power status for a specific plant.
        :return: A dict object containing the whole data
        """

        url = f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/station/v1/overview/station-real-kpi"
        params = {
            "stationDn": plant_id,
            "clientTime": round(time.time() * 1000),
            "timeZone": 1,
            "_": round(time.time() * 1000),
        }

        r = self._session.get(url=url, params=params)
        r.raise_for_status()

        # errors in decoding the object generally mean that the login expired
        # this is handeled by @logged_in
        power_obj = r.json()

        if "data" not in power_obj:
            raise FusionSolarException("Failed to retrieve plant data.")

        return power_obj["data"]


def get_plant_stats_yearly(
        self, plant_id: str, query_time: int = None
    ) -> dict:
        """Retrieves the complete plant usage statistics for the current day.
        :param plant_id: The plant's id
        :type plant_id: str
        :param query_time: If set, must be set to 00:00:00 of the day the data should
                           be fetched for. If not set, retrieves the data for the
                           current day.
        :type query_time: int
        :return: _description_
        """
        # set the query time to today
        if not query_time:
            query_time = self._get_day_start_sec()
            
        r = self._session.get(
            url=f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/station/v1/overview/energy-balance",
            params={
                "stationDn": plant_id,
                "timeDim": 6,
                "queryTime": query_time, # TODO: this may have changed to micro-seconds ie. timestamp * 1000
                # dateTime=2024-03-07 00:00:00
                "timeZone": 2,  # 1 in no daylight
                "timeZoneStr": "Europe/Vienna",
                "_": round(time.time() * 1000),
            },
        )
        r.raise_for_status()
        plant_data = r.json()

        if not plant_data["success"] or "data" not in plant_data:
            raise FusionSolarException(
                f"Failed to retrieve plant status for {plant_id}"
            )

        # return the plant data
        return plant_data["data"]
        
def get_plant_stats_monthly(
        self, plant_id: str, query_time: int = None
    ) -> dict:
        """Retrieves the complete plant usage statistics for the current day.
        :param plant_id: The plant's id
        :type plant_id: str
        :param query_time: If set, must be set to 00:00:00 of the day the data should
                           be fetched for. If not set, retrieves the data for the
                           current day.
        :type query_time: int
        :return: _description_
        """
        # set the query time to today
        if not query_time:
            query_time = self._get_day_start_sec()
            
        r = self._session.get(
            url=f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/station/v1/overview/energy-balance",
            params={
                "stationDn": plant_id,
                "timeDim": 5,
                "queryTime": query_time, # TODO: this may have changed to micro-seconds ie. timestamp * 1000
                # dateTime=2024-03-07 00:00:00
                "timeZone": 2,  # 1 in no daylight
                "timeZoneStr": "Europe/Vienna",
                "_": round(time.time() * 1000),
            },
        )
        r.raise_for_status()
        plant_data = r.json()

        if not plant_data["success"] or "data" not in plant_data:
            raise FusionSolarException(
                f"Failed to retrieve plant status for {plant_id}"
            )

        # return the plant data
        return plant_data["data"]


def get_power_status(self) -> PowerStatus:
        """Retrieve the current power status. This is the complete
           summary accross all stations.
        :return: The current status as a PowerStatus object
        """

        url = f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/station/v1/station/total-real-kpi"
        params = {
            "queryTime": round(time.time() * 1000),
            "timeZone": 1,
            "_": round(time.time() * 1000),
        }

        r = self._session.get(url=url, params=params)
        r.raise_for_status()

        # errors in decoding the object generally mean that the login expired
        # this is handeled by @logged_in
        power_obj = r.json()

        power_status = PowerStatus(
            current_power_kw=float( power_obj["data"]["currentPower"] ),
            energy_today_kwh=float( power_obj["data"]["dailyEnergy"] ),
            energy_kwh=float( power_obj["data"]["cumulativeEnergy"] ),
        )

        return power_status

def get_plant_stats(
    self, plant_id: str, query_time: int = None
) -> dict:
    """Retrieves the complete plant usage statistics for the current day.
    :param plant_id: The plant's id
    :type plant_id: str
    :param query_time: If set, must be set to 00:00:00 of the day the data should
                       be fetched for. If not set, retrieves the data for the
                       current day.
    :type query_time: int
    :return: _description_
    """
    # set the query time to today
    if not query_time:
        query_time = self._get_day_start_sec()

    r = self._session.get(
        url=f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/station/v1/overview/energy-balance",
        params={
            "stationDn": plant_id,
            "timeDim": 2,
            "queryTime": query_time, # TODO: this may have changed to micro-seconds ie. timestamp * 1000
            # dateTime=2024-03-07 00:00:00
            "timeZone": 2,  # 1 in no daylight
            "timeZoneStr": "Europe/Vienna",
            "_": round(time.time() * 1000),
        },
    )
    r.raise_for_status()
    plant_data = r.json()

    if not plant_data["success"] or "data" not in plant_data:
        raise FusionSolarException(
            f"Failed to retrieve plant status for {plant_id}"
        )

    # return the plant data
    return plant_data["data"]

def get_inverter_ids(self, plant_id: str) -> list:
    """Get inverter device IDs for a specific plant
    :param plant_id: The plant's id
    :type plant_id: str
    :return: List of inverter device IDs (deviceDn)
    :rtype: list
    """
    inverter_ids = []
    try:
        # Method 1: Try using plant flow to get device IDs
        # Check if get_plant_flow method exists
        if not hasattr(self, 'get_plant_flow'):
            _LOGGER.warning(f"get_plant_flow method not found on client, trying alternative method")
            raise AttributeError("get_plant_flow method not available")
        
        _LOGGER.debug(f"Calling get_plant_flow for plant {plant_id}")
        plant_flow = self.get_plant_flow(plant_id)
        _LOGGER.debug(f"get_plant_flow returned: {type(plant_flow)}")
        
        if not plant_flow or not isinstance(plant_flow, dict):
            _LOGGER.warning(f"get_plant_flow returned invalid data for plant {plant_id}")
            raise ValueError("Invalid plant flow data")
        
        nodes = plant_flow.get('data', {}).get('flow', {}).get('nodes', [])
        _LOGGER.debug(f"Found {len(nodes)} nodes in plant flow for {plant_id}")
        
        for node in nodes:
            # Look for inverter nodes - check name, type, and other fields
            node_name = node.get('name', '').lower()
            node_type = node.get('type', '').lower()
            node_id = node.get('id', '').lower()
            
            # Check if this is an inverter node
            # Check each text field against each keyword
            if any(keyword in text for text in [node_name, node_type, node_id] 
                   for keyword in ['inverter', 'inv']):
                # Get device IDs from this node
                dev_ids = node.get('devIds', [])
                if dev_ids:
                    # Filter out None values before extending
                    valid_dev_ids = [dev_id for dev_id in dev_ids if dev_id]
                    if valid_dev_ids:
                        inverter_ids.extend(valid_dev_ids)
                        _LOGGER.debug(f"Found inverter node: {node_name or node_type or node_id}, devIds: {valid_dev_ids}")
                    else:
                        _LOGGER.warning(f"Inverter node found but all devIds are None or empty: {node_name or node_type or node_id}")
        
        # If no inverters found via plant flow, try alternative method
        if not inverter_ids:
            _LOGGER.info(f"No inverters found via plant flow for {plant_id}, trying alternative method")
            # Method 2: Try using get_device_ids and filter (less precise but may work)
            try:
                if not hasattr(self, 'get_device_ids'):
                    _LOGGER.warning(f"get_device_ids method not found on client")
                    raise AttributeError("get_device_ids method not available")
                
                all_devices = self.get_device_ids()
                _LOGGER.debug(f"get_device_ids returned {len(all_devices)} devices")
                # Filter for inverters - note: this gets all inverters in account, not just this plant
                # But it's a fallback if plant_flow doesn't work
                for device in all_devices:
                    if device.get('type', '').lower() == 'inverter':
                        device_dn = device.get('deviceDn')
                        # Only add if deviceDn exists and is not None
                        if device_dn:
                            inverter_ids.append(device_dn)
                            _LOGGER.debug(f"Found inverter device: {device}")
                        else:
                            _LOGGER.warning(f"Inverter device found but deviceDn is missing or None: {device}")
            except Exception as e2:
                _LOGGER.warning(f"Alternative method also failed for plant {plant_id}: {e2}", exc_info=True)
        
        if inverter_ids:
            _LOGGER.info(f"Found {len(inverter_ids)} inverter(s) for plant {plant_id}: {inverter_ids}")
        else:
            _LOGGER.info(f"No inverters found for plant {plant_id}")
        
        return inverter_ids
    except AttributeError as e:
        _LOGGER.error(f"Method not available when getting inverter IDs for plant {plant_id}: {e}", exc_info=True)
        return []
    except Exception as e:
        _LOGGER.warning(f"Failed to get inverter IDs for plant {plant_id}: {e}", exc_info=True)
        return []

# Monkey-patch additional methods to FusionSolarClient
FusionSolarClient.get_current_plant_data = get_current_plant_data
FusionSolarClient.get_plant_stats_yearly = get_plant_stats_yearly
FusionSolarClient.get_plant_stats_monthly = get_plant_stats_monthly
FusionSolarClient.get_power_status = get_power_status
FusionSolarClient.get_plant_stats = get_plant_stats
FusionSolarClient.get_inverter_ids = get_inverter_ids

# Note: get_alarm_data() already exists in fusion_solar_py library, no monkey-patch needed
# The method is available at: FusionSolarClient.get_alarm_data(device_dn)

error_messages = {
            1: "Instalação Desligada",
            2: "Sem Consumo",
            3: "Sem Produção",
            4: "Erro de Comunicação"
        }


def get_or_create_client(account):
    """
    Get existing client from session pool or create new one.
    Lazy approach: Only checks/creates session when needed (not proactively).
    The @logged_in decorator on API methods will auto-re-authenticate if session expired.
    This reduces processing load on Raspberry Pi devices.
    """
    USER, PASSWORD, SUBDOMAIN = account
    current_time = time.time()
    
    # Initialize session pool entry if it doesn't exist
    if USER not in _session_pool:
        _session_pool[USER] = {
            "client": None,
            "last_used": 0,
            "lock": threading.Lock()
        }
    
    with _session_pool[USER]["lock"]:
        client = _session_pool[USER]["client"]
        last_used = _session_pool[USER]["last_used"]
        
        # Only create new client if we don't have one
        # The @logged_in decorator will handle session validation and re-auth when needed
        if client is None:
            try:
                _LOGGER.info(f"[SESSION] Creating NEW session for account: {USER} (subdomain: {SUBDOMAIN})")
                print(f"🔑 Creating session for {USER}...")
                
                # Log account details (without password for security)
                _LOGGER.debug(f"[SESSION] Account details - USER: '{USER}', SUBDOMAIN: '{SUBDOMAIN}', PASSWORD length: {len(PASSWORD)}")
                _LOGGER.debug(f"[SESSION] USER type: {type(USER)}, SUBDOMAIN type: {type(SUBDOMAIN)}, PASSWORD type: {type(PASSWORD)}")
                _LOGGER.debug(f"[SESSION] USER repr: {repr(USER)}, SUBDOMAIN repr: {repr(SUBDOMAIN)}")
                
                # Initialize client with captcha support if model path is provided
                client_kwargs = {"huawei_subdomain": SUBDOMAIN}
                _LOGGER.debug(f"[SESSION] Initial client_kwargs: {client_kwargs}")
                
                if CAPTCHA_MODEL_PATH:
                    _LOGGER.debug(f"[SESSION] CAPTCHA_MODEL_PATH: '{CAPTCHA_MODEL_PATH}'")
                    _LOGGER.debug(f"[SESSION] CAPTCHA_MODEL_PATH exists: {os.path.exists(CAPTCHA_MODEL_PATH) if CAPTCHA_MODEL_PATH else False}")
                    _LOGGER.debug(f"[SESSION] CAPTCHA_MODEL_PATH absolute: {os.path.abspath(CAPTCHA_MODEL_PATH) if CAPTCHA_MODEL_PATH else 'N/A'}")
                    
                    if os.path.exists(CAPTCHA_MODEL_PATH):
                        try:
                            # Try to get absolute path and verify it's valid
                            abs_path = os.path.abspath(CAPTCHA_MODEL_PATH)
                            _LOGGER.debug(f"[SESSION] CAPTCHA model absolute path: '{abs_path}'")
                            client_kwargs["captcha_model_path"] = abs_path
                            _LOGGER.info(f"[SESSION] CAPTCHA support enabled - using model: {abs_path}")
                            print(f"Using CAPTCHA model: {abs_path}")
                        except Exception as path_error:
                            _LOGGER.error(f"[SESSION] Error processing CAPTCHA model path '{CAPTCHA_MODEL_PATH}': {path_error}", exc_info=True)
                            print(f"⚠️  Error with CAPTCHA model path: {path_error}")
                    else:
                        _LOGGER.warning(f"[SESSION] CAPTCHA model path specified but file not found: {CAPTCHA_MODEL_PATH}")
                        print(f"⚠️  Warning: CAPTCHA model not found at {CAPTCHA_MODEL_PATH}")
                else:
                    _LOGGER.debug(f"[SESSION] No CAPTCHA_MODEL_PATH configured")
                
                _LOGGER.debug(f"[SESSION] Final client_kwargs: {client_kwargs}")
                _LOGGER.info(f"[SESSION] Attempting login for account: {USER}...")
                login_start_time = time.time()
                
                # Track if CAPTCHA was encountered during login
                # The fusion_solar_py library will log "solving captcha and retrying login" if CAPTCHA is needed
                try:
                    _LOGGER.debug(f"[SESSION] Calling FusionSolarClient with USER='{USER}', PASSWORD length={len(PASSWORD)}, kwargs={client_kwargs}")
                    _LOGGER.debug(f"[SESSION] About to create FusionSolarClient instance...")
                    client = FusionSolarClient(USER, PASSWORD, **client_kwargs)
                    _LOGGER.debug(f"[SESSION] FusionSolarClient instance created successfully")
                except OSError as os_error:
                    # OSError with errno 22 is "Invalid argument"
                    error_code = getattr(os_error, 'errno', None)
                    error_msg = str(os_error)
                    _LOGGER.error(f"[SESSION] OSError during login for {USER}: errno={error_code}, message='{error_msg}'", exc_info=True)
                    _LOGGER.error(f"[SESSION] OSError details - USER: '{USER}', SUBDOMAIN: '{SUBDOMAIN}', PASSWORD length: {len(PASSWORD)}")
                    _LOGGER.error(f"[SESSION] OSError details - client_kwargs: {client_kwargs}")
                    if CAPTCHA_MODEL_PATH:
                        _LOGGER.error(f"[SESSION] OSError details - CAPTCHA_MODEL_PATH: '{CAPTCHA_MODEL_PATH}', exists: {os.path.exists(CAPTCHA_MODEL_PATH)}")
                    print(f"❌ OSError during login for {USER}: errno={error_code}, {error_msg}")
                    raise
                except Exception as login_exc:
                    # Check if it's a CAPTCHA-related exception
                    error_msg = str(login_exc)
                    error_type = type(login_exc).__name__
                    _LOGGER.error(f"[SESSION] Exception during login for {USER}: {error_type} - {error_msg}", exc_info=True)
                    _LOGGER.error(f"[SESSION] Exception details - USER: '{USER}', SUBDOMAIN: '{SUBDOMAIN}', PASSWORD length: {len(PASSWORD)}")
                    _LOGGER.error(f"[SESSION] Exception details - client_kwargs: {client_kwargs}")
                    
                    if 'captcha' in error_msg.lower():
                        _LOGGER.warning(f"[CAPTCHA] ⚠️ CAPTCHA encountered during login for {USER}: {login_exc}")
                        print(f"🔐 [CAPTCHA] Encountered during login for {USER}")
                    else:
                        print(f"❌ Exception during login for {USER}: {error_type}: {error_msg}")
                    raise
                
                login_duration = time.time() - login_start_time
                
                # Longer login times (>3s) might indicate CAPTCHA was solved
                if login_duration > 3.0:
                    _LOGGER.info(f"[CAPTCHA] ⚠️ Login took {login_duration:.2f}s for {USER} (may indicate CAPTCHA was solved)")
                    print(f"⚠️ Login took {login_duration:.2f}s (possibly CAPTCHA solving)")
                
                _session_pool[USER]["client"] = client
                _session_pool[USER]["last_used"] = current_time
                _session_pool[USER]["created_at"] = current_time
                _LOGGER.info(f"[SESSION] ✓ Login successful for {USER} (took {login_duration:.2f}s)")
                print(f"Session created successfully ✅ (login took {login_duration:.2f}s)")
            except FusionSolarException as e:
                error_msg = str(e)
                _LOGGER.error(f"[SESSION] FusionSolar API error during login for {USER}: {error_msg}")
                print(f"❌ FusionSolar API error for {USER}: {error_msg}")
                raise
            except OSError as os_error:
                # OSError with errno 22 is "Invalid argument" - often related to file paths or encoding
                error_code = getattr(os_error, 'errno', None)
                error_msg = str(os_error)
                filename = getattr(os_error, 'filename', None)
                _LOGGER.error(f"[SESSION] OSError during login for {USER}: errno={error_code}, message='{error_msg}', filename={filename}", exc_info=True)
                _LOGGER.error(f"[SESSION] OSError context - USER: '{USER}', SUBDOMAIN: '{SUBDOMAIN}', PASSWORD length: {len(PASSWORD)}")
                _LOGGER.error(f"[SESSION] OSError context - client_kwargs: {client_kwargs}")
                if CAPTCHA_MODEL_PATH:
                    _LOGGER.error(f"[SESSION] OSError context - CAPTCHA_MODEL_PATH: '{CAPTCHA_MODEL_PATH}'")
                    _LOGGER.error(f"[SESSION] OSError context - CAPTCHA_MODEL_PATH exists: {os.path.exists(CAPTCHA_MODEL_PATH)}")
                    try:
                        abs_path = os.path.abspath(CAPTCHA_MODEL_PATH)
                        _LOGGER.error(f"[SESSION] OSError context - CAPTCHA_MODEL_PATH absolute: '{abs_path}'")
                    except Exception as path_err:
                        _LOGGER.error(f"[SESSION] OSError context - Could not get absolute path: {path_err}")
                print(f"❌ OSError during login for {USER}: errno={error_code}, {error_msg}")
                if filename:
                    print(f"   Related file: {filename}")
                raise
            except Exception as e:
                error_msg = str(e)
                error_type = type(e).__name__
                error_args = getattr(e, 'args', None)
                _LOGGER.error(f"[SESSION] Failed to create session for {USER} (Error type: {error_type}): {error_msg}", exc_info=True)
                _LOGGER.error(f"[SESSION] Exception details - USER: '{USER}', SUBDOMAIN: '{SUBDOMAIN}', PASSWORD length: {len(PASSWORD)}")
                _LOGGER.error(f"[SESSION] Exception details - client_kwargs: {client_kwargs}")
                _LOGGER.error(f"[SESSION] Exception args: {error_args}")
                if CAPTCHA_MODEL_PATH:
                    _LOGGER.error(f"[SESSION] Exception context - CAPTCHA_MODEL_PATH: '{CAPTCHA_MODEL_PATH}', exists: {os.path.exists(CAPTCHA_MODEL_PATH)}")
                print(f"❌ Erro ao criar sessão para {USER}: {error_type}: {error_msg}")
                raise
        else:
            # Reusing existing session from pool
            session_age = current_time - last_used
            created_at = _session_pool[USER].get("created_at", last_used)
            total_session_age = current_time - created_at
            
            _LOGGER.info(f"[SESSION] Reusing existing session for {USER} (last used: {session_age:.1f}s ago, total age: {total_session_age:.1f}s)")
            print(f"♻️  Reusing session for {USER} (last used {session_age:.0f}s ago)")
        
        # Update last used timestamp
        _session_pool[USER]["last_used"] = current_time
        
        # Lazy keepalive: Only call keep_alive() when we're about to use the session
        # This is more efficient than proactive keepalive, but ensures session stays alive
        # Since we fetch data every 5 minutes (cache), this is sufficient
        _LOGGER.debug(f"[KEEPALIVE] Calling keep_alive() for {USER}...")
        keepalive_start_time = time.time()
        try:
            # The @logged_in decorator will handle re-auth if session expired
            # But we also call keep_alive() to explicitly maintain the session
            # This is safe because @logged_in will re-auth if keep_alive() fails
            client.keep_alive()
            keepalive_duration = time.time() - keepalive_start_time
            _LOGGER.info(f"[KEEPALIVE] ✓ Keep-alive successful for {USER} (took {keepalive_duration:.3f}s)")
        except FusionSolarException as keepalive_error:
            keepalive_duration = time.time() - keepalive_start_time
            error_msg = str(keepalive_error)
            # If keep_alive fails, @logged_in decorator will handle it on next API call
            _LOGGER.warning(f"[KEEPALIVE] ✗ Keep-alive FAILED for {USER} (took {keepalive_duration:.3f}s): {error_msg}")
            _LOGGER.warning(f"[KEEPALIVE] Session for {USER} may have expired. @logged_in decorator will re-authenticate on next API call.")
            print(f"⚠️  Keep-alive failed for {USER} (session may have expired, will renew on next request)")
            # No need to handle here - let the decorator do its job
            pass
        except Exception as keepalive_error:
            keepalive_duration = time.time() - keepalive_start_time
            error_type = type(keepalive_error).__name__
            error_msg = str(keepalive_error)
            _LOGGER.warning(f"[KEEPALIVE] ✗ Keep-alive exception for {USER} ({error_type}, took {keepalive_duration:.3f}s): {error_msg}")
            _LOGGER.warning(f"[KEEPALIVE] Session for {USER} will be renewed by @logged_in decorator on next API call.")
            print(f"⚠️  Keep-alive error for {USER}: {error_type}: {error_msg}")
            # No need to handle here - let the decorator do its job
            pass
        
        return client

def process_account(account):
    USER, PASSWORD, SUBDOMAIN = account
    result = {
        "production": 0.0,
        "consumption": 0.0,
        "grid": 0.0,
        "plants": 0,
        "statuses": [],
        "alerts": [],
        "summed_production": None,
        "summed_consumption": None,
        "summed_self_consumption": None,
        "summed_overflow": None,
    }

    try:
        try:
            _LOGGER.info(f"Processing account: {USER} (subdomain: {SUBDOMAIN})")
            client = get_or_create_client(account)
        except Exception as login_error:
            error_msg = str(login_error)
            error_type = type(login_error).__name__
            _LOGGER.error(f"Login failed for account {USER}: {error_type} - {error_msg}", exc_info=True)
            print(f"❌ Erro no login da conta {USER}: {error_type}: {error_msg}")
            result["alerts"].append(f"🔴 Conta {USER} - Erro no login: {error_msg[:100]}")
            return result

        _LOGGER.info(f"Fetching station list for account: {USER}")
        try:
            plants = client.get_station_list()
            _LOGGER.info(f"Successfully retrieved station list for {USER}")
        except Exception as station_error:
            error_msg = str(station_error)
            error_type = type(station_error).__name__
            _LOGGER.error(f"Failed to fetch station list for {USER}: {error_type} - {error_msg}", exc_info=True)
            print(f"❌ Erro ao buscar lista de estações para {USER}: {error_type}: {error_msg}")
            result["alerts"].append(f"🔴 Conta {USER} - Erro ao buscar estações: {error_msg[:100]}")
            return result
        if not plants:
            try:
                print(f"⚠️ Nenhuma instalação encontrada para {USER}")
            except (UnicodeEncodeError, UnicodeError):
                print(f"Nenhuma instalação encontrada para {USER}")
            # Add warning to alerts
            result["alerts"].append(f"⚠️ Conta {USER} - Nenhuma instalação encontrada")
            # Don't log out - keep session alive for reuse
            return result

        number_plants = len(plants)
        print(f"Found {number_plants} stations for account {USER}")
        installed_capacity_map = {p["name"]: float(p["installedCapacity"]) for p in plants}

        for i, plant in enumerate(plants, start=1):
            plant_id = plant['dn']
            plant_name = plant["name"]
            installed_capacity = installed_capacity_map.get(plant_name, 0)

            _LOGGER.debug(f"Processing plant {i}/{number_plants}: {plant_name} (ID: {plant_id})")
            print(f"  → Analyzing installation {i}/{number_plants}: {plant_name}")
            try:
                plant_stats = client.get_plant_stats(plant_id)
                plant_data = client.get_last_plant_data(plant_stats)
                _LOGGER.debug(f"Successfully retrieved data for plant: {plant_name}")
            except FusionSolarException as e:
                error_msg = str(e)
                _LOGGER.error(f"FusionSolar API error fetching data for {plant_name} (ID: {plant_id}): {error_msg}")
                print(f"    ❌ API error for {plant_name}: {error_msg}")
                # Continue with next plant even if this one fails
                result["statuses"].append({
                    "name": plant_name,
                    "pinstalled": installed_capacity,
                    "production": 0.0,
                    "consumption": 0.0,
                    "grid": 0.0,
                    "surplus": 0.0,
                    "status_icon": "🔴"
                })
                # Add detailed error message (truncated if too long)
                error_display = error_msg[:80] + "..." if len(error_msg) > 80 else error_msg
                result["alerts"].append(f"🔴 {plant_name} - Erro ao buscar dados: {error_display}")
                continue
            except Exception as e:
                error_msg = str(e)
                error_type = type(e).__name__
                _LOGGER.error(f"Error fetching data for plant {plant_name} (ID: {plant_id}): {error_type} - {error_msg}", exc_info=True)
                print(f"    ❌ Erro ao buscar dados da instalação {plant_name}: {error_type}: {error_msg}")
                # Continue with next plant even if this one fails
                result["statuses"].append({
                    "name": plant_name,
                    "pinstalled": installed_capacity,
                    "production": 0.0,
                    "consumption": 0.0,
                    "grid": 0.0,
                    "surplus": 0.0,
                    "status_icon": "🔴"
                })
                # Add detailed error message (truncated if too long)
                error_display = error_msg[:80] + "..." if len(error_msg) > 80 else error_msg
                result["alerts"].append(f"🔴 {plant_name} - Erro ao buscar dados: {error_display}")
                continue

            # Extract values and timestamps
            production_data = plant_data.get('productPower', {})
            production_power = float(production_data.get('value') or 0) if isinstance(production_data, dict) else float(production_data or 0)
            production_time = production_data.get('time') if isinstance(production_data, dict) else None
            
            consumption_data = plant_data.get('usePower', {})
            consumption_power = float(consumption_data.get('value') or 0) if isinstance(consumption_data, dict) else float(consumption_data or 0)
            consumption_time = consumption_data.get('time') if isinstance(consumption_data, dict) else None
            
            grid_data = plant_data.get('meterActivePower', {})
            grid_power = float(grid_data.get('value') or 0) if isinstance(grid_data, dict) else float(grid_data or 0)
            grid_time = grid_data.get('time') if isinstance(grid_data, dict) else None
            
            # Get the most recent timestamp (or any available timestamp)
            last_data_time = production_time or consumption_time or grid_time
            
            _LOGGER.debug(f"Plant {plant_name} data - Production: {production_power} kW ({production_time}), Consumption: {consumption_power} kW ({consumption_time}), Grid: {grid_power} kW ({grid_time})")

            # totals
            result["production"] += production_power
            result["consumption"] += consumption_power
            result["grid"] += grid_power
            result["plants"] += 1

            # status
            if plant['plantStatus'] == 'connected' and production_power != 0 and consumption_power != 0:
                status_icon = "🟢"
                error_state = 0
            elif plant['plantStatus'] == 'disconnected':
                status_icon = "🟡"
                error_state = 1
                
                # Check if disconnected for more than threshold hours
                if last_data_time:
                    try:
                        # Parse timestamp from "2026-01-15 14:30" format
                        last_data_datetime = datetime.strptime(last_data_time, "%Y-%m-%d %H:%M")
                        current_datetime = datetime.now()
                        hours_disconnected = (current_datetime - last_data_datetime).total_seconds() / 3600
                        
                        if hours_disconnected >= DISCONNECTED_RED_THRESHOLD_HOURS:
                            status_icon = "🔴"
                            _LOGGER.warning(f"Plant {plant_name} has been disconnected for {hours_disconnected:.1f} hours (threshold: {DISCONNECTED_RED_THRESHOLD_HOURS}h)")
                    except (ValueError, TypeError) as e:
                        # If timestamp parsing fails, keep yellow status
                        _LOGGER.debug(f"Could not parse timestamp for {plant_name}: {last_data_time}, error: {e}")
                
            elif plant['plantStatus'] == 'connected' and production_power != 0 and consumption_power == 0:
                status_icon = "🟡"
                error_state = 2
            elif plant['plantStatus'] == 'connected' and production_power == 0:
                status_icon = "🟡"
                error_state = 3
            else:
                status_icon = "🟡"
                error_state = 4

            plant_working_map = {name: code for name, code in list_of_plants}
            if error_state != 0:
                error_message = error_messages.get(error_state, "Erro desconhecido")
                # Only override with ⏳ if not already red (🔴)
                if plant_working_map.get(plant_name) == "1" and status_icon != "🔴":
                    status_icon = "⏳"
                
                # Build alert message
                alert_msg = f"{status_icon} {plant_name} - {error_message}"
                
                # Add timestamp for critical alerts (🔴)
                if status_icon == "🔴" and last_data_time:
                    try:
                        # Format timestamp: "2026-01-15 14:30" -> "15/01/2026 14:30"
                        last_data_datetime = datetime.strptime(last_data_time, "%Y-%m-%d %H:%M")
                        formatted_time = last_data_datetime.strftime("%d/%m/%Y %H:%M")
                        alert_msg += f" (última comunicação: {formatted_time})"
                    except (ValueError, TypeError):
                        # If parsing fails, use original format
                        alert_msg += f" (última comunicação: {last_data_time})"
                
                result["alerts"].append(alert_msg)

            surplus_power = max(production_power - consumption_power, 0)

            # Check for active alarms for all installations
            active_alarms = []
            try:
                _LOGGER.info(f"🔍 Checking for active alarms in {plant_name} (plant_id: {plant_id})...")
                # Verify client has get_inverter_ids (monkey-patched method)
                # Note: get_alarm_data() exists in fusion_solar_py library, so it's always available
                if not hasattr(client, 'get_inverter_ids'):
                    _LOGGER.error(f"get_inverter_ids method not found on client for {plant_name}")
                else:
                    # Get inverter IDs for this plant
                    _LOGGER.info(f"Calling get_inverter_ids for {plant_name}...")
                    inverter_ids = client.get_inverter_ids(plant_id)
                    _LOGGER.info(f"get_inverter_ids returned {len(inverter_ids)} inverter(s) for {plant_name}: {inverter_ids}")
                    
                    if inverter_ids:
                        # Check alarms for each inverter
                        # get_alarm_data() is part of fusion_solar_py library, so it's always available
                        for inverter_id in inverter_ids:
                            # Skip if inverter_id is None or empty
                            if not inverter_id:
                                _LOGGER.warning(f"Skipping alarm check for {plant_name}: inverter_id is None or empty")
                                continue
                            
                            try:
                                _LOGGER.info(f"Calling get_alarm_data for inverter {inverter_id} in {plant_name}...")
                                alarm_data = client.get_alarm_data(device_dn=inverter_id)
                                _LOGGER.info(f"get_alarm_data returned for {plant_name}: {type(alarm_data)}, keys: {list(alarm_data.keys()) if isinstance(alarm_data, dict) else 'N/A'}")
                                
                                # Parse alarm response - structure may vary
                                alarms = []
                                
                                # Try different possible response structures
                                if isinstance(alarm_data, dict):
                                    if alarm_data.get("success") and "data" in alarm_data:
                                        data = alarm_data["data"]
                                        # Could be a list directly or nested
                                        if isinstance(data, list):
                                            alarms = data
                                        elif isinstance(data, dict):
                                            alarms = data.get("list", []) or data.get("alarms", []) or data.get("data", [])
                                    elif "list" in alarm_data:
                                        alarms = alarm_data["list"]
                                    elif "alarms" in alarm_data:
                                        alarms = alarm_data["alarms"]
                                
                                _LOGGER.info(f"Parsed {len(alarms)} alarm(s) from response for {plant_name}")
                                
                                if alarms:
                                    for alarm in alarms:
                                        if not isinstance(alarm, dict):
                                            continue
                                            
                                        alarm_name = alarm.get("alarmName") or alarm.get("name") or alarm.get("alarm_name") or "Alarme desconhecido"
                                        alarm_level = alarm.get("alarmLevel") or alarm.get("level") or alarm.get("alarm_level") or ""
                                        alarm_time = alarm.get("alarmTime") or alarm.get("time") or alarm.get("alarm_time") or alarm.get("occurTime") or ""
                                        
                                        # Format alarm time if available
                                        alarm_time_str = "N/A"
                                        if alarm_time:
                                            try:
                                                # Try different time formats
                                                if isinstance(alarm_time, (int, float)):
                                                    # Timestamp in milliseconds
                                                    alarm_dt = datetime.fromtimestamp(alarm_time / 1000)
                                                    alarm_time_str = alarm_dt.strftime("%d/%m/%Y %H:%M")
                                                elif isinstance(alarm_time, str):
                                                    # Try parsing as timestamp or date string
                                                    try:
                                                        if alarm_time.isdigit():
                                                            alarm_dt = datetime.fromtimestamp(int(alarm_time) / 1000)
                                                            alarm_time_str = alarm_dt.strftime("%d/%m/%Y %H:%M")
                                                        else:
                                                            # Try parsing as date string
                                                            alarm_dt = datetime.strptime(alarm_time, "%Y-%m-%d %H:%M:%S")
                                                            alarm_time_str = alarm_dt.strftime("%d/%m/%Y %H:%M")
                                                    except:
                                                        alarm_time_str = alarm_time
                                            except Exception as time_error:
                                                _LOGGER.debug(f"Could not parse alarm time: {alarm_time}, error: {time_error}")
                                                alarm_time_str = str(alarm_time)
                                        
                                        # Map alarm level to emoji
                                        level_emoji = {
                                            "1": "🔴",  # Critical
                                            "2": "🟠",  # Major
                                            "3": "🟡",  # Minor
                                            "4": "⚪",  # Warning
                                            "critical": "🔴",
                                            "major": "🟠",
                                            "minor": "🟡",
                                            "warning": "⚪"
                                        }.get(str(alarm_level).lower(), "⚠️")
                                        
                                        active_alarms.append({
                                            "device": "Inversor",
                                            "name": alarm_name,
                                            "level": alarm_level,
                                            "time": alarm_time_str,
                                            "emoji": level_emoji
                                        })
                                        _LOGGER.warning(f"🚨 Active alarm in {plant_name} - Inversor: {alarm_name} (Level {alarm_level}) at {alarm_time_str}")
                                        print(f"    🚨 {plant_name}: {alarm_name} (Nível {alarm_level}) - {alarm_time_str}")
                            except FusionSolarException as alarm_error:
                                error_msg = str(alarm_error)
                                _LOGGER.warning(f"FusionSolar API error getting alarms for inverter {inverter_id} in {plant_name}: {error_msg}")
                                continue
                            except Exception as alarm_error:
                                error_msg = str(alarm_error)
                                error_type = type(alarm_error).__name__
                                _LOGGER.warning(f"Failed to get alarms for inverter {inverter_id} in {plant_name}: {error_type} - {error_msg}", exc_info=True)
                                continue
                    
                    if active_alarms:
                        _LOGGER.info(f"Found {len(active_alarms)} active alarm(s) in {plant_name}")
                        print(f"    ⚠️  {plant_name}: {len(active_alarms)} alarme(s) ativo(s)")
                        # Add alarms to alerts
                        for alarm in active_alarms:
                            result["alerts"].append(
                                f"{alarm['emoji']} {plant_name} - {alarm['name']} (Inversor, {alarm['time']})"
                            )
                    else:
                        _LOGGER.debug(f"No active alarms found in {plant_name}")
            except AttributeError as e:
                error_msg = str(e)
                _LOGGER.error(f"Attribute error when checking alarms for {plant_name}: {error_msg}", exc_info=True)
                print(f"    ❌ Erro ao verificar alarmes em {plant_name}: método não disponível")
            except Exception as e:
                error_msg = str(e)
                error_type = type(e).__name__
                _LOGGER.warning(f"Error checking alarms for {plant_name}: {error_type} - {error_msg}", exc_info=True)
                # Don't fail the whole process if alarm check fails - just log and continue

            result["statuses"].append({
                "name": plant['name'],
                "pinstalled": installed_capacity,
                "production": production_power,
                "consumption": consumption_power,
                "grid": grid_power,
                "surplus": surplus_power,
                "status_icon": status_icon,
                "last_data_time": last_data_time,  # Timestamp do último dado válido
                "active_alarms": active_alarms,  # Include alarms for this plant
                "alarm_count": len(active_alarms)  # Count of active alarms
            })

            # chart data
            product_power_filtered = [float(x) if x != '--' else 0 for x in plant_stats.get('productPower', [])]
            consumption_power_filtered = [float(x) if x != '--' else 0 for x in plant_stats.get('usePower', [])]
            self_use_power_filtered = [float(x) if x != '--' else 0 for x in plant_stats.get('selfUsePower', [])]

            if result["summed_production"] is None:
                result["summed_production"] = [0] * len(product_power_filtered)
                result["summed_consumption"] = [0] * len(consumption_power_filtered)
                result["summed_self_consumption"] = [0] * len(self_use_power_filtered)
                result["summed_overflow"] = [0] * len(product_power_filtered)

            result["summed_production"] = [
                round(s + c, 2) for s, c in zip(result["summed_production"], product_power_filtered)
            ]
            result["summed_consumption"] = [
                round(s + c, 2) for s, c in zip(result["summed_consumption"], consumption_power_filtered)
            ]
            result["summed_self_consumption"] = [
                round(s + c, 2) for s, c in zip(result["summed_self_consumption"], self_use_power_filtered)
            ]
            result["summed_overflow"] = [
                round(s + max(prod - cons, 0), 2)
                for s, prod, cons in zip(result["summed_overflow"], product_power_filtered, consumption_power_filtered)
            ]

        # Don't log out - keep session alive for reuse
        # client.log_out()  # Commented out to maintain session
        _LOGGER.info(f"Successfully processed account {USER}: {result['plants']} plants, Total production: {result['production']:.2f} kW, Total consumption: {result['consumption']:.2f} kW")
        print(f"✓ Completed processing {USER}: {result['plants']} plants processed")
        return result

    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        _LOGGER.error(f"Unexpected error processing account {USER}: {error_type} - {error_msg}", exc_info=True)
        print(f"❌ Erro no processamento da conta {USER}: {error_type}: {error_msg}")
        # Add account-level error to alerts so it's visible in the UI
        result["alerts"].append(f"🔴 Conta {USER} - Erro ao processar: {error_msg[:100]}")
        return result
        
def _fetch_live_data():
    """Internal function to actually fetch data from Fusion Solar API"""
    try:
        _LOGGER.info("="*60)
        _LOGGER.info("Starting data fetch from Fusion Solar API")
        _LOGGER.info(f"Processing {len(accounts)} accounts in parallel")
        print("\n" + "="*60)
        print("Starting data fetch from Fusion Solar API")
        print(f"Processing {len(accounts)} accounts...")
        print("="*60)
        
        total_production = total_consumption = total_grid = total_plants = 0
        statuses = []
        zero_production_plants = []
        summed_production = summed_consumption = summed_self_consumption = summed_overflow = None
        account_summaries = []  # Track stations per account

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(process_account, acc): acc for acc in accounts}
            for f in as_completed(futures):
                account = futures[f]
                r = f.result()
                total_production += r["production"]
                total_consumption += r["consumption"]
                total_grid += r["grid"]
                total_plants += r["plants"]
                statuses.extend(r["statuses"])
                zero_production_plants.extend(r["alerts"])
                account_summaries.append({
                    "account": account[0],
                    "plants": r["plants"]
                })
                
                # merge charts
                if r["summed_production"] is not None:
                    if summed_production is None:
                        summed_production = r["summed_production"]
                        summed_consumption = r["summed_consumption"]
                        summed_self_consumption = r["summed_self_consumption"]
                        summed_overflow = r["summed_overflow"]
                    else:
                        summed_production = [a + b for a, b in zip(summed_production, r["summed_production"])]
                        summed_consumption = [a + b for a, b in zip(summed_consumption, r["summed_consumption"])]
                        summed_self_consumption = [a + b for a, b in zip(summed_self_consumption, r["summed_self_consumption"])]
                        summed_overflow = [a + b for a, b in zip(summed_overflow, r["summed_overflow"])]

        # Print summary of installations per account
        _LOGGER.info("="*60)
        _LOGGER.info("DATA FETCH SUMMARY")
        _LOGGER.info(f"Total production: {total_production:.2f} kW")
        _LOGGER.info(f"Total consumption: {total_consumption:.2f} kW")
        _LOGGER.info(f"Total grid: {total_grid:.2f} kW")
        _LOGGER.info(f"Total installations: {total_plants}")
        print("\n" + "="*60)
        print("INSTALLATION SUMMARY")
        print("="*60)
        for summary in account_summaries:
            print(f"  {summary['account']}: {summary['plants']} installations")
            _LOGGER.info(f"Account {summary['account']}: {summary['plants']} installations")
        print(f"\n  TOTAL INSTALLATIONS: {total_plants}")
        print(f"  Expected in list_of_plants: {len(list_of_plants)}")
        print(f"  Total Production: {total_production:.2f} kW")
        print(f"  Total Consumption: {total_consumption:.2f} kW")
        print("="*60 + "\n")
        
        alert_message = "✅ Todas as instalações estão a funcionar normalmente."
        if zero_production_plants:
            # Sort alerts by priority: 🔴 (critical) first, then 🟠 (major), then ⏳, then 🟡 (minor), then ⚪ (warning), then ⚠️
            def alert_priority(alert):
                if alert.startswith("🔴"):
                    return 0  # Highest priority - Critical
                elif alert.startswith("🟠"):
                    return 1  # Major alarms
                elif alert.startswith("⏳"):
                    return 2  # In maintenance
                elif alert.startswith("🟡"):
                    return 3  # Minor alarms
                elif alert.startswith("⚪"):
                    return 4  # Warning alarms
                elif alert.startswith("⚠️"):
                    return 5
                else:
                    return 6  # Lowest priority
            
            zero_production_plants.sort(key=alert_priority)
            alert_message = "As seguintes instalações estão com problemas:\n" + "\n".join([f"- {p}" for p in zero_production_plants])

        current_time = datetime.now().strftime('%H:%M')
        x_axis = [f"{h:02d}:{m:02d}" for h in range(24) for m in range(0, 60, 5)]
        filtered_axis = [t for t in x_axis if t <= current_time]
        n = len(filtered_axis)

        # Ensure chart data is always arrays, never None
        if summed_production is not None:
            summed_production = summed_production[:n]
            summed_consumption = summed_consumption[:n]
            summed_self_consumption = summed_self_consumption[:n]
            summed_overflow = summed_overflow[:n]
        else:
            # If no chart data available, use empty arrays
            summed_production = []
            summed_consumption = []
            summed_self_consumption = []
            summed_overflow = []

        # Get current timestamp for last updated
        last_updated_datetime = datetime.now()
        
        return {
            "production": round(total_production, 2),
            "consumption": round(total_consumption, 2),
            "grid": round(total_grid, 2),
            "total_plants": total_plants,
            "statuses": statuses,
            "alert": alert_message,
            "chart": {
                "x_axis": filtered_axis,
                "production": summed_production,
                "consumption": summed_consumption,
                "self_consumption": summed_self_consumption,
                "surplus": summed_overflow
            },
            "alerts": zero_production_plants,
            "last_updated": last_updated_datetime.strftime('%Y-%m-%d %H:%M:%S'),
            "last_updated_timestamp": last_updated_datetime.timestamp()
        }

    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        _LOGGER.error(f"Critical error in _fetch_live_data: {error_type} - {error_msg}", exc_info=True)
        print(f"❌ Critical error in data fetch: {error_type}: {error_msg}")
        return {"error": "Erro ao carregar dados 😞"}

def _update_chart_x_axis_for_current_time(cached_data):
    """
    Update the chart x_axis and pad data arrays with null values for time points
    that have passed since the data was cached, but don't have data yet.
    """
    from datetime import datetime
    current_time_str = datetime.now().strftime('%H:%M')
    
    # Generate full x_axis up to current time
    x_axis = [f"{h:02d}:{m:02d}" for h in range(24) for m in range(0, 60, 5)]
    filtered_axis = [t for t in x_axis if t <= current_time_str]
    
    if "chart" not in cached_data or not cached_data["chart"]:
        return cached_data
    
    chart = cached_data["chart"]
    old_x_axis = chart.get("x_axis", [])
    old_length = len(old_x_axis)
    new_length = len(filtered_axis)
    
    # If no new time points have passed, return data as-is
    if new_length <= old_length:
        return cached_data
    
    # Update x_axis to current time
    chart["x_axis"] = filtered_axis
    
    # Pad all data arrays with null values for new time points
    arrays_to_pad = ["production", "consumption", "self_consumption", "surplus"]
    for array_name in arrays_to_pad:
        if array_name in chart and isinstance(chart[array_name], list):
            # Add null values for new time points
            num_new_points = new_length - old_length
            chart[array_name].extend([None] * num_new_points)
    
    return cached_data

@app.route("/api/live-data")
def live_data():
    """API endpoint with caching to reduce Fusion Solar API calls"""
    current_time = time.time()
    
    # Check if we have cached data that's still valid
    with _data_cache["lock"]:
        cache_age = current_time - _data_cache["timestamp"]
        
        if _data_cache["data"] is not None and cache_age < CACHE_DURATION:
            # Update x_axis to current time (adds null values for new time points)
            # Use deepcopy to avoid modifying the original cached data
            cached_data_copy = copy.deepcopy(_data_cache["data"])
            cached_data_copy = _update_chart_x_axis_for_current_time(cached_data_copy)
            _LOGGER.info(f"Returning cached data (age: {int(cache_age)}s, remaining: {int(CACHE_DURATION - cache_age)}s)")
            print(f"📦 Returning cached data (age: {int(cache_age)}s)")
            return jsonify(cached_data_copy)
        
        # Cache expired or doesn't exist, fetch fresh data
        _LOGGER.info("Cache expired or missing, fetching fresh data from Fusion Solar API...")
        print("🔄 Cache expired or missing, fetching fresh data from Fusion Solar API...")
        fresh_data = _fetch_live_data()
        
        # Check if there was an error
        if "error" in fresh_data:
            _LOGGER.error("Data fetch returned error, not caching")
            # Return error immediately without caching
            return jsonify(fresh_data), 500
        
        # Update cache with successful data
        _data_cache["data"] = fresh_data
        _data_cache["timestamp"] = current_time
        last_updated_str = fresh_data.get('last_updated', 'N/A')
        _LOGGER.info(f"✅ Data successfully updated at {last_updated_str}. Total plants: {fresh_data.get('total_plants', 0)}")
        print(f"✅ Data successfully updated at {last_updated_str}")
        
        return jsonify(fresh_data)

if __name__ == "__main__":
    # Only run Flask dev server if executed directly (not via gunicorn)
    # Gunicorn imports app:app directly, so this block is skipped in production
    app.run(debug=True)



