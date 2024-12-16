"""
https://www.zenrows.com/blog/avoid-playwright-bot-detection#user-agent
https://github.com/AtuboDad/playwright_stealth
https://substack.thewebscraping.club/p/playwright-stealth-cdp


TODO - deal with Runtime.enable
https://github.com/kaliiiiiiiiii/undetected-playwright-python

TODO - deal with CDP signals
https://datadome.co/threat-research/how-new-headless-chrome-the-cdp-signal-are-impacting-bot-detection/
"""
from copy import deepcopy
import json
import re
import sys
import os

from dataclasses import dataclass
import io
import random
import time
from typing import Any, Callable, Dict, Generic, Iterable, List, Optional, Tuple, TypeVar
import uuid
import PIL
import PIL.Image
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from playwright._impl._page import Page
from playwright_stealth import stealth_async
from unidecode import unidecode
import json
import time
import os
from playwright.async_api._generated import Request
from playwright.async_api._generated import ElementHandle
from playwright.async_api import PlaywrightContextManager

from url_analyzer.classification.browser_automation.constants import STEALTH_INIT_SCRIPT
from url_analyzer.classification.browser_automation.datamodel import BrowserUrlVisit, scroll_page_and_wait
from url_analyzer.classification.browser_automation.utilities import NetworkTracker


async def remove_if_modified_since_header(route, request):
  # Clone the headers, excluding 'If-Modified-Since'
  headers = {k: v for k, v in request.headers.items() if k.lower() not in  ('if-modified-since', 'if-none-match')}
  
  headers['sec-ch-ua'] = '"(Not(A:Brand";v="99", "Google Chrome";v="127", "Chromium";v="127"'
  headers['sec-ch-ua-full-version-list'] = '"(Not(A:Brand";v="99.0.0.0", "Google Chrome";v="127", "Chromium";v="127"'

  # Continue the request with the modified headers
  await route.continue_(headers=headers)

async def initialize_browser_context(
  playwright: PlaywrightContextManager,
  headless: bool = True,
  proxy_url: Optional[str] = None,
  storage_state: Optional[str] = None
) -> tuple:
  
  args = []
    
  # disable navigator.webdriver:true flag. This is lifted from https://github.com/kaliiiiiiiiii/undetected-playwright-python as a simple solution to avoid detection
  # also discussed in https://stackoverflow.com/questions/53039551/selenium-webdriver-modifying-navigator-webdriver-flag-to-prevent-selenium-detec/69533548#69533548
  args.append("--disable-blink-features=AutomationControlled")
  
  if proxy_url is not None:
    # We need to ignore https errors when we run playwright through a proxy
    browser = await playwright.chromium.launch(headless=headless, proxy={"server": proxy_url}, args=args)
    context = await browser.new_context(ignore_https_errors=True, storage_state=storage_state)
  else:
    browser = await playwright.chromium.launch(headless=headless, args=args)
    context = await browser.new_context(storage_state=storage_state)

  # await context.route("**/*", remove_if_modified_since_header)
  await context.add_init_script(STEALTH_INIT_SCRIPT)
  return browser, context

@dataclass
class PlaywrightPageManager:
  """
  Wrapper around Playwright that manages a particular page and context
  """
  playwright: "Playwright"
  browser: "BrowserType"
  context: "BrowserContext"
  page: "Page"
  network_tracker: NetworkTracker
  headless: bool = True
  proxy_url: Optional[str] = None

  @classmethod
  async def prepare_page(cls, page: Page):
    async def accept(dialog):
      try:
        await dialog.accept()
      except Exception as e:
        print(f"WARNING: error in dialog.accept(): {e}")
    page.on("dialog", accept)

    ## NOTE: For now we are not using stealth_async since this seems to cause some pages to fail to load (e.g. https://nyt.com). We are using the STEALTH_INIT_SCRIPT to accomplish this instead
    # await stealth_async(page)



  @classmethod
  async def construct(cls, headless: bool = True, proxy_url: Optional[str] = None) -> "PlaywrightPageManager":
    """Initialize Playwright and start interactive session."""
    
    playwright = await async_playwright().start()
    browser, context = await initialize_browser_context(playwright=playwright, headless=headless, proxy_url=proxy_url)
    page = await context.new_page()

    # This is a hack we use only for DVWA to control the security level. This doesn't apply to anything outside of DVWA accessed through localhost.
    await context.add_cookies([
      {'name': 'security',
      'value': 'medium',
      'domain': 'localhost',
      'path': '/',
      'expires': -1,
      'httpOnly': True,
      'secure': False,
      'sameSite': 'Lax'
    }])
    await cls.prepare_page(page=page)
    return cls(
      playwright=playwright,
      browser=browser,
      context=context,
      page=page,
      network_tracker=NetworkTracker(page=page),
      headless=headless,
      proxy_url=proxy_url
    )

  @classmethod
  async def from_storage_state(
    cls,
    storage_state: str,
    headless: bool = True,
    proxy_url: Optional[str] = None
  ) -> "PlaywrightPageManager":
    playwright = await async_playwright().start()
    browser, context = await initialize_browser_context(
      playwright=playwright,
      storage_state=storage_state,
      headless=headless,
      proxy_url=proxy_url)
    page = await context.new_page()

    await cls.prepare_page(page=page)
    return cls(
      playwright=playwright,
      browser=browser,
      context=context,
      page=page,
      network_tracker=NetworkTracker(page=page),
      headless=headless,
      proxy_url=proxy_url
    )



  async def new_tab(self) -> "PlaywrightPageManager":
    """
    Create a new PlaywrightPageManager that wraps another tab using the same context
    """

    page = await self.context.new_page()
    await self.prepare_page(page=page)
  
    playwright_page_manager = PlaywrightPageManager(
      playwright=self.playwright,
      browser=self.browser,
      context=self.context,
      page=page,
      network_tracker=NetworkTracker(page=page)
    )
    return playwright_page_manager
  
  async def clone(self) -> "PlaywrightPageManager":
    """
    Create a new PlaywrightPageManager with the same browser context data. Based on https://playwright.dev/python/docs/api-testing#reuse-authentication-state.
    """
    storage_state = await self.context.storage_state()
    
    return await PlaywrightPageManager.from_storage_state(
      storage_state=storage_state,
      headless=self.headless,
      proxy_url=self.proxy_url
    )

  async def clone_and_close(self) -> "PlaywrightPageManager":
    """
    Create a new PlaywrightPageManager and close the current one. Helps to fight against memory leaks in playwright 
    """
    new_playwright_page_manager = await self.clone()
    await self.close()
    return new_playwright_page_manager


  async def close(self) -> None:
    await self.page.close()
    await self.context.close()
    await self.browser.close()
    await self.playwright.stop()

    
  async def click_locator(self, locator: "Locator", timeout: int = 5000) -> BrowserUrlVisit:
    """
    Click an element on the page, tracking all network calls
    """
    async def take_action(locator=locator, timeout=timeout): await locator.click(timeout=timeout)
    browser_url_visit = await BrowserUrlVisit.from_action(page=self.page, take_action=take_action)
    BrowserUrlVisit.model_validate(browser_url_visit)
    return browser_url_visit
  
  async def focus_and_press(self, locator: "Locator") -> BrowserUrlVisit:
    """
    Submit the form on the page by pressing the enter key, tracking all network calls
    """

    # The action needs to be a Dict[str, str], but it is only used for analytics
    async def take_action(page=self.page, locator=locator):

      # First we focus on a field (probably a form field)
      await locator.focus()

      # Then we click after triggering the focus. If this is a form field this will submit the form.
      await page.press('body', 'Enter')
    browser_url_visit = await BrowserUrlVisit.from_action(page=self.page, take_action=take_action)
    BrowserUrlVisit.model_validate(browser_url_visit)
    return browser_url_visit
  
  async def open_url(self, url: str) -> BrowserUrlVisit:
    """
    Open a url on the page, tracking all network calls
    """

    # https://stackoverflow.com/questions/68266451/navigating-to-url-waiting-until-load-python-playwright-issue
    async def take_action(page=self.page, url=url): await page.goto(url)
    # async def take_action(page=self.page, url=url): await page.goto(url, wait_until="domcontentloaded")
    browser_url_visit = await BrowserUrlVisit.from_action(page=self.page, take_action=take_action)
    BrowserUrlVisit.model_validate(browser_url_visit)
    return browser_url_visit

  async def reload_and_click(self) -> BrowserUrlVisit:
    """
    Reload the page, wait for the load to complete, and then click on the page. Useful for dismissing popups or getting around other javascript heavy things
    """
    async def take_action(page=self.page):
      await page.reload()
      await scroll_page_and_wait(page=page, timeout=3000)
      await page.mouse.click(0,0)
    browser_url_visit = await BrowserUrlVisit.from_action(page=self.page, take_action=take_action)
    BrowserUrlVisit.model_validate(browser_url_visit)
    return browser_url_visit


class PlaywrightPageManagerContext:
  """
  Very basic wrapper that allows doing 
    async with PlaywrightPageManagerContext(playwright_page_manager=playwright_page_manager) as playwright_page_manager:
      # do stuff
  to ensure that the playwright_page_manager gets closed
  """
  def __init__(self, playwright_page_manager: PlaywrightPageManager):
    self.playwright_page_manager = playwright_page_manager

  async def __aenter__(self):
    return self.playwright_page_manager

  async def __aexit__(self, *args):
    await self.playwright_page_manager.close()


  @classmethod
  async def construct(cls, **kwargs) -> "PlaywrightPageManagerContext":
    return cls(playwright_page_manager=await PlaywrightPageManager.construct(**kwargs))

class PlaywrightPageManagerCloneContext:

  def __init__(self, base_playwright_page_manager: PlaywrightPageManager):
    self.base_playwright_page_manager = base_playwright_page_manager

  async def __aenter__(self):
    self.cloned_playwright_page_manager = await self.base_playwright_page_manager.clone()
    return  self.cloned_playwright_page_manager

  async def __aexit__(self, *args):
    await self.cloned_playwright_page_manager.close()
