import base64
import logging
import os
from typing import List, Optional

from pydantic import BaseModel
from url_analyzer.classification.browser_automation.playwright_spider import VisitedUrl
from url_analyzer.classification.browser_automation.response_record import ResponseRecord
from url_analyzer.classification.browser_automation.datamodel import UrlScreenshotResponse
from url_analyzer.classification.browser_automation.playwright_page_manager import PlaywrightPageManager, PlaywrightPageManagerContext
from url_analyzer.classification.browser_automation.run_calling_context import open_url_with_context
from url_analyzer.classification.browser_automation.utilities import ScreenshotType, get_href_links_from_page, get_image_links_from_page, get_url_screenshot_response_from_loaded_page
from url_analyzer.classification.utilities.utilities import Maybe

IMAGE_ROOT_PATH = os.path.join(
  os.path.join(os.path.join(os.path.join(os.path.dirname(__file__), '..'), '..'), '..'), "outputs/images")

class UrlToClassify(BaseModel):
  url: str
  html: str
  url_screenshot_response: Optional[UrlScreenshotResponse] = None
  urls_on_page: Optional[list[str]] = None
  response_log: Optional[List[ResponseRecord]] = None

  @classmethod
  def from_visited_url(cls, visited_url: VisitedUrl) -> "UrlToClassify":
    return cls(
      url=visited_url.url,
      html=visited_url.open_url_browser_url_visit.ending_html,
      url_screenshot_response=visited_url.url_screenshot_response,  
      urls_on_page=visited_url.urls_on_page,
      response_log=visited_url.open_url_browser_url_visit.response_log
    )
  
  @classmethod
  async def from_url_fast(
    cls,
    url: str,
    screenshot_type: str = ScreenshotType.VIEWPORT_SCREENSHOT,
    headless: bool = True
  ) -> "Maybe[UrlToClassify]":
    async with PlaywrightPageManagerContext(playwright_page_manager=(
      await PlaywrightPageManager.construct(headless=headless)
    )) as playwright_page_manager:

      try:
        browser_url_visit = (await open_url_with_context(playwright_page_manager=playwright_page_manager, url=url)).unwrap()
      except Exception as e:
        logging.error(f"Error opening url: {url} \n-----\n {e} \n-----\n")
        return Maybe(error=f"Error opening url: {url}")
      else:
        url_screenshot_response = await get_url_screenshot_response_from_loaded_page(
          page=playwright_page_manager.page,
          image_root_path=IMAGE_ROOT_PATH,
          screenshot_type=screenshot_type
        )

        href_links = await get_href_links_from_page(page=playwright_page_manager.page)
        image_links = await get_image_links_from_page(page=playwright_page_manager.page)
        urls_on_page = set(href_links + image_links)

        return Maybe(content=cls(
          url=browser_url_visit.ending_url,
          html=browser_url_visit.ending_html,
          url_screenshot_response=url_screenshot_response,
          urls_on_page=urls_on_page,
          response_log=browser_url_visit.response_log
        ))
