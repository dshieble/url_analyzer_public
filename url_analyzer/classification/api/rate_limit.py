# Rate limiting settings
import time
from typing import Dict, List

class RateLimiter:
  def __init__(
    self,
    max_requests_per_period: int = 5,
    window_size_in_minutes: int = 5
  ):
    self.request_logs: Dict[str, List[float]] = {}
    self.max_requests_per_period = max_requests_per_period
    self.window_size_in_minutes = window_size_in_minutes

  def is_rate_limited(self, token: str) -> bool:
    current_time = time.time()
    if token not in self.request_logs:
      self.request_logs[token] = []

    # Filter out requests older than the time window (M minutes)
    window_start_time = current_time - (self.window_size_in_minutes * 60)
    self.request_logs[token] = [t for t in self.request_logs[token] if t > window_start_time]

    # Check if the number of requests exceeds the limit
    if len(self.request_logs[token]) >= self.max_requests_per_period:
      out = True
    else:
      # Log the new request
      self.request_logs[token].append(current_time)
      out = False
    return out