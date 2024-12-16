"""
TODO: Migrate calling context to the driver json API standard


The purpose of this file is to store helper methods that wrap the various methods that construct BrowserUrlVisit objects. These methods are designed to be called from the run_calling_context method, which allows them to be replayed when we do an api scan

"""
import traceback
from pydantic import BaseModel, ValidationError, field_validator
from typing import Any, Dict, List, Optional, Set, Tuple, TypeVar
from playwright.async_api import async_playwright
from urllib.parse import urljoin


from url_analyzer.classification.browser_automation.playwright_page_manager import PlaywrightPageManager, PlaywrightPageManagerCloneContext
from url_analyzer.classification.browser_automation.datamodel import BrowserUrlVisit, ClickSignaturesInSequenceCallingContext, FillFormCallingContext, OpenUrlCallingContext
from url_analyzer.classification.browser_automation.playwright_driver import PlaywrightDriver
from url_analyzer.classification.browser_automation.dynamic_spider_helpers import SignatureSequenceActionResults, click_signatures_in_sequence, clone_playwright_and_click_signatures_in_sequence_and_find_new_signatures
from url_analyzer.classification.utilities.utilities import Maybe, pydantic_validate
from url_analyzer.classification.utilities.logger import Logger


class CallingContextFunctionName:
  OPEN_URL = "open_url"
  FILL_FORM = "fill_form"
  PUSH_BUTTONS_IN_SEQUENCE = "push_buttons_in_sequence"


async def _open_url_safe(playwright_page_manager: PlaywrightPageManager, url: str) -> Maybe[BrowserUrlVisit]:
  try:
    browser_url_visit = await playwright_page_manager.open_url(url=url)
  except Exception as e:
    maybe_browser_url_visit = Maybe(error=f"ERROR opening url {url}: \n{traceback.format_exc()}\n")
  else:
    maybe_browser_url_visit = Maybe(content=browser_url_visit)
  return maybe_browser_url_visit

async def _fill_form_on_page_worker(playwright_page_manager: PlaywrightPageManager, url: str, form_input: Dict[str, str], verbose: bool = True) -> Maybe[BrowserUrlVisit]:
  """
  Given a playwright_page_manager, create a clone playwright_page_manager, open the target url, fill out the form on that clone page with the form input, and return the response

  TODO: Add a capability to follow the changing page?

  TODO: Switch the page open to be directed to the url of the form page
  
  """
  if verbose:
    print(f"Calling fill_form_on_page_worker with form_input: {form_input}")
  async with PlaywrightPageManagerCloneContext(playwright_page_manager) as clone_playwright_page_manager:

    # TODO: Potentially log this open
    await clone_playwright_page_manager.open_url(url=url)

    driver = PlaywrightDriver(playwright_page_manager=clone_playwright_page_manager)
    try:
      # TODO: Change this to exclude select and checkboxes and to make those optional
      form_fields = (await driver.get_form_fields()).unwrap()
      action_response = await driver.fill_out_form(
        form_input=form_input,
        form_fields=form_fields,
        hard_fail_on_form_fill_failure=False
      )
    except ValidationError as e:
      # Pydantic validation errors need to be broadcast loudly. If these are showing up then likely things will keep breaking. 
      raise e
    except Exception as e:
      maybe_browser_url_visit = Maybe(error=f"ERROR filling out form with input {form_input}: \n{traceback.format_exc()}\n")
    else:
      if action_response.is_success:
        maybe_browser_url_visit = Maybe(content=action_response.browser_url_visit)
      else:
        maybe_browser_url_visit = Maybe(error=action_response.error)
    finally:
      await clone_playwright_page_manager.close()
  return maybe_browser_url_visit



async def open_url_with_context(playwright_page_manager: PlaywrightPageManager, **function_arguments) -> Maybe[BrowserUrlVisit]:
  # Convenience method to wrap open_url with context
  calling_context = OpenUrlCallingContext(**function_arguments)
  maybe_browser_url_visit = await _open_url_safe(playwright_page_manager=playwright_page_manager, **calling_context.__dict__)
  if maybe_browser_url_visit.content is not None:
    maybe_browser_url_visit.content.open_url_calling_context = calling_context

  # Validate the response
  maybe_browser_url_visit.apply(lambda browser_url_visit: pydantic_validate(BrowserUrlVisit, browser_url_visit))
  return maybe_browser_url_visit


async def fill_form_on_page_worker_with_context(playwright_page_manager: PlaywrightPageManager, **function_arguments) -> Maybe[BrowserUrlVisit]:
  """
  TODO: Refactor this so the playwright cloning happens in the caller and the context replay is the only thing that is handled here
  
  """

  # Convenience method to wrap fill_form with context
  calling_context = FillFormCallingContext(**function_arguments)
  maybe_browser_url_visit = await _fill_form_on_page_worker(playwright_page_manager=playwright_page_manager, **calling_context.__dict__)
  if maybe_browser_url_visit.content is not None:
    maybe_browser_url_visit.content.fill_form_calling_context = calling_context
  return maybe_browser_url_visit


async def clone_playwright_and_click_signatures_in_sequence_and_find_new_signatures_with_context(
  playwright_page_manager: PlaywrightPageManager,
  logger: Optional[Logger] = None,
  **function_arguments
) -> Optional[SignatureSequenceActionResults]:
  # Convenience method to wrap clone_playwright_and_click_signatures_in_sequence_and_find_new_signatures
  calling_context = ClickSignaturesInSequenceCallingContext(**function_arguments)
  optional_signature_sequence_action_results = await clone_playwright_and_click_signatures_in_sequence_and_find_new_signatures(
    playwright_page_manager=playwright_page_manager, logger=logger, **calling_context.__dict__)
  if optional_signature_sequence_action_results is not None and optional_signature_sequence_action_results.browser_url_visit is not None:
    optional_signature_sequence_action_results.browser_url_visit.click_signatures_in_sequence_calling_context = calling_context
  return optional_signature_sequence_action_results



async def run_calling_context(playwright_page_manager: PlaywrightPageManager, browser_url_visit: BrowserUrlVisit) -> Maybe[BrowserUrlVisit]:
  
  if browser_url_visit.open_url_calling_context is not None:
    maybe_browser_url_visit = await open_url_with_context(
      playwright_page_manager=playwright_page_manager, **browser_url_visit.open_url_calling_context.__dict__)
  elif browser_url_visit.fill_form_calling_context is not None:
    maybe_browser_url_visit = await fill_form_on_page_worker_with_context(
      playwright_page_manager=playwright_page_manager, **browser_url_visit.fill_form_calling_context.__dict__)
  elif browser_url_visit.click_signatures_in_sequence_calling_context is not None:
    optional_signature_sequence_action_results = await clone_playwright_and_click_signatures_in_sequence_and_find_new_signatures_with_context(
      playwright_page_manager=playwright_page_manager, **browser_url_visit.click_signatures_in_sequence_calling_context.__dict__)
    maybe_browser_url_visit = (
      Maybe(error=f"clone_playwright_and_click_signatures_in_sequence_and_find_new_signatures_with_context returned None")
      if optional_signature_sequence_action_results is None
      else Maybe(content=optional_signature_sequence_action_results.browser_url_visit)
    )
  else:
    raise ValueError("browser_url_visit does not have a calling context")
  
  return maybe_browser_url_visit

