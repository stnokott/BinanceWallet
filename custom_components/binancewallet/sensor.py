"""
Retrieves balances from Binance wallet

TODO:
- Config flow
"""
import urllib.error

import voluptuous as vol

from .const.const import (
    LOGGER,
    CONF_API_KEY,
    CONF_API_SECRET,
    CONF_NAME,
    ENDPOINT_BASE,
    SENSOR_PREFIX,
    CONF_ICON,
    ATTR_DATA_TIMESTAMP,
    ATTR_ASSETS,
    ATTR_BALANCES_ASSET,
    ATTR_BALANCES_TOTAL,
    ENDPOINT_WALLET, CONF_UNIQUE_ID, UNIQUE_ID_PREFIX,
)

from homeassistant.components.sensor import PLATFORM_SCHEMA
import homeassistant.helpers.config_validation as cv
from homeassistant.util import Throttle
from homeassistant.helpers.entity import Entity

from datetime import datetime, timedelta
import enum
import hashlib
import hmac
import json
import time
from typing import Optional, List
from urllib.parse import urlencode, urljoin

import requests

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_API_KEY): cv.string,
        vol.Required(CONF_API_SECRET): cv.string,
        vol.Optional(CONF_UNIQUE_ID, default=""): cv.string,
        vol.Optional(CONF_NAME, default=""): cv.string,
        vol.Optional(CONF_ICON, default="mdi:bitcoin"): cv.string,
    }
)


def setup_platform(hass, config, add_entities, discovery_info=None):
    LOGGER.debug("Setting up sensor")

    unique_id = config.get(CONF_UNIQUE_ID).lower().strip()
    name = config.get(CONF_NAME)
    api_key = config.get(CONF_API_KEY)
    api_secret = config.get(CONF_API_SECRET)
    icon = config.get(CONF_ICON)

    entities = []

    try:
        entities.append(BinanceWalletSensor(api_key, api_secret, unique_id, name, icon))
    except urllib.error.HTTPError as e:
        LOGGER.error(e.reason)
        return False

    add_entities(entities)


class BinanceWalletSensor(Entity):
    def __init__(self, api_key, api_secret, unique_id, id_name, icon):
        self.update = Throttle(timedelta(hours=1))(self._update)
        if len(unique_id) > 0:
            self._unique_id = unique_id
        else:
            self._unique_id = f"{UNIQUE_ID_PREFIX}_{api_key[:4]}"
        self._name = (
            f"{SENSOR_PREFIX} {id_name if len(id_name) > 0 else api_key[:4] + 'xxxx'}"
        )
        self._icon = icon
        self._state: Optional[float] = None
        self._data_timestamp: Optional[str] = None
        self._balances: List[WalletBalance] = []
        self._unit_of_measurement: str = "BTC"
        self._wallet = Wallet(api_key, api_secret)

    @property
    def unique_id(self):
        return self._unique_id

    @property
    def name(self):
        return self._name

    @property
    def icon(self):
        return self._icon

    @property
    def state(self):
        return self._state

    @property
    def unit_of_measurement(self):
        return self._unit_of_measurement

    @property
    def device_state_attributes(self):
        return {
            ATTR_DATA_TIMESTAMP: self._data_timestamp,
            ATTR_ASSETS: [
                {
                    ATTR_BALANCES_ASSET: balance.asset,
                    ATTR_BALANCES_TOTAL: balance.total,
                }
                for balance in self._balances
            ],
        }

    def _update(self):
        self._wallet.update()
        self._data_timestamp = self._wallet.timestamp.strftime("%d-%m-%Y %H:%M")
        self._state = self._wallet.total_btc
        self._balances = self._wallet.balances


class RequestStatus(enum.IntEnum):
    SUCCESS = 0
    REQUEST_MALFORMED = 1
    WAF_LIMIT_VIOLATED = 2
    RATE_LIMIT_EXCEEDED = 3
    IP_BANNED = 4
    INTERNAL_ERROR = 5
    UNDEFINED = 6


class RequestResponse:
    def __init__(self, response: requests.Response):
        status_code = response.status_code
        self.text = response.text
        if status_code == 200:
            self.status = RequestStatus.SUCCESS
            for key in response.headers.keys():
                if "X-SAPI-USED-IP-WEIGHT-" in key:
                    LOGGER.debug(
                        f"Current used weight: {key[22:]}={response.headers[key]}"
                    )
        else:
            if status_code == 403:
                self.status = RequestStatus.WAF_LIMIT_VIOLATED
            elif status_code == 429:
                self.status = RequestStatus.RATE_LIMIT_EXCEEDED
            elif status_code == 418:
                self.status = RequestStatus.IP_BANNED
            elif str(status_code)[0] == "4":
                self.status = RequestStatus.REQUEST_MALFORMED
            elif str(status_code)[0] == "5":
                self.status = RequestStatus.INTERNAL_ERROR
            else:
                LOGGER.warning(f"Undefined HTTP status code: {status_code}")
                self.status = RequestStatus.UNDEFINED


class WalletBalance:
    def __init__(self, asset: str, free: float, locked: float):
        self.asset = asset
        self.total = free + locked


class Wallet:
    def __init__(self, api_key: str, secret_key: str):
        self._api_key = api_key
        self._secret_key = secret_key
        self.timestamp: Optional[datetime] = None
        self.total_btc: Optional[float] = None
        self.balances: List[WalletBalance] = []

        self._headers = {"X-MBX-APIKEY": self._api_key}

    def _execute_request(self) -> RequestResponse:
        url = urljoin(ENDPOINT_BASE, ENDPOINT_WALLET)

        params = {
            "type": "SPOT",
            "timestamp": str(int(time.time() * 1000))
        }

        # form base query string from params
        base_query_string = urlencode(params)

        # create signature params
        params["signature"] = hmac.new(
            bytes(self._secret_key, "utf-8"),
            bytearray(base_query_string, "utf-8"),
            hashlib.sha256,
        ).hexdigest()

        r = requests.get(url, headers=self._headers, params=params)
        return RequestResponse(r)

    def update(self):
        response = self._execute_request()

        if response.status != RequestStatus.SUCCESS:
            LOGGER.warning(
                f"Unsuccessful request: <{response.status.name}> -> <{response.text}>"
            )
        else:
            try:
                response_json = json.loads(response.text)
                latest_snapshot = response_json["snapshotVos"][-1]
                self.timestamp = datetime.fromtimestamp(
                    latest_snapshot["updateTime"] / 1000
                )
                snapshot_data = latest_snapshot["data"]
                self.total_btc = snapshot_data["totalAssetOfBtc"]
                for balance in snapshot_data["balances"]:
                    self.balances.append(
                        WalletBalance(
                            balance["asset"], balance["free"], balance["locked"]
                        )
                    )
                LOGGER.debug(
                    f"Successfully parsed response ({len(self.balances)} balances found)."
                )
            except json.JSONDecodeError as e1:
                LOGGER.warning(f"Could not parse response as JSON: {e1}")
            except KeyError as e2:
                LOGGER.warning(f"Required attribute missing in response JSON: {e2}")
