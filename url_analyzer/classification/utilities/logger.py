import os
import sys
import time
import uuid
from pydantic import BaseModel, ConfigDict, ValidationError
from typing import Any, Awaitable, Callable, Coroutine, Dict, Generic, List, Optional, OrderedDict, Set, Tuple, TypeVar
from dataclasses import dataclass

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

BASE_LOG_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "logs")

from url_analyzer.classification.utilities.utilities import run_with_logs, url_to_filepath



class Logger(BaseModel):
  """
  Convenience class for logging to a file with context
  """
  key: Optional[str] = None
  dirname: Optional[str] = None
  initial_content: Optional[str] = None

  @classmethod
  async def construct(cls, dirname: Optional[str] = None, key: Optional[str] = None, initial_content: Optional[str] = None) -> "Logger":
    await run_with_logs("mkdir", "-p", dirname, process_name="mkdir")
    if dirname is not None:
      fname = os.path.join(dirname, "log.txt")
      with open(fname, "a") as f:
        f.write("" if initial_content is None else initial_content)
    return cls(key=key, dirname=dirname, initial_content=initial_content)

  @classmethod
  async def construct_from_url_and_base_log_dir(cls, url: str, base_log_dir: Optional[str] = None, **kwargs) -> "Logger":

    base_log_dir = base_log_dir if base_log_dir is not None else BASE_LOG_DIRECTORY

    dirname = os.path.join(base_log_dir, f"{str(int(time.time()))}_{url_to_filepath(url)}_{uuid.uuid4()}")
    return await cls.construct(dirname=dirname, **kwargs)

  def log(self, msg: str):
    print(msg if self.key is None else f"[{self.key}]" + msg)
    if self.dirname is not None:
      fname = os.path.join(self.dirname, "log.txt")
      with open(fname, "a") as f:
        f.write(msg)