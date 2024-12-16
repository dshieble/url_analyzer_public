
from collections import defaultdict
import random
import time
import traceback
from pydantic import BaseModel
import os
from typing import Any, Dict, List, Optional, Set, Tuple, TypeVar
import uuid
import re
import w3lib.url



from url_analyzer.classification.browser_automation.playwright_dynamic_spider import explore_page

from url_analyzer.classification.browser_automation.playwright_page_manager import PlaywrightPageManager, PlaywrightPageManagerCloneContext
from url_analyzer.classification.browser_automation.utilities import ScreenshotType, get_href_links_from_page, get_image_links_from_page, get_url_screenshot_response_from_loaded_page
from url_analyzer.classification.browser_automation.datamodel import BrowserUrlVisit, UrlScreenshotResponse
from url_analyzer.classification.browser_automation.playwright_driver import FormField, PlaywrightDriver
from url_analyzer.classification.browser_automation.run_calling_context import fill_form_on_page_worker_with_context, open_url_with_context

from url_analyzer.classification.utilities.single_visit_queue import PrefixOptimizedSingleVisitQueue
from url_analyzer.classification.utilities.utilities import Maybe, filter_url, get_base_url_from_url, load_pydantic_model_from_directory_path, pydantic_create, pydantic_validate, run_with_logs, url_to_filepath
from url_analyzer.classification.utilities.logger import BASE_LOG_DIRECTORY, Logger

URL_ASSET_REGEX = r'^http(.*)\.(js|css|png|jpg|jpeg|woff2|svg|pdf)(\?.*|)$'
MAX_BODY_TEXT_LENGTH = 10000
DEFAULT_PLAYWRIGHT_SPIDER_DIRECTORY_ROOT_PATH = os.path.join( os.path.join(os.path.join(os.path.dirname(__file__), '..'), '..'), "outputs/playwright_scanner_outputs")
SPIDER_DIRECTORY_NAME = "spider"




class VisitedUrlForm(BaseModel):
  field_name_to_value: Dict[str, str]
  browser_url_visit: BrowserUrlVisit

class VisitedUrl(BaseModel):

  url: str
  open_url_browser_url_visit: BrowserUrlVisit
  urls_on_page: Optional[List[str]] = None
  form_list: Optional[List[VisitedUrlForm]] = None
  url_screenshot_response: Optional[UrlScreenshotResponse] = None
  dynamic_browser_url_visit_list: Optional[List[BrowserUrlVisit]] = None

  @classmethod
  def construct(cls, max_text_length: Optional[int] = MAX_BODY_TEXT_LENGTH, **kwargs):
    """
    Build the visited_url from kwargs and perform some post-processing to reduce the memory footprint of the response log
    """
    visited_url = pydantic_create(cls, **kwargs)
    if max_text_length is not None:
      visited_url.open_url_browser_url_visit.truncate_response_log_text(max_text_length=max_text_length)
      if visited_url.form_list is not None:
        for visited_url_form in visited_url.form_list:
          visited_url_form.browser_url_visit.truncate_response_log_text(max_text_length=max_text_length)
    return visited_url

  def get_browser_url_visit_list(self) -> List[BrowserUrlVisit]:

    browser_url_visit_list = [self.open_url_browser_url_visit]
    if self.form_list is not None:
      browser_url_visit_list += [
        visited_url_form.browser_url_visit for visited_url_form in self.form_list
        if visited_url_form is not None
      ]
    return browser_url_visit_list


  def write_to_directory(self, directory: str) -> str:
    visited_url_json = self.model_dump_json(indent=2)
    fname = f"{url_to_filepath(self.url)}-{str(hash(visited_url_json))}.json"
    path = os.path.join(directory, fname)
    with open(path, 'w') as file:
      print(f"Writing visited url {self.url} to {file.name}")
      file.write(visited_url_json)
    return path
  


def load_visited_url_list_from_path(path: str) -> List[VisitedUrl]:
  return load_pydantic_model_from_directory_path(path=path, cls=VisitedUrl)


async def get_random_input_from_form_field(form_field: FormField) -> str:
  """
  TODO: Change this to sense if a field has some kind of validation on email address or phone number and input accordingly
  """
  options = await form_field.get_options()
  if options is None:
    random_input = str(uuid.uuid4()) + "@" + str(uuid.uuid4()) + ".com"
  else:
    random_input = random.choice(options)
  return random_input


async def _get_visited_url_form_list(playwright_page_manager: PlaywrightPageManager, verbose: bool = True) -> List[VisitedUrlForm]:
  """
  TODO: Expand this to support multiple forms on a single page. Right now this is just one form for simplicity

  TODO: Expand this to do something smarter with form fields that look like they should be email addresses

  TODO: switch to a smarter form handler like https://github.com/crawljax/crawljax/blob/master/core/src/main/java/com/crawljax/forms/FormHandler.java
  """
  driver = PlaywrightDriver(playwright_page_manager=playwright_page_manager)
  maybe_form_fields = await driver.get_form_fields()
  if maybe_form_fields.content is None:
    maybe_browser_url_visit = Maybe(error=f"ERROR getting form fields for page {playwright_page_manager.page.url}: {maybe_form_fields.error}")
  else:
    """
    TODO: this type of mapping where form fields are defined based on their text is likely not going to work in cases where a form has multiple fields with the same text. We will need to fix this.
    TODO: support manipulating the non-user visible forms as well
    """

    if verbose:
      print(f"Testing form fields {maybe_form_fields.content.user_supplied_form_field_list} on page {playwright_page_manager.page.url}")

    form_input = {
      form_field.text: (await get_random_input_from_form_field(form_field=form_field))
      for form_field in maybe_form_fields.content.user_supplied_form_field_list
    }

    # We use a calling context to produce the BrowserUrlVisit so that we can replay it in the future
    maybe_browser_url_visit = await fill_form_on_page_worker_with_context(playwright_page_manager=playwright_page_manager, url=playwright_page_manager.page.url, form_input=form_input, verbose=verbose)


  maybe_visited_url_form = maybe_browser_url_visit.apply(lambda browser_url_visit: VisitedUrlForm(
    field_name_to_value=form_input,
    browser_url_visit=browser_url_visit
  ))

  if maybe_visited_url_form.error is not None and verbose:
    print(f"ERROR submitting form on page {playwright_page_manager.page.url}: {maybe_visited_url_form.error}")

  return [] if maybe_visited_url_form.content is None else [maybe_visited_url_form.content]


class PlaywrightSpider:
  """
  TODO: Modify the dynamic spider to grab the urls in the discovered pages
  """

  def __init__(
    self,
    included_fqdn_regex: str,
    directory: str,
    excluded_url_regex: Optional[str] = None,
    verbose: bool = True, 
    explore_dynamically: bool = False,
    submit_forms: bool = True,
    screenshot_type: str = ScreenshotType.NO_SCREENSHOT,
    max_urls_per_base_url: int = 3,
    max_url_count: int = 1000,
    included_url_regex: Optional[str] = None
  ):
    self.included_fqdn_regex = included_fqdn_regex
    self.included_url_regex = included_url_regex
    self.directory = directory
    self.excluded_url_regex = excluded_url_regex
    self.verbose = verbose
    self.submit_forms = submit_forms
    self.explore_dynamically = explore_dynamically

    self.screenshot_type = screenshot_type

    # This is the largest number of different parameters we will visit for each base url
    self.max_urls_per_base_url = max_urls_per_base_url

    # The maximum number of distinct urls to visit before ending the spider
    self.max_url_count = max_url_count

    self.enqueued_base_url_to_parameterized_url_set = defaultdict(set)

    self.image_root_path = self.get_image_root_path_from_screenshot_type(
      directory=self.directory,
      screenshot_type=self.screenshot_type
    )

    self.visited_urls = {}
    self.url_queue = PrefixOptimizedSingleVisitQueue.construct(name="url_queue")
    self.skipped_urls = set()
    self.asset_urls = set()

    self.base_log_dir = os.path.join(BASE_LOG_DIRECTORY, str(int(time.time())))

  @classmethod 
  async def construct(
    cls,
    url_list: List[str],
    included_fqdn_regex: str,
    directory_root_path: Optional[str] = None,
    included_url_regex: Optional[str] = None,
    **spider_kwargs
  ) -> "PlaywrightSpider":
      
    directory_root_path = (
      directory_root_path if directory_root_path is not None else DEFAULT_PLAYWRIGHT_SPIDER_DIRECTORY_ROOT_PATH
    )

    dirname = str(int(time.time())) + "___" + ("-".join([url_to_filepath(url) for url in url_list]))[:100]
    base_directory = os.path.join(directory_root_path, dirname)
    spider_directory = await prepare_playwright_spider_directory(base_directory=base_directory)

    return PlaywrightSpider(included_fqdn_regex=included_fqdn_regex, included_url_regex=included_url_regex, directory=spider_directory, **spider_kwargs)


  def url_in_scope(self, url: str) -> bool:
    excluded_url_regex_list = None if self.excluded_url_regex is None else [self.excluded_url_regex]
    return filter_url(url=url, included_fqdn_regex=self.included_fqdn_regex, included_url_regex=self.included_url_regex, excluded_url_regex_list=excluded_url_regex_list)
    
  def url_is_asset(self, url: str) -> bool:
    return re.match(URL_ASSET_REGEX, url)

  def get_image_root_path_from_screenshot_type(self, directory: str, screenshot_type: str) -> Optional[str]:
    if screenshot_type == ScreenshotType.NO_SCREENSHOT:
      image_root_path = None
    elif screenshot_type in [ScreenshotType.VIEWPORT_SCREENSHOT, ScreenshotType.FULL_PAGE_SCREENSHOT]:
      image_root_path = os.path.join(directory, "images")
    else:
      raise ValueError(f"Invalid screenshot type {screenshot_type}")
    return image_root_path
  
  async def run(
    self,
    url_list: List[str],
    playwright_page_manager_to_clone: Optional[PlaywrightPageManager] = None,
  ):
    """
    Given set of initial urls, add these to the queue and then iteratively pop from the queue and visit each url in turn until the queue is empty

    TODO: Switch to also restarting playwright and not just the page manager on exceptions

    """
    print(f"Running PlaywrightSpider on urls: {url_list} with included_fqdn_regex: {self.included_fqdn_regex} and directory: {self.directory}")

    # The spider page manager will be repeatedly closed and cloned throughout the run, so we start by cloning the initial page manager so it doesn't get closed

    for url in url_list:
      self._enqueue_url(url=url)
    while not self.url_queue.is_empty() and len(self.url_queue.has_ever_been_enqueued) < self.max_url_count:

      url = self.url_queue.pop_from_queue()
      print(f"Popped {url} from queue! Remaining elements in queue are: {self.url_queue.queue}")
      if url in self.visited_urls:
        raise ValueError(f"Url {url} has already been visited!")

      async with PlaywrightPageManagerCloneContext(playwright_page_manager_to_clone) as spider_playwright_page_manager:
        await self._visit(url=url, playwright_page_manager=spider_playwright_page_manager)

  def _enqueue_url(self, url: str):
    """
    Add a url to the queue if it is in scope and not already visited
    """
    if not url.startswith("http"):
      print(f"Skipping url {url} because it is not a valid url")
      self.skipped_urls.add(url)
    else:

      """
      NOTE: We need the keep_fragments for cases like 'http://localhost:3000/#/register'. Otherwise the canonicalized url will be 'http://localhost:3000/' and we will miss the register page
      
      See https://w3lib.readthedocs.io/en/latest/w3lib.html
      """
      url = w3lib.url.canonicalize_url(url, keep_fragments=True)
      base_url = get_base_url_from_url(url)
      if not self.url_in_scope(url=url):
        print(f"Skipping url {url} because it is out of scope")
        self.skipped_urls.add(url)
      elif self.url_is_asset(url=url):
        print(f"Skipping url {url} because it is an asset")
        self.asset_urls.add(url)
      elif len(self.enqueued_base_url_to_parameterized_url_set[base_url]) >= self.max_urls_per_base_url:
        print(f"Skipping url {url} because the base_url {base_url} has already been enqueued {self.max_urls_per_base_url} times")
        self.skipped_urls.add(url)
      else:
        self.enqueued_base_url_to_parameterized_url_set[base_url].add(url)
        was_added = self.url_queue.add_to_queue(value=url, verbose=True)
        if was_added:
          print(f"Added url {url} to queue")
        else:
          print(f"Skipping url {url} because it has already been enqueued")


    
  async def _visit(self, url: str, playwright_page_manager: PlaywrightPageManager):
    try:
      visited_url = await self.get_visited_url(url=url, playwright_page_manager=playwright_page_manager)
    except Exception as e:
      # If we see an error then we don't re-add to the queue, but we also don't write or mark as visited
      error = traceback.format_exc()
      print(f"ERROR visiting url {url}: {error}")
    else:
      if visited_url.urls_on_page is not None:
        for url_on_page in visited_url.urls_on_page:
          self._enqueue_url(url=url_on_page)
    
      if visited_url.url != url:
        raise ValueError(f"Visited url {visited_url.url} does not match url {url}!")
      self.visited_urls[url] = visited_url
      visited_url.write_to_directory(directory=self.directory)
        

  async def get_visited_url(self, url: str, playwright_page_manager: PlaywrightPageManager) -> VisitedUrl:

    # New url that is in scope
    print(f"Opening {url}...")
 
    browser_url_visit = (await open_url_with_context(playwright_page_manager=playwright_page_manager, url=url)).unwrap()
    print(f"Opened {url}! starting_url: {browser_url_visit.starting_url} ending_url: {browser_url_visit.ending_url}")

    # We check for out of scope redirects, but we don't mark the redirecting url when this happens
    if not self.url_in_scope(url=browser_url_visit.ending_url):
      if self.verbose:
        print(f"Was redirected from url to {browser_url_visit.ending_url}, which is out of scope. Skipping...")
      self.skipped_urls.add(browser_url_visit.ending_url)
      visited_url = VisitedUrl.construct(
        url=url, open_url_browser_url_visit=browser_url_visit
      )
    else:
      logger = await Logger.construct_from_url_and_base_log_dir(url=url, base_log_dir=self.base_log_dir)
      visited_url = await get_visited_url_from_browser_url_visit(
        url=url,
        browser_url_visit=browser_url_visit,
        playwright_page_manager=playwright_page_manager,
        explore_dynamically=self.explore_dynamically,
        submit_forms=self.submit_forms,
        screenshot_type=self.screenshot_type,
        image_root_path=self.image_root_path,
        verbose=self.verbose,
        logger=logger
      )
    return visited_url


async def get_visited_url_from_browser_url_visit(
  url: str,
  browser_url_visit: BrowserUrlVisit,
  playwright_page_manager: PlaywrightPageManager,
  logger: Logger,
  explore_dynamically: bool = False,
  submit_forms: bool = True,
  verbose: bool = True,
  max_starting_signature_count_for_dynamic_exploration: Optional[int] = 10,
  max_total_sequence_signature_count_for_dynamic_exploration: Optional[int] = 20,
  screenshot_type: str = ScreenshotType.NO_SCREENSHOT,
  image_root_path: Optional[str] = None,
) -> Tuple[VisitedUrl, List[str]]:
  
  if screenshot_type != ScreenshotType.NO_SCREENSHOT:
    if image_root_path is None:
      raise ValueError("Cannot capture screenshot without image_root_path!")
    if verbose:
      logger.log(f"Taking screenshot of url {url}...")

    url_screenshot_response = await get_url_screenshot_response_from_loaded_page(
      page=playwright_page_manager.page,
      image_root_path=image_root_path,
      screenshot_type=screenshot_type
    )
    if verbose:
      logger.log(f"Wrote screenshot of url {url} to {url_screenshot_response.screenshot_path}")
  else:
    url_screenshot_response = None

  # Links
  logger.log(f"Fetching links for url {url}...")

  href_links = await get_href_links_from_page(page=playwright_page_manager.page)
  image_links = await get_image_links_from_page(page=playwright_page_manager.page)

  if explore_dynamically:
    dynamic_browser_url_visit_list, dynamic_discovered_links_set = await explore_page(
      playwright_page_manager=playwright_page_manager,
      url=url,
      max_starting_signature_count=max_starting_signature_count_for_dynamic_exploration,
      max_total_sequence_signature_count=max_total_sequence_signature_count_for_dynamic_exploration,
      verbose=verbose,
      parent_logger=logger
    )
    if verbose:
      logger.log(f"Dynamic exploration on page {url} discovered links: {dynamic_discovered_links_set}")
  else:
    dynamic_browser_url_visit_list, dynamic_discovered_links_set = [], set()

  urls_on_page_list = set(list(href_links) + list(image_links) + list(dynamic_discovered_links_set))

  if submit_forms:
    form_list = await _get_visited_url_form_list(playwright_page_manager=playwright_page_manager, verbose=verbose)
  else:
    form_list = None
  
  visited_url = VisitedUrl.construct(
    url=url,
    url_screenshot_response=url_screenshot_response,
    open_url_browser_url_visit=browser_url_visit,
    urls_on_page=urls_on_page_list,
    form_list=form_list,
    dynamic_browser_url_visit_list=dynamic_browser_url_visit_list
  )
  return visited_url


async def prepare_playwright_spider_directory(base_directory: str) -> str:
  """
  Creates the base directory that all scanner results will live in and the spider directory within that base directory
  """
  spider_directory = os.path.join(base_directory, SPIDER_DIRECTORY_NAME)
  await run_with_logs("mkdir", base_directory, process_name="mkdir base")
  await run_with_logs("mkdir", spider_directory, process_name="mkdir spider")
  await run_with_logs("mkdir", os.path.join(spider_directory, "images"), process_name="mkdir images")
  return spider_directory

async def run_playwright_spider_from_playwright_page_manager(
  url_list: str,
  included_fqdn_regex: str,
  directory_root_path: Optional[str] = None,
  playwright_page_manager_to_clone: Optional[PlaywrightPageManager] = None,
  included_url_regex: Optional[str] = None,
  **spider_kwargs
) -> PlaywrightSpider:
  """
  Args:
    url_list: The list of urls to start the spider on
    included_fqdn_regex: The regex that determines which fqdns are in scope for the spider
    playwright_page_manager: The PlaywrightPageManager to use for the spider
    directory_root_path: The root directory to write the spider results to. If not provided, we use the default directory root path
    spider_kwargs: The kwargs to pass to the PlaywrightSpider constructor
  """

  # TODO: Generate a base path that you use for both the active scanner and the spider

  directory_root_path = (
    directory_root_path if directory_root_path is not None else DEFAULT_PLAYWRIGHT_SPIDER_DIRECTORY_ROOT_PATH
  )

  dirname = str(int(time.time())) + "___" + ("-".join([url_to_filepath(url) for url in url_list]))[:100]
  base_directory = os.path.join(directory_root_path, dirname)
  spider_directory = await prepare_playwright_spider_directory(base_directory=base_directory)

  spider = PlaywrightSpider(included_fqdn_regex=included_fqdn_regex, included_url_regex=included_url_regex, directory=spider_directory, **spider_kwargs)

  await spider.run(
    url_list=url_list,
    playwright_page_manager_to_clone=playwright_page_manager_to_clone,
  )
  return spider

