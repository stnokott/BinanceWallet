import logging

ENDPOINT_BASE = "https://api.binance.com"
ENDPOINT_WALLET = "/sapi/v1/accountSnapshot"

CONF_API_KEY = "api_key"
CONF_API_SECRET = "api_secret"
CONF_NAME = "name"
CONF_ICON = "icon"

SENSOR_PREFIX = "Binance Wallet "
ATTR_DATA_TIMESTAMP = "data_timestamp"
ATTR_ASSETS = "assets"
ATTR_BALANCES_ASSET = "asset"
ATTR_BALANCES_TOTAL = "total"

LOGGER = logging.getLogger(__name__)
