"""
https://www.zenrows.com/blog/avoid-playwright-bot-detection#user-agent
https://github.com/AtuboDad/playwright_stealth
"""
import asyncio
from copy import deepcopy
from dataclasses import dataclass
import json
import re
import sys
import os

import io
import time
import traceback
from typing import Any, Callable, Dict, Generic, Iterable, List, Optional, OrderedDict, Tuple, TypeVar, Union
import PIL
import PIL.Image
from bs4 import BeautifulSoup
import chardet
import playwright
from playwright.async_api import async_playwright
from playwright._impl._page import Page
from playwright_stealth import stealth_async
import requests
import json
import time
import os

from url_analyzer.classification.browser_automation.playwright_page_manager import PlaywrightPageManager, PlaywrightPageManagerCloneContext
from url_analyzer.classification.browser_automation.response_record import ResponseRecord


BASE_EXCLUDED_HEADERS_TEMPLATE_LIST = [
  "(.*):(.*)", "content-length"
]

REQUEST_FILE_TEMPLATE = """{method} {url_path} {http_protocol}
Host: {fqdn}
{formatted_headers}

{post_data}"""


def get_post_data_kwargs(raw_request_post_data: Optional[Union[str, Dict[str, Any]]]) -> Dict[str, Any]:
  if type(raw_request_post_data) == str:
    try:
      request_post_data = json.loads(raw_request_post_data)
    except json.JSONDecodeError as e:
      print(
        f"""
        Failed to parse raw_request_post_data as json. Will resubmit request with data field instead
        ---- raw_request_post_data ----
        {raw_request_post_data}
        --------
        """
      )
      post_data_kwargs = {"data": raw_request_post_data}
    else:
      post_data_kwargs = {"json": request_post_data}
  else:
    post_data_kwargs = {"json": raw_request_post_data}
  return post_data_kwargs

async def resubmit_response(
  response_record: ResponseRecord,
  playwright_page_manager: Optional[PlaywrightPageManager] = None,
  verbose: bool = False,
) -> ResponseRecord:
  """
  Given a response record, resubmit the request and return the new response


  TODO: Modify this so it can work with a PlaywrightPageManager

  """
  assert response_record.request_url is not None

  request_url = response_record.request_url
  request_method = response_record.request_method
  raw_request_headers = response_record.request_headers
  raw_request_post_data = response_record.request_post_data

  if type(raw_request_headers) == str:
    raw_request_headers = json.loads(raw_request_headers)
  request_headers = {k: v for k, v in raw_request_headers.items() if not k.startswith(":")}

  post_data_kwargs = get_post_data_kwargs(raw_request_post_data=raw_request_post_data)

  print("submitting...")

  if verbose:
    print(f"\n-----REQUEST-----\nurl: {request_url} \n headers: {request_headers} \n post_data_kwargs: {post_data_kwargs} \n request_method: {request_method}\n-----------------\n")
  
  if playwright_page_manager is not None:
    # TODO: Figure out if there is some headers you need to be smarter about how you override!!!

    async with PlaywrightPageManagerCloneContext(playwright_page_manager) as cloned_playwright_page_manager:
      if request_method == 'POST':
        raw_response = await cloned_playwright_page_manager.context.request.post(request_url, headers=request_headers, **post_data_kwargs)
      elif request_method == 'GET':
        raw_response = await cloned_playwright_page_manager.context.request.get(request_url, headers=request_headers)
      else:
        raise ValueError(f"Unknown method {request_method}")
      response_record = await ResponseRecord.from_playwright_response(raw_response)
  else:
    if request_method == 'POST':
      raw_response = requests.post(request_url, headers=request_headers, **post_data_kwargs)
    elif request_method == 'GET':
      raw_response = requests.get(request_url, headers=request_headers)
    else:
      raise ValueError(f"Unknown method {request_method}")
    response_record = ResponseRecord(
      response_url=raw_response.url,
      response_text=raw_response.text,
      response_text_length=len(raw_response.text),
      response_status=raw_response.status_code,
      response_status_text=raw_response.reason,
      response_headers=raw_response.headers,
      request_url=request_url,
      request_method=request_method,
      request_post_data=None if post_data_kwargs is None else list(post_data_kwargs.values())[0],
      request_headers=request_headers
    )
  ResponseRecord.model_validate(response_record)
  return response_record
