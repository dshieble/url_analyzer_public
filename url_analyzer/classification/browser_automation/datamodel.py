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
from typing import Any, Callable, Dict, Generic, Iterable, List, Optional, OrderedDict, Set, Tuple, TypeVar, Union
import PIL
import PIL.Image
from bs4 import BeautifulSoup
import chardet
import playwright
from playwright.async_api import async_playwright
from playwright._impl._page import Page
from playwright_stealth import stealth_async
import requests
from unidecode import unidecode
import validators
import inscriptis
import pytesseract
import json
import time
import os
from playwright.async_api._generated import Request
import dill
import curlify
from pydantic import BaseModel, ValidationError
import urllib.parse
from playwright.async_api._generated import ElementHandle


from url_analyzer.classification.utilities.file_utils import AsyncFileClient, get_client_from_path
from url_analyzer.classification.utilities.utilities import modify_url, pydantic_create, pydantic_validate
from url_analyzer.classification.browser_automation.response_record import get_response_log, ResponseRecord


MAX_BODY_TEXT_LENGTH = 10000
DEFAULT_IMAGE_ROOT_PATH = os.path.join(os.path.dirname(__file__), '..', 'outputs', 'images')


async def wait_for_load_state_safe(page: Page, **kwargs):

  # Playwright throws an error when the wait_for_load_state times out. This is a workaround.
  try:
    await page.wait_for_load_state(**kwargs)
  except Exception as e:
    pass

async def scroll_page_and_wait(page: Page, timeout: int = 500):
  await wait_for_load_state_safe(page, state='networkidle', timeout=5000)
  await page.wait_for_timeout(timeout)
  try:
    await page.evaluate(f"window.scrollTo(0, 0)")
  except Exception as e:
    print(e)
  await wait_for_load_state_safe(page, state='networkidle', timeout=5000)
  await page.wait_for_timeout(timeout)


class PageLoadResponse(BaseModel):
  page_loaded_successfully: bool
  page_response_status: Optional[int] = None
  page_loading_error: Optional[str] = None
  page_final_destination_url: Optional[str] = None


class UrlScreenshotResponse(BaseModel):
  url: str
  timestamp: int
  page_load_response: PageLoadResponse
  html: Optional[str] = None
  screenshot_path: Optional[str] = None
  navigation_error: Optional[str] = None
  content_error: Optional[str] = None
  image_error: Optional[str] = None
  screenshot_exception: Optional[str] = None

  def display(self):
    print(
      f"""
      url: {self.url}
      timestamp: {self.timestamp}
      page_response_status: {self.page_response_status}
      screenshot_path: {self.screenshot_path}
      loading_error: {self.loading_error}
      navigation_error: {self.navigation_error}
      dns_failure: {self.dns_failure}
      image_error: {self.image_error}
      screenshot_exception: {self.screenshot_exception}
      final_redirect_url: {self.final_redirect_url}
      """
    )

  async def get_screenshot_bytes(self, client: Optional[AsyncFileClient] = None) -> bytes:
    """
    If the screenshot bytes is None, fetch the image from s3 first to set it
    """
    if client is None:
      client = get_client_from_path(path=self.screenshot_path)
        
    screenshot_bytes = await client.load_object(path=self.screenshot_path)
    return screenshot_bytes

  @classmethod
  async def from_screenshot_bytes(
    cls,
    screenshot_bytes: bytes,
    client: Optional[AsyncFileClient] = None,
    *args,
    image_root_path: Optional[str] = None,
    verbose=True,
    **kwargs
  ) -> "Optional[UrlScreenshotResponse]":
    response = cls(*args,  **kwargs)
    if response.screenshot_path is not None:
      raise ValueError("Cannot create a screenshot response from screenshot_bytes if the screenshot path is already set")
    
    # Save the image to the screenshot path
    screenshot_path = response.generate_screenshot_path(image_root_path=image_root_path)
    if client is None:
      client = get_client_from_path(path=screenshot_path)
        
    try:
      await client.write_object(obj=screenshot_bytes, path=screenshot_path)

    except PIL.UnidentifiedImageError as e:
      if verbose:
        print(f"ERROR: UnidentifiedImageError on {response.url} at {response.timestamp} saving to {screenshot_path}")
      response.image_error = str(e)
    except PIL.Image.DecompressionBombError as e:
      if verbose:
        print(f"ERROR: DecompressionBombError on {response.url} at {response.timestamp} saving to {screenshot_path}")
      response.image_error = str(e)
    except Exception as e:
      print(f"EXCEPTION  on {response.url} at {response.timestamp} saving to {screenshot_path}")
      raise e
    else:
      # If the save was successful, set the screenshot path
      response.screenshot_path = screenshot_path
    return response



  def generate_screenshot_path(self, image_root_path: Optional[str] = None,) -> str:
    # Url images are defined by hashing the url and the timestamp. They are independent of the experiment_id.
    image_root_path = DEFAULT_IMAGE_ROOT_PATH if image_root_path is None else image_root_path
    image_hash = str(hash(self.url + str(self.timestamp)))
    return f"{image_root_path}/{image_hash}.png"

  async def get_image(self, client: Optional[AsyncFileClient] = None) -> PIL.Image:
    if self.screenshot_path is not None:
      if client is None:
        client = get_client_from_path(path=self.screenshot_path)
      screenshot_bytes = await client.load_object(path=self.screenshot_path)
      image = PIL.Image.open(io.BytesIO(screenshot_bytes)).convert('RGB')
    else:
      image = None
    return image
  

class SignatureHandle(BaseModel):
  signature: str
  kind: str
  inject_random_text_in_all_inputs: bool = True

class SignatureSequence(BaseModel):
  signature_sequence: List[SignatureHandle]
  required_signatures: Set[str]


class OpenUrlCallingContext(BaseModel):
  url: str

class FillFormCallingContext(BaseModel):
  url: str
  form_input: Dict[str, str]
  verbose: bool = True

class ClickSignaturesInSequenceCallingContext(BaseModel):
  url: str
  signature_sequence: SignatureSequence
  include_all_clickable: bool = False
  min_elements: int = 3
  num_reloads: int = 10








class Listener:

  # Stores the response on each dialog
  response_log: Optional[List[ResponseRecord]]

  # Stores the message on each dialog
  dialog_message_log: Optional[List[str]]

  # Stores the error message on each console
  console_error_message_log: Optional[List[str]]

  def __init__(self, page: Page):
    self.response_log = []
    self.dialog_message_log = []
    self.console_error_message_log = []

    self.page = page
    self.page.on("response", self.handle_response)
    self.page.on("dialog", self.handle_dialog)
    self.page.on("console", self.handle_console)

  async def handle_response(self, response: Request):
    # Record the message on each response that is processes
    response_record = await ResponseRecord.from_playwright_response(response)
    pydantic_validate(ResponseRecord, response_record)
    self.response_log.append(response_record)


  async def handle_dialog(self, dialog):
    # Record the message on each dialog that is opened
    self.dialog_message_log.append(dialog.message)
    await dialog.dismiss()

  async def handle_console(self, console):
    # Record the error message on each dialog that is opened
    if console.type == "error":
      self.console_error_message_log.append(console.text)




  def remove_listener(self):
    self.page.remove_listener("response", self.handle_response)
    self.page.remove_listener("dialog", self.handle_dialog)
    self.page.remove_listener("console", self.handle_console)

class BrowserUrlVisit(BaseModel):
  timestamp: Optional[int] = None
  starting_url: Optional[str] = None
  ending_url: Optional[str] = None
  starting_html: Optional[str] = None
  ending_html: Optional[str] = None
  starting_storage_state: Optional[Dict[str, Any]] = None
  ending_storage_state: Optional[Dict[str, Any]] = None
  response_log: Optional[List[ResponseRecord]] = None
  dialog_message_log: Optional[List[str]] = None
  console_error_message_log: Optional[List[str]] = None

  open_url_calling_context: Optional[OpenUrlCallingContext] = None
  fill_form_calling_context: Optional[FillFormCallingContext] = None
  click_signatures_in_sequence_calling_context: Optional[ClickSignaturesInSequenceCallingContext] = None

  def get_calling_context(self) -> Optional[Any]:
    if self.open_url_calling_context is not None:
      return self.open_url_calling_context
    elif self.fill_form_calling_context is not None:
      return self.fill_form_calling_context
    elif self.click_signatures_in_sequence_calling_context is not None:
      return self.click_signatures_in_sequence_calling_context
    else:
      return None

  def write_to_directory(self, directory: str) -> str:
    browser_url_visit_json = self.model_dump_json(indent=2)
    with open(os.path.join(directory, f"browser_url_visit_{hash(browser_url_visit_json)}.json"), 'w') as file:
      print(f"Writing BrowserUrlVisit with starting_url: {self.starting_url} and ending_url: {self.ending_url} to {file.name}")
      file.write(browser_url_visit_json)
    return file.name

  @classmethod
  async def from_action(cls, page: Page, take_action: Callable[[], str], timeout: int = 3000) -> "BrowserUrlVisit":
  
    # Record data about the starting state
    starting_url = page.url
    starting_html = await page.content()
    starting_storage_state = await page.context.storage_state()

    # Add listeners that capture the request and response objects, dialog messages, and console messages
    listener = Listener(page=page)

    # Take the action, and then wait for the page to load
    timestamp = int(time.time())
    await take_action()

    await scroll_page_and_wait(page=page, timeout=timeout)

    # Record data about the ending state
    ending_url = page.url
    ending_html = await page.content()
    ending_storage_state = await page.context.storage_state()

    # Remove the listeners
    listener.remove_listener()

    browser_url_visit = pydantic_create(
      cls=BrowserUrlVisit,
      timestamp=timestamp,
      starting_url=starting_url,
      ending_url=ending_url,
      starting_html=starting_html,
      ending_html=ending_html,
      starting_storage_state=starting_storage_state,
      ending_storage_state=ending_storage_state,
      response_log=listener.response_log,
      dialog_message_log=listener.dialog_message_log,
      console_error_message_log=listener.console_error_message_log
    )
    BrowserUrlVisit.model_validate(browser_url_visit)
    return browser_url_visit


  def truncate_response_log_text(self, max_text_length: int = 10000) -> "BrowserUrlVisit":
    """
    Truncate the text in each response to the specified length in order to reduce the memory footprint of the log
    """
    for response in self.response_log:
      if response.response_text is not None and response.response_text_length > max_text_length:
        response.response_text = response.response_text[:max_text_length]
    return self


class NetworkLog(BaseModel):
  response_log: List[ResponseRecord]

  def write_to_file(self, filepath: str) -> str:
    network_log_json = self.model_dump_json(indent=2)
    with open(filepath, 'w') as file:
      print(f"Writing network_log_json to {file.name}")
      file.write(network_log_json)
    return file.name


class ActionRequest(BaseModel):
  """
  Represents an action to drive a browser

  TODO: Expand this as an interface beyond LLMs
  """
  action_name: str
  function_response_dict: Dict[str, Any]
