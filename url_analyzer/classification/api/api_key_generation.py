

import argparse
from datetime import datetime, timedelta, timezone
import sys
import os
import asyncio

import jwt


JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")

def get_api_key_from_ip_address(ip_address: str) -> str:
  # Get current time in UTC
  now = datetime.now(timezone.utc)
  
  # Calculate the end of the next calendar day in UTC
  tomorrow = now + timedelta(days=1)
  end_of_next_day = datetime(
    year=tomorrow.year,
    month=tomorrow.month,
    day=tomorrow.day,
    hour=23,
    minute=59,
    second=59,
    microsecond=999999,
    tzinfo=timezone.utc
  )
  
  # Create the payload with the IP address and expiration time
  payload = {
    "ip_address": ip_address,
    "exp": end_of_next_day
  }
  
  # Generate the JWT API key
  api_key = jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")
  return api_key