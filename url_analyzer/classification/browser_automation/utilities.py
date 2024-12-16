"""
https://www.zenrows.com/blog/avoid-playwright-bot-detection#user-agent
https://github.com/AtuboDad/playwright_stealth
"""
import asyncio
import json
import re
import os

import time
from typing import Dict, List, Optional, Set, Tuple
import uuid
import PIL.Image
from bs4 import BeautifulSoup, Comment
from playwright.async_api import async_playwright
from playwright._impl._page import Page
from playwright_stealth import stealth_async
from unidecode import unidecode
import inscriptis
import json
import time
import os
from playwright.async_api._generated import Request
import curlify
from playwright.async_api._generated import ElementHandle, Locator
from urllib.parse import urljoin

from url_analyzer.classification.utilities.file_utils import AsyncFileClient
from url_analyzer.classification.browser_automation.datamodel import NetworkLog, PageLoadResponse, UrlScreenshotResponse, scroll_page_and_wait, wait_for_load_state_safe
from url_analyzer.classification.browser_automation.response_record import get_response_log


class ScreenshotType:
  VIEWPORT_SCREENSHOT = "viewport"
  FULL_PAGE_SCREENSHOT = "full_page"
  NO_SCREENSHOT = "no_screenshot"


GET_OUTER_HTML_JAVASCRIPT_FN = """
  async function getOuterHTML(element) {
    return element.outerHTML;
  }
  """
MAX_BODY_TEXT_LENGTH = 10000
DEFAULT_IMAGE_ROOT_PATH = os.path.join(os.path.dirname(__file__), '..', 'outputs', 'images')

async def get_outer_html_list_from_locator_list(locator_list: List[Locator]) -> List[str]:
  return await asyncio.gather(*[locator.evaluate(GET_OUTER_HTML_JAVASCRIPT_FN) for locator in locator_list])

async def load_page(
  page: Page,
  url: str,
  timeout: int = 5000,
) -> PageLoadResponse:
  """
  Args:
    page: A playwright page object
    url: The url to load
  Returns:
    A tuple of 
      page_loaded_successfully: A boolean indicating whether the page loaded correctly
      page_response_status: An integer if it was possible to reach the page without an error
      page_loading_error: An error if it was not possible to reach the page without an error
  """
  try:
    page_response = await page.goto(url)
  except Exception as e:
    page_load_response = PageLoadResponse(
      page_loaded_successfully=False,
      page_loading_error=str(e)
    )
  else:
    await wait_for_load_state_safe(page, state='networkidle', timeout=5000)
    await page.wait_for_timeout(timeout)
    
    page_load_response = PageLoadResponse(
      page_loaded_successfully=True,
      page_response_status=page_response.status,
      # Take the url from the page we landed on (not the initial page response object) and remove the trailing slash from final destination url
      page_final_destination_url=page.url.rstrip()
    )
  return page_load_response


async def get_html_and_screenshot(
  page: Page,
  full_page: bool = False
) -> Tuple[str, Optional[bytes]]:
  """
  Get the html and screenshot from a page. Does not reload the page
  """
  html = await page.content()
  if len(html) <= 39:
    # Empty html has just html, head, and body
    screenshot = None
  else:
    screenshot = await page.screenshot(type="png", full_page=full_page)
  return html, screenshot


async def get_url_screenshot_response_from_loaded_page(
  page: Page,
  image_root_path: Optional[str] = None,
  page_load_response: Optional[PageLoadResponse] = None,
  scroll_timeout: int = 500,
  timestamp: Optional[int] = None,
  client: Optional[AsyncFileClient] = None,
  screenshot_type: str = ScreenshotType.VIEWPORT_SCREENSHOT
) -> UrlScreenshotResponse:
  """
  Take a screenshot from a page that is assumed to have already been loaded and therefore does not need to be reloaded. The screenshot will be written to s3.
  """

  if screenshot_type == ScreenshotType.VIEWPORT_SCREENSHOT:
    take_full_page_screenshot = False
  elif screenshot_type == ScreenshotType.FULL_PAGE_SCREENSHOT:
    take_full_page_screenshot = True
  else:
    raise ValueError(f"Invalid screenshot_type {screenshot_type}")

  page_load_response = PageLoadResponse(page_loaded_successfully=True) if page_load_response is None else page_load_response
  timestamp = int(time.time()) if timestamp is None else timestamp
  try:
    # Scroll to the top of the page, useful for forcing the page to load
    await scroll_page_and_wait(page=page, timeout=scroll_timeout)
  except Exception as e:
    # The page loaded, but we failed to scroll to the top of the page
    url_screenshot_response = UrlScreenshotResponse(
      url=page.url, timestamp=timestamp, page_load_response=page_load_response, navigation_error=str(e))
  else:
    try:
      html, screenshot_bytes = await get_html_and_screenshot(
        page=page, full_page=take_full_page_screenshot
      )
    except Exception as e:
      url_screenshot_response = UrlScreenshotResponse(
        url=page.url, timestamp=timestamp, page_load_response=page_load_response, content_error=str(e))
    else:
      url_screenshot_response = await UrlScreenshotResponse.from_screenshot_bytes(
        screenshot_bytes=screenshot_bytes,
        url=page.url,
        image_root_path=image_root_path,
        timestamp=timestamp,
        html=html,
        page_load_response=page_load_response,
        client=client)
  return url_screenshot_response

async def get_url_screenshot_response(
  page: Page,
  url: Optional[str] = None,
  scroll_timeout: int = 500,
  screenshot_type: str = ScreenshotType.VIEWPORT_SCREENSHOT,
) -> UrlScreenshotResponse:
  url = page.url if url is None else url
  # NOTE: Page is already assumed to have been created and shrouded in stealth
  timestamp = int(time.time())
  
  
  page_load_response = await load_page(page=page, url=url, timeout=scroll_timeout)

  if not page_load_response.page_loaded_successfully and page_load_response.page_loading_error is not None:
    url_screenshot_response = UrlScreenshotResponse(
      url=url, timestamp=timestamp, page_load_response=page_load_response)
  elif not page_load_response.page_loaded_successfully and page_load_response.page_response_status is not None:
    url_screenshot_response = UrlScreenshotResponse(
      url=url, timestamp=timestamp, page_load_response=page_load_response)
  else:
    url_screenshot_response = await get_url_screenshot_response_from_loaded_page(
      page=page,
      scroll_timeout=scroll_timeout,
      timestamp=timestamp,
      screenshot_type=screenshot_type
    )
    
              
  return url_screenshot_response



async def create_context_and_get_url_screenshot_response(
  browser: "BrowserType",
  url: str,
  *args,
  **kwargs
) -> UrlScreenshotResponse:
  context = await browser.new_context()
  page = await context.new_page()
  await stealth_async(page)
  return await get_url_screenshot_response(page=page, url=url, *args, **kwargs)


async def get_url_screenshot_response_from_url(
  url: str,
  *args,
  **kwargs
) -> UrlScreenshotResponse:
  """
  Args:
    url: The url to load
  Returns:
    The page response and content
  """
  async with async_playwright() as playwright_context_manager:
    browser = await playwright_context_manager.chromium.launch(headless=True)
    return await create_context_and_get_url_screenshot_response(
      browser=browser, url=url, *args, **kwargs)


def remove_html_comments(html: str) -> str:
  """
  Remove all html comments from a string
  """
  soup = BeautifulSoup(html, 'html.parser')
  for comment in soup.find_all(text=lambda text: isinstance(text, Comment)):
    comment.extract()
  return str(soup)

def remove_html_metadata(html: str):
  """
  Removes all meta tags, comments, headers, script tags, and style tags from an html string. Also removes all tag attributes.
  
  """
  soup = BeautifulSoup(html, 'html.parser')

  # Find and remove elements inside 'head' tag
  soup.head = ""

  # Remove all script and style tags
  for script in soup(["script", "style"]):
    script.decompose()
  
  # Remove all meta tags
  for meta in soup.find_all("meta"):
    meta.decompose()

  # Remove all comments
  for element in soup(text=lambda text: isinstance(text, Comment)):
    element.extract()

  # Remove attributes that are not necessary to render
  for tag in soup():
    data_attrs = [attr for attr in tag.attrs if attr.startswith("data-")]
    for data_attr in data_attrs:
      del tag[data_attr]

    aria_attrs = [attr for attr in tag.attrs if attr.startswith("aria-")]
    for aria_attr in aria_attrs:
      del tag[aria_attr]

    # Remove some tags that are important
    for k in ['crossorigin', 'class', 'tabindex', 'lang', 'dir', 'width', 'height', 'loading', "d"]:
      del tag[k]
      

  return str(soup)



def remove_hidden_elements(html: str):
  """
  Remove elements that are hidden
  """
  soup = BeautifulSoup(html, 'html.parser')
  
  # Find and remove hidden elements
  for tag in soup.select('[style*="display: none"], [style*="visibility: hidden"], [hidden=""], [hidden], [type="hidden"], [style="display:none"], [style="visibility:hidden"], [aria-hidden="true"]'):
    tag.decompose()

  # Return the modified HTML string
  return str(soup)


def get_visible_text_from_html(html: str):
  html = remove_hidden_elements(html=html)
  html = remove_html_metadata(html=html)
  return inscriptis.get_text(html)


def is_complete_sentence(text: str) -> bool:
  return re.search(r"[.!?]\s*$", text) is not None\


def prettify_text(text: str, limit: Optional[int] = None) -> str:
  """Prettify text by removing extra whitespace and converting to lowercase."""
  text = re.sub(r"\s+", " ", text)
  text = text.strip().lower()
  text = unidecode(text)
  if limit:
    text = text[:limit]
  return text


def truncate_string_from_last_occurrence(string: str, character: str) -> str:
  """Truncate a string from the last occurrence of a character."""
  last_occurrence_index = string.rfind(character)
  if last_occurrence_index != -1:
    truncated_string = string[: last_occurrence_index + 1]
    return truncated_string
  else:
    return string


async def _has_inner_html(locator: Locator) -> bool:
  try:
    inner_html = await locator.inner_html()
  except Exception as e:
    inner_html = None
  return inner_html is not None and len(inner_html) > 0
    
async def _locator_is_navigable(locator: Locator) -> bool:
  is_navigable_js = """
  (element) => {
    while (element) {
      if (element.tagName.toLowerCase() === 'a' || element.hasAttribute('href')) {
        return true;
      }
      element = element.parentElement;
    }
    return false;
  }
  """
  return await locator.evaluate(is_navigable_js)

async def _locator_is_interactable(
  locator: Locator,
  verbose: bool = False,
  include_all_clickable: bool = False,
  interactable_tagname_set: Optional[Set[str]] = None,
  interactable_role_set: Optional[Set[str]] = None
) -> bool:
  """
  TODO: Make changes to this so that we can filter the buttons presented to the LLM to just "real" buttons but we can still provide the full list of buttons to the dynamic playwright spider
  
  """
  interactable_tagname_set = interactable_tagname_set if interactable_tagname_set is not None else {
    "a", "button", "select", "textarea", "input"
  }
  interactable_role_set = interactable_role_set if interactable_role_set is not None else { 
    'button', 'tooltip', 'dialog', 'navigation', 'link', 'menuitem', 'menuitemcheckbox', 'menuitemradio', 'option', 'radio', 'switch', 'tab'
  }
  try:
    is_interactable_tagname =  str(await locator.evaluate("(element) => { return element.tagName; }")).lower() in interactable_tagname_set
    is_interactable_role =  str(await locator.evaluate("(element) => { return element.role; }")).lower()  in interactable_role_set
    is_interactable = is_interactable_tagname or is_interactable_role
    if not is_interactable and include_all_clickable:
      # Expand the scope to also include all elements that appear clickable
      is_clickable = """
      (element) => {
        if (window.getComputedStyle(element).cursor === 'pointer') {
          return true;
        }
        return false;
      }
      """
      is_interactable = await locator.evaluate(is_clickable)
  except Exception as e:
    if verbose:
      print(f"Error evaluating locator {locator}: {e}")
    is_interactable = False
  return is_interactable

async def _dedup_locators_by_outer_html(locator_list: List[Locator]) -> List[Locator]:
  outer_html_list = await get_outer_html_list_from_locator_list(locator_list)
  outer_html_to_clickable_locator = {outer_html: locator for outer_html, locator in zip(outer_html_list, locator_list)}
  deduped_clickable_locator_list = list(outer_html_to_clickable_locator.values())
  return deduped_clickable_locator_list


async def get_interactable_locators_from_page(
  page_or_frame: "Page",
  filter_invisible: bool = True,
  filter_navigable: bool = True,
  filter_disabled: bool = False,
  **locator_is_interactable_kwargs
) -> List[Locator]:
  all_locator_list = [locator for locator in await page_or_frame.locator('*').all()]

  is_interactable_list = await asyncio.gather(*[
    _locator_is_interactable(locator=locator, **locator_is_interactable_kwargs) for locator in all_locator_list])
 
  # Locators that pass the "fetch all locators and filter" stage
  raw_clickable_locator_list = [locator for locator, is_interactable in zip(all_locator_list, is_interactable_list) if is_interactable]

  # Locators that have a matching label or aria-label
  raw_clickable_locator_list += await page_or_frame.get_by_label("click", exact=False).all()
  
  clickable_locator_list = await _dedup_locators_by_outer_html(raw_clickable_locator_list)

  if filter_disabled:
    is_enabled_list = await asyncio.gather(*[locator.is_enabled() for locator in clickable_locator_list])
    clickable_locator_list = [locator for locator, is_enabled in zip(clickable_locator_list, is_enabled_list) if is_enabled]

  if filter_invisible:
    is_visible_list = await asyncio.gather(*[locator.is_visible() for locator in clickable_locator_list])
    clickable_locator_list = [locator for locator, is_visible in zip(clickable_locator_list, is_visible_list) if is_visible]

  if filter_navigable:
    # Filter out buttons that just trigger a page change
    navigable_list = await asyncio.gather(*[_locator_is_navigable(locator=locator) for locator in clickable_locator_list])
    clickable_locator_list = [locator for locator, is_navigable in zip(clickable_locator_list, navigable_list) if not is_navigable]

  return clickable_locator_list




async def get_text_input_field_list(page_or_frame: "Page") -> List[Locator]:
  """
  Get the first text input on a page
  """
  return [e for e in await page_or_frame.locator("textarea, input").all()]


async def get_and_fill_text_input_field_list(page_or_frame: "Page") -> List[Locator]:
  """
  Get the first text input on a page

  TODO: You'll probably want to change this to make the injection of random text before clicking and submitting a bit smarter. For example you'll want automatic phone number and email address field detection
  """
  text_input_field_locators = await get_text_input_field_list(page_or_frame=page_or_frame)
  error_list = await asyncio.gather(*[safe_fill(locator=locator, value=str(uuid.uuid4()),  timeout=5000) for locator in text_input_field_locators])
  return [locator for locator, error in zip(text_input_field_locators, error_list) if error is None]

def get_cookie_list_from_headers(fqdn: str, all_headers: Dict[str, str]) -> List[Dict[str, str]]:
  """
  Given a playwright request, grab the cookies from the request and write them to a file
  """
  cookie_string = all_headers['cookie']
  cookie_list = []
  for cookie in cookie_string.split(";"):
    fields = cookie.strip().split("=")
    assert len(fields) == 2
    cookie_list.append({
      "name": fields[0],
      "value": fields[1],
      "domain": fqdn,
      "path":
    "/"})
  return cookie_list




async def write_cookies_to_file(fqdn: str, all_headers: Dict[str, str], destination_cookie_json_path: str) -> str:
  """
  Given a playwright request, grab the cookies from the request and write them to a file
  """
  if os.path.exists(destination_cookie_json_path):
    archive_path = f'/tmp/{int(time.time())}'
    print(f"Archiving existing {destination_cookie_json_path} to {archive_path}")
    os.system(f"mv {destination_cookie_json_path} {archive_path}")

  cookie_list = get_cookie_list_from_headers(fqdn=fqdn, all_headers=all_headers)
  print(f"Writing cookies to {destination_cookie_json_path}! Cookies: \n---\n{cookie_list}\n---\n")
  with open(destination_cookie_json_path, 'w') as f:
    f.write(json.dumps(cookie_list))
  return destination_cookie_json_path


async def safe_fill(locator: Locator, *args, **kwargs) -> Optional[str]:
  # Returns None if the fill is successful, otherwise returns the error message
  try:
    await locator.fill(*args, **kwargs)
  except Exception as e:
    error = str(e)
  else:
    error = None
  return error


async def get_href_links_from_page(page: "Page") -> List[str]:
  """
  Given a playwright Page, return a list of all href links on the page
  """
  url_list = []
  link_locator_list = await page.locator("a").all()
  for link_locator in link_locator_list:
    relative_url = await link_locator.get_attribute("href")
    if isinstance(relative_url, str):
      url_list.append(urljoin(page.url, relative_url))
  return url_list


async def get_image_links_from_page(page: "Page") -> List[str]:
  """
  Given a playwright Page, return a list of all image links on the page
  """
  image_locator_link = await page.locator("img").all()
  image_links = []
  for img_locator in image_locator_link:
    src = await img_locator.get_attribute("src")
    if src:
      absolute_src = urljoin(page.url, src)
      image_links.append(absolute_src)

    srcset = await img_locator.get_attribute("srcset")
    if srcset:
      # srcset can contain multiple URLs, separated by commas
      for src in srcset.split(","):
        # Each entry in srcset has the form 'url size'
        # We split by whitespace and take the first part to get the URL
        src = src.split()[0]
        absolute_src = urljoin(page.url, src)
        image_links.append(absolute_src)
  return image_links




class NetworkTracker:
  # Track the network calls that a page makes

  def __init__(self, page: Page):
    self.playwright_response_list = []
    page.on("response", lambda response: self.playwright_response_list.append(response))

  async def get_network_log(self):
    response_log = await get_response_log(response_list=self.playwright_response_list)
    return NetworkLog(response_log=response_log)

  def write_network_log(self, path: str):
    with open(path, "w"):
      json.dump(self.get_network_log(), path)

