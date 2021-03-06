"""
Cox Data Usage Sensor

Example config:

- platform: Cox
  name: Cox Data Usage
  username: !secret cox_username
  password: !secret cox_password

Based on this: https://github.com/lachesis/comcast/blob/master/comcast.py

"""

import calendar
import datetime as dt
import json
import logging
import re
from functools import partial

import requests
import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (CONF_NAME, CONF_USERNAME, CONF_PASSWORD)
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

_LOGGER = logging.getLogger(__name__)

LOGIN_API_URL = 'https://idm.east.cox.net/idm/coxnetlogin'
DATA_USAGE_URL = 'https://www.cox.com/internet/mydatausage.cox'

DEFAULT_ICON = 'mdi:chart-line'

MIN_TIME_BETWEEN_UPDATES = dt.timedelta(minutes=60)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default='Cox'): cv.string,
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string
})

ATTR_USED_DATA = 'Used data'
ATTR_TOTAL_DATA = 'Total data'
ATTR_DAYS_IN_MONTH = 'Days this month'
ATTR_DAYS_LEFT = 'Days Left in Cycle'
ATTR_UTILIZATION = 'Percentage Used'
ATTR_CURRENT_AVG_GB = 'Average GB Used Per Day'
ATTR_REMAINING_AVG_GB = 'Average GB Remaining Per Day'


async def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Set up the sensor."""
    _LOGGER.debug('Cox: async_setup_platform')

    name = config.get(CONF_NAME)
    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)

    device = CoxDataUsage(hass, name, username, password)

    result = await device.async_update()
    if result is False:
        return

    async_add_devices([device])


class CoxDataUsage(Entity):
    """Representation of the sensor."""

    def __init__(self, hass, name, username, password):
        """Initialize the sensor."""

        self._hass = hass
        self._name = name
        self._username = username
        self._password = password

        self._state = STATE_UNKNOWN
        self._state_attributes = None

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unit_of_measurement(self):
        """Return the unit the value is expressed in."""
        return "GB"

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return DEFAULT_ICON

    @property
    def state(self):
        """Return the state."""
        return self._state

    @property
    def device_state_attributes(self):
        """Return additional information about the sensor."""
        return self._state_attributes

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def async_update(self):
        """Fetch the latest data."""

        self._state = STATE_UNKNOWN
        self._state_attributes = {}

        session = requests.session()
        session.verify = False
        # fill out the login form
        data = {
            'onsuccess': 'https://www.cox.com/internet/mydatausage.cox',
            'onfailure': 'ww2.cox.com/resaccount/sign-in.cox',
            'targetFN': 'COX.net',
            'emaildomain': '@cox.net',
            'username': self._username,
            'password': self._password,
            'rememberme': 'true'
        }
        # perform the login
        response = await CoxDataUsage.async_call_api(self._hass, session, LOGIN_API_URL, data)
        if response is None:
            return False

        # get the data usage
        response = await CoxDataUsage.async_call_api(self._hass, session, DATA_USAGE_URL)
        if response is None:
            return False
        script_var = re.findall(r'var.utag_data={\s*(.*?)}\n', response.text, re.DOTALL | re.MULTILINE)
        json_str = "{" + script_var[0] + "}"
        response_object = json.loads(json_str)
        # Add total days in the current month
        now = dt.datetime.now()
        days_in_month = calendar.monthrange(now.year, now.month)[1]

        usage = float(response_object['dumUsage'])
        limit = float(response_object['dumLimit'])
        days_left = float(response_object['dumDaysLeft'])
        utilization = response_object['dumUtilization']
        current_avg_gb = round((usage/max((days_in_month - days_left), 1)), 2)
        remaining_avg_gb = round((limit - usage) / days_left, 2)

        self._state = usage
        self._state_attributes = {
            ATTR_USED_DATA: usage,
            ATTR_TOTAL_DATA: limit,
            ATTR_UTILIZATION: utilization,
            ATTR_DAYS_IN_MONTH: days_in_month,
            ATTR_DAYS_LEFT: days_left,
            ATTR_CURRENT_AVG_GB: current_avg_gb,
            ATTR_REMAINING_AVG_GB: remaining_avg_gb
        }

        return True

    @staticmethod
    async def async_call_api(hass, session, url, data=None):
        """Calls the given api and returns the response data"""
        try:
            if data is None:
                response = await hass.loop.run_in_executor(None, partial(session.get, url, timeout=10))
            else:
                response = await hass.loop.run_in_executor(None, partial(session.post, url, data=data, timeout=10))
        except (requests.exceptions.RequestException, ValueError):
            _LOGGER.warning(
                'Request failed for url %s',
                url)
            return None

        if response.status_code != 200:
            _LOGGER.warning(
                'Invalid status_code %s from url %s',
                response.status_code, url)
            return None

        return response
