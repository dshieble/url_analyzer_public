from typing import Optional
from urllib.parse import urlparse
import dns.resolver
from pydantic import BaseModel

from url_analyzer.classification.browser_automation.playwright_spider import PlaywrightSpider
from url_analyzer.classification.classifier.url_classification import RichUrlClassificationResponse, classify_url
from url_analyzer.classification.browser_automation.playwright_page_manager import PlaywrightPageManager, PlaywrightPageManagerContext
from url_analyzer.classification.classifier.url_to_classify import UrlToClassify
from url_analyzer.classification.browser_automation.run_calling_context import open_url_with_context
from url_analyzer.classification.browser_automation.utilities import ScreenshotType
from url_analyzer.classification.utilities.utilities import Maybe


class MaybeRichUrlClassificationResponse(BaseModel):
  # NOTE We make this its own BaseModel rather than using Maybe[RichUrlClassificationResponse] because we want to be able to return it from the HTTP API
  content: Optional[RichUrlClassificationResponse] = None
  error: Optional[str] = None
  
def domain_resolves(url: str) -> bool:
  try:
    # Parse the domain from the URL
    parsed_url = urlparse(url)
    domain = parsed_url.netloc

    # Attempt to resolve the domain
    dns.resolver.resolve(domain, 'A')
    return True
  except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.Timeout, dns.exception.DNSException):
    return False

def validate_classification_inputs(url: str) -> Optional[str]:
  error = None
  parsed_url = urlparse(url)
  if parsed_url.scheme is None or len(parsed_url.scheme) == 0:
    error = "ERROR: URL must have a scheme (e.g. https://)"
  elif not domain_resolves(url):
    error = f"ERROR: The URL {url} was not found!"
  return error

class UrlClassifier:
  async def classify_url(self, url: str, *args, **kwargs) -> MaybeRichUrlClassificationResponse:
    raise NotImplementedError
  
class BasicUrlClassifier(UrlClassifier):
  async def classify_url(
    self,
    url: str,
    headless: bool = True,
    max_html_token_count: int = 2000,
    screenshot_type: str = ScreenshotType.VIEWPORT_SCREENSHOT
  ) -> MaybeRichUrlClassificationResponse:

    maybe_url_to_classify = await UrlToClassify.from_url_fast(
      url=url,
      screenshot_type=screenshot_type,
      headless=headless
    )
    if maybe_url_to_classify.content is not None:
      rich_url_classification_response = await classify_url(
        url_to_classify=maybe_url_to_classify.content,
        max_html_token_count=max_html_token_count,
      )
      maybe_rich_url_classification_response = MaybeRichUrlClassificationResponse(content=rich_url_classification_response)
    else:
      maybe_rich_url_classification_response = MaybeRichUrlClassificationResponse(error=maybe_url_to_classify.error)
    return maybe_rich_url_classification_response


class SpiderUrlClassifier(UrlClassifier):
  async def classify_url(
    self,
    url: str,
    headless: bool = True,
    included_fqdn_regex: Optional[str] = None,
    max_html_token_count: int = 2000,
    screenshot_type: str = ScreenshotType.VIEWPORT_SCREENSHOT
  ) -> MaybeRichUrlClassificationResponse:
    
    playwright_spider = await PlaywrightSpider.construct(
      url_list=[url],
      included_fqdn_regex=(".*" if included_fqdn_regex is None else included_fqdn_regex),
      screenshot_type=screenshot_type,
    )
    async with PlaywrightPageManagerContext(playwright_page_manager=(
      await PlaywrightPageManager.construct(headless=headless)
    )) as playwright_page_manager:
      visited_url = await playwright_spider.get_visited_url(
        url=url,
        playwright_page_manager=playwright_page_manager
      )
      visited_url.write_to_directory(directory=playwright_spider.directory)

    url_to_classify = UrlToClassify.from_visited_url(visited_url=visited_url)
    try:
      rich_url_classification_response = await classify_url(
        url_to_classify=url_to_classify,
        max_html_token_count=max_html_token_count,
      )
    except Exception as e:
      maybe_rich_url_classification_response = MaybeRichUrlClassificationResponse(error=f"Error classifying URL {url}")
    else:
      maybe_rich_url_classification_response = MaybeRichUrlClassificationResponse(content=rich_url_classification_response)
    return maybe_rich_url_classification_response

