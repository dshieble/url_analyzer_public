"""
Logic for locating and interacting with elements on a page using Playwright between multiple browser instances
"""

import re
from dataclasses import dataclass
import traceback
from typing import List, Optional, Set, Tuple
from playwright.async_api._generated import Locator




from url_analyzer.classification.browser_automation.utilities import get_and_fill_text_input_field_list, get_href_links_from_page, get_image_links_from_page, get_interactable_locators_from_page, get_outer_html_list_from_locator_list, get_text_input_field_list, safe_fill
from url_analyzer.classification.browser_automation.datamodel import BrowserUrlVisit, SignatureHandle, SignatureSequence
from url_analyzer.classification.browser_automation.playwright_page_manager import PlaywrightPageManager, PlaywrightPageManagerCloneContext
from url_analyzer.classification.utilities.utilities import Maybe
from url_analyzer.classification.utilities.logger import Logger




class SignatureHandleKind:
  CLICK = "click"
  SUBMIT = "submit"

@dataclass
class SignatureSequenceActionResults:
  discovered_signature_sequence_list: List[SignatureSequence]
  browser_url_visit: Optional[BrowserUrlVisit]
  discovered_links_set: Set[str]



# TODO: Right now this will put you into an infinite loop because the signature can change in response to form fill and submission actions, causing the changed signature to get re-picked up

async def get_session_signature(locator: Locator, logger: Logger) -> str:
  try:
    return (await get_outer_html_list_from_locator_list(locator_list=[locator]))[0]
  except Exception as e:
    logger.log(f"[get_session_signature] EXCEPTION in locator: {locator}")
    raise e


async def get_session_signatures(locator_list: List[Locator], logger: Logger) -> List[str]:
  """
  Ideally this should be 
    locator_session_signature_list = await asyncio.gather(*[get_session_signature(locator=locator) for locator in locators])
  However, this seems to trigger a weird playwright bug in which the locators get garbage collected during async gather. As a result we need to do this the slow way
  """
  return [await get_session_signature(locator=locator, logger=logger) for locator in locator_list]

  # TODO: Use this function to bypsss ssssion jks



async def get_signature(locator: Locator) -> str:
  """
  TODO:
    - use outerHTML to distinguish between old and new
    - use signature within the pool of new only and old only to distinguish what to grab
    - write a test to capture this

  The goal of this method is to derive a signature for a particular HTML element that satisfies the following characteristics
    - The signature must not change when the page is reloaded
    - The signature must not
  
  """


  GET_SIGNATURE_JAVASCRIPT = """
  async function getSignature(element) {
    let imgSrc = Array.from(element.querySelectorAll('img')).map(img => img.src).join(',');
    let src = element.src;
    let text = element.innerText;
    let tagName = element.tagName;
    let role = element.role;
    return `tag=[${tagName}]_role=[${role}]_text=[${text}]_src=[${src}]_image=[${imgSrc}]`;
  }
  """
  # Returns a signature to identify this element across reloads. This may collide with other signatures
  return await locator.evaluate(GET_SIGNATURE_JAVASCRIPT)


async def get_signatures(locator_list: List[Locator]) -> List[str]:
  """
  Ideally this should be 
    locator_signature_list = await asyncio.gather(*[get_signature(locator=locator) for locator in locators])
  However, this seems to trigger a weird playwright bug in which the locators get garbage collected during async gather. As a result we need to do this the slow way
  """
  return [await get_signature(locator=locator) for locator in locator_list]


async def get_interactable_element_signature_and_session_signatures(page: "Page") -> List[Tuple[str, str]]:

  fn = """
  async function getSignature(element) {
    let imgSrc = Array.from(element.querySelectorAll('img')).map(img => img.src).join(',');
    let src = element.src;
    let text = element.innerText;
    let tagName = element.tagName;
    let role = element.role;
    return `tag=[${tagName}]_role=[${role}]_text=[${text}]_src=[${src}]_image=[${imgSrc}]`;
  }

  async function getSessionSignature(element) {
    return element.outerHTML;
  }

  const interactableTagnames = ['a', 'button', 'select', 'textarea', 'input'];
  const interactableRoles = ['button', 'tooltip', 'dialog', 'navigation', 'link', 'menuitem', 'menuitemcheckbox', 'menuitemradio', 'option', 'radio', 'switch', 'tab'];
  
  let elements = Array.from(document.querySelectorAll('*'));
  
  // Filter elements based on tag name and role
  elements = elements
    .filter((element) => {
      const tagName = element.tagName.toLowerCase();
      const role = element.getAttribute('role')?.toLowerCase();
      return interactableTagnames.includes(tagName) || interactableRoles.includes(role);
    })
    .filter((element) => element.offsetWidth > 0 && element.offsetHeight > 0)
    .filter((element) => !['a', 'area'].includes(element.tagName.toLowerCase()));

  () => {elements};
  """
  return await page.evaluate(fn)


async def take_action_on_signature_handle(
  signature_handle: SignatureHandle,
  playwright_page_manager: PlaywrightPageManager,
  logger: Logger,
  excluded_session_signature_set: Optional[Set[str]] = None
) -> Optional[BrowserUrlVisit]:

  if signature_handle.inject_random_text_in_all_inputs:
    # TODO: You'll probably want to change this to make the injection of random text before clicking and submitting a bit smarter
    # We first fill all of the text input fields with random text
    await get_and_fill_text_input_field_list(page_or_frame=playwright_page_manager.page)

  locator_list = await get_locators_from_signature_set(
    playwright_page_manager=playwright_page_manager, signature_set={signature_handle.signature}, excluded_session_signature_set=excluded_session_signature_set, logger=logger)

  if len(locator_list) == 0:
    signatures_on_page = await get_signatures(locator_list=await playwright_page_manager.page.locator('*').all())
    logger.log(
      f"\n-------\n[take_action_on_signature_handle - {signature_handle.kind}] Could not find any elements with signature {signature_handle.signature}. Discovered signatures are {signatures_on_page}\n-------\n"
    )
    optional_browser_url_visit = None
  else:
    locator = locator_list[0]

    if signature_handle.kind == SignatureHandleKind.CLICK:
      # We choose the first locator in the list arbitrarily
      logger.log(
        f"\n-------\n[take_action_on_signature_handle - CLICK] Clicking element with signature {signature_handle.signature}\n-------\n"
      )
      optional_browser_url_visit = await playwright_page_manager.click_locator(locator=await locator, timeout=30000)
    elif signature_handle.kind == SignatureHandleKind.SUBMIT:
      # We choose the first locator in the list arbitrarily
      logger.log(
        f"\n-------\ntake_action_on_signature_handle - Submit] Submitting element with signature {signature_handle.signature}\n-------\n"
      )
      optional_browser_url_visit = await playwright_page_manager.focus_and_press(locator=await locator)
    else:
      logger.log(
        f"\n-------\n[ERROR - take_action_on_signature_handle] Unknown signature_handle.kind {signature_handle.kind}\n-------\n"
      )
      raise ValueError(f"Unknown signature_handle.kind {signature_handle.kind}")

  logger.log(f"\n\n[take_action_on_signature_handle] called on [{signature_handle.signature}] COMPLETED!!!!\n\n")
  return optional_browser_url_visit



async def get_locators_from_signature_set(
  playwright_page_manager: PlaywrightPageManager,
  signature_set: Set[str],
  logger: Logger,
  excluded_session_signature_set: Optional[Set[str]] = None
) -> List[Locator]:
  # Returns a list of locators that match the signature

  excluded_session_signature_set = set() if excluded_session_signature_set is None else excluded_session_signature_set
  locator_list = await playwright_page_manager.page.locator('*').all()


  locator_signature_list = await get_signatures(locator_list=locator_list) 
  locator_session_signature_list = await get_session_signatures(locator_list=locator_list, logger=logger) 


  return [
    locator
    for locator, locator_signature, locator_session_signature in zip(locator_list, locator_signature_list, locator_session_signature_list)
    if locator_signature in signature_set and locator_session_signature not in excluded_session_signature_set
  ]


async def get_signatures_from_page(
  playwright_page_manager: PlaywrightPageManager,
  logger: Logger,
  excluded_session_signature_set: Optional[Set[str]] = None,
  fill_textboxes: bool = True,
  **interactable_locators_kwargs
) -> Tuple[Set[str], Set[str], Set[str]]:
  # Define a JavaScript function to check if an element matches the signature

  text_input_field_locators = list(
    await get_and_fill_text_input_field_list(page_or_frame=playwright_page_manager.page)
    if fill_textboxes else
    await get_text_input_field_list(page_or_frame=playwright_page_manager.page)
  )
  unfiltered_text_input_field_signatures = list(await get_signatures(locator_list=text_input_field_locators))

  interactable_locators = list(await get_interactable_locators_from_page(page_or_frame=playwright_page_manager.page, **interactable_locators_kwargs))
  unfiltered_interactable_signatures = list(await get_signatures(locator_list=interactable_locators))

  # Exclude the signatures that belong to locators whose session signatures are in the excluded set
  if excluded_session_signature_set is not None and len(excluded_session_signature_set) > 0:
    unfiltered_text_input_field_session_signatures = list(await get_session_signatures(locator_list=text_input_field_locators, logger=logger))
    excluded_text_input_field_locator_indices = [i for i in range(len(text_input_field_locators)) if unfiltered_text_input_field_session_signatures[i] in excluded_session_signature_set]
    included_text_input_field_locator_indices = [i for i in range(len(text_input_field_locators)) if unfiltered_text_input_field_session_signatures[i] not in excluded_session_signature_set]

    unfiltered_interactable_session_signatures = list(await get_session_signatures(locator_list=interactable_locators, logger=logger))
    excluded_interactable_locator_indices = [i for i in range(len(interactable_locators)) if unfiltered_interactable_session_signatures[i] in excluded_session_signature_set]
    included_interactable_locator_indices = [i for i in range(len(interactable_locators)) if unfiltered_interactable_session_signatures[i] not in excluded_session_signature_set]

    logger.log(
      f"[get_signatures_from_page] len(excluded_text_input_field_locator_indices): {excluded_text_input_field_locator_indices} len(included_text_input_field_locator_indices): {len(included_text_input_field_locator_indices)} len(excluded_interactable_locator_indices): {len(excluded_interactable_locator_indices)} len(included_interactable_locator_indices): {len(included_interactable_locator_indices)}"
    )

    excluded_signatures = set(
      [unfiltered_text_input_field_signatures[i] for i in excluded_text_input_field_locator_indices] +
      [unfiltered_interactable_signatures[i] for i in excluded_interactable_locator_indices]
    )
    text_input_field_signatures = set([unfiltered_text_input_field_signatures[i] for i in included_text_input_field_locator_indices])
    interactable_signatures = set([unfiltered_interactable_signatures[i] for i in included_interactable_locator_indices])
  else:
    excluded_signatures = set()
    text_input_field_signatures = set(unfiltered_text_input_field_signatures)
    interactable_signatures = set(unfiltered_interactable_signatures)



  return interactable_signatures, text_input_field_signatures, excluded_signatures



async def reload_url_until_signatures_appear_and_get_signatures(
  playwright_page_manager: PlaywrightPageManager,
  logger: Logger,
  num_reloads: int = 10,
  min_elements: Optional[int] = 3,
  required_signatures: Optional[Set[str]] = None,
  required_signatures_regex: Optional[str] = None,
  **kwargs
) ->  Set[str]:
  # Needed to handle cases where we need to reload the page before the javascript loads
  for _ in range(num_reloads):
    interactable_signatures, text_input_field_signatures, _ = await get_signatures_from_page(playwright_page_manager=playwright_page_manager, logger=logger, **kwargs)

    all_signatures = interactable_signatures.union(text_input_field_signatures)
    if min_elements is not None and len(all_signatures) < min_elements:
      logger.log(
        f"Found {len(all_signatures)} elements ({all_signatures}), which is fewer than the minimum of {min_elements}. Reloading page {playwright_page_manager.page.url}...")
      await playwright_page_manager.reload_and_click()
    elif required_signatures is not None and not set(required_signatures).issubset(all_signatures):
      missing_signatures = set(required_signatures).difference(all_signatures)
      logger.log(
        f"Found {len(all_signatures)} elements ({all_signatures}), but missing required signatures {missing_signatures}. Reloading page {playwright_page_manager.page.url}...")
      await playwright_page_manager.reload_and_click()
    elif required_signatures_regex is not None and not any(re.match(required_signatures_regex, signature) for signature in all_signatures):
      logger.log(
        f"Found {len(all_signatures)} elements ({all_signatures}), but no required signatures matching regex {required_signatures_regex}. Reloading page {playwright_page_manager.page.url}...")
      await playwright_page_manager.reload_and_click()
    else:
      all_signatures_string = "\n-".join(all_signatures)
      logger.log(
        f"[reload_url_until_signatures_appear_and_get_signatures] Found {len(all_signatures)} elements and all required signatures {required_signatures} on page {playwright_page_manager.page.url}. Signatures found are: \n-{all_signatures_string}")
      break

  if required_signatures_regex is not None:
    assert any(re.match(required_signatures_regex, signature) for signature in all_signatures)
  return interactable_signatures, text_input_field_signatures


async def click_signatures_in_sequence(
  signature_sequence: SignatureSequence,
  playwright_page_manager: PlaywrightPageManager,
  logger: Optional[Logger] = None
) -> Maybe[BrowserUrlVisit]:
  """
  initialize the excluded html list to be empty
  for each signature in signature list
    find the locators with that signature that are not in the excluded html list
    choose one locator arbitrarily
    expand the excluded html list to include all current html
    click the locator signature
  """

  logger = logger if logger is not None else Logger()
  browser_url_visit, error = None, None
  excluded_session_signature_set = set()
  # We need to repeatedly reload the page until the signatures appear


  logger.log(f"\n\n[click_signatures_in_sequence] Clicking signatures in sequence {[s.signature for s in signature_sequence.signature_sequence]}\n\n")  
  for signature_handle in signature_sequence.signature_sequence:

    # identify which outer_htmls were present before the click so we can exclude them after the click.
    try:
      pre_action_session_signature_set = set(await get_session_signatures(locator_list=await playwright_page_manager.page.locator('*').all(), logger=logger))

      logger.log(f"[click_signatures_in_sequence] len(pre_action_session_signature_set): {len(pre_action_session_signature_set)}")
    except Exception as e:
      browser_url_visit = None
      error = (
        f"[click_signatures_in_sequence] ERROR using get_session_signature before clicking {signature_handle.signature} in sequence {[s.signature for s in signature_sequence.signature_sequence]}: \n--------\n{traceback.format_exc()}\n---------\n"
      )
      logger.log(error)
      break
    else:
      try:
        browser_url_visit = await take_action_on_signature_handle(
          signature_handle=signature_handle,
          playwright_page_manager=playwright_page_manager,
          excluded_session_signature_set=excluded_session_signature_set,
          logger=logger)
      except Exception as e:
        browser_url_visit = None
        error = (
          f"[click_signatures_in_sequence] ERROR clicking signature {signature_handle.signature} in sequence {[s.signature for s in signature_sequence.signature_sequence]}: \n--------\n{traceback.format_exc()}\n---------\n"
        )
        logger.log(error)
        break
      else:
        logger.log(
          f"[click_signatures_in_sequence] Successfully took action on signature {signature_handle.signature} in sequence {[s.signature for s in signature_sequence.signature_sequence]}"
        )
        excluded_session_signature_set.update(pre_action_session_signature_set)

  maybe_browser_url_visit = Maybe(content=browser_url_visit, error=error)
  return maybe_browser_url_visit








  
async def _get_discovered_links_set(playwright_page_manager: PlaywrightPageManager, optional_browser_url_visit: Optional[BrowserUrlVisit]) -> Set[str]:
  # Get any links on the page after the action is taken
  discovered_links_set = set()
  discovered_links_set.update(await get_href_links_from_page(page=playwright_page_manager.page))
  discovered_links_set.update(await get_image_links_from_page(page=playwright_page_manager.page))

  if optional_browser_url_visit is not None:
    # Add the pages that we ended on
    discovered_links_set.update(optional_browser_url_visit.ending_url)
    discovered_links_set.update(playwright_page_manager.page.url)
  return discovered_links_set



async def click_signatures_in_sequence_and_find_new_signatures(
  signature_sequence: SignatureSequence,
  playwright_page_manager: PlaywrightPageManager,
  logger: Logger,
  max_signature_sequence_length: Optional[int] = None
) -> SignatureSequenceActionResults:
  """
  for each signature in signature list
    find the locators with that signature
    choose one arbitrarily
    click that signature
  
  identify all new signatures that were found after the click
  add the new signatures to the known_signatures_set
  return
    - all new signatures that were found after the click
    - the final browser_url_visit with the signatures_to_click_list as a calling context
  """
  starting_url = playwright_page_manager.page.url

  # identify which outer_htmls were present before the click so we can exclude them after the click.
  initial_session_signature_set = set(await get_session_signatures(locator_list=await playwright_page_manager.page.locator('*').all(), logger=logger))

  try:
    optional_browser_url_visit = (await click_signatures_in_sequence(
      signature_sequence=signature_sequence,
      playwright_page_manager=playwright_page_manager,
      logger=logger
    )).content
  except Exception as e:
    # Even if we throw an exception we don't want to stop the process of discovering new links etc
    logger.log(
      f"ERROR in click_signatures_in_sequence_and_find_new_signatures with signature_sequence: {signature_sequence}: ========\n{traceback.format_exc()}\n============="
    )
    optional_browser_url_visit = None

  discovered_links_set = await _get_discovered_links_set(playwright_page_manager=playwright_page_manager, optional_browser_url_visit=optional_browser_url_visit)
  logger.log(f"discovered_links_set on {starting_url}: {discovered_links_set}")
  if playwright_page_manager.page.url != starting_url:
    # The page redirected, so we don't want to continue
    logger.log(
      f"[click_signatures_in_sequence_and_find_new_signatures] After clicking signatures {signature_sequence.signature_sequence} we redirected from {starting_url} to {playwright_page_manager.page.url}"
    )
    discovered_signature_sequence_list = []
  elif max_signature_sequence_length is not None and len(signature_sequence) >= max_signature_sequence_length:
    # We aren't going to explore signature sequences longer than max_signature_sequence_length
    logger.log(
      f"[click_signatures_in_sequence_and_find_new_signatures] After clicking signatures {signature_sequence.signature_sequence} we have reached max_signature_sequence_length: {max_signature_sequence_length}"
    )
    discovered_signature_sequence_list = []
  else:
  
    # These are the global signatures of elements whose session signatures were not present on the page before the action was taken. These might match signatures of elements that are on the page before the action sequence, but in the next iteration of click_signatures_in_sequence we are going to select these only from the set of objects whose session_signatures are new
    new_interactable_signatures, new_text_input_field_signatures, excluded_signatures = await get_signatures_from_page(
      playwright_page_manager=playwright_page_manager,
      excluded_session_signature_set=initial_session_signature_set,
      logger=logger,
      fill_textboxes=True
    )

    click_signature_handle_list = [SignatureHandle(kind=SignatureHandleKind.CLICK, signature=signature) for signature in new_interactable_signatures ]
    submit_signature_handle_list = [SignatureHandle(kind=SignatureHandleKind.SUBMIT, signature=signature) for signature in new_text_input_field_signatures]

    # We return a new sequence for each discovered signature
    discovered_signature_sequence_list = (
      [
        SignatureSequence(
          signature_sequence=(signature_sequence.signature_sequence + [signature_handle]),
          required_signatures=signature_sequence.required_signatures
        )
      for signature_handle in (click_signature_handle_list + submit_signature_handle_list)
      ]
    )


    # Log the results
    logger.log(
      f"[click_signatures_in_sequence_and_find_new_signatures] After clicking signatures {signature_sequence.signature_sequence} found we have -------\n(browser_url_visit is None): {optional_browser_url_visit is None}\ncalling_context: {None if optional_browser_url_visit is None else optional_browser_url_visit.get_calling_context()}\ndiscovered_signature_sequence_list: {discovered_signature_sequence_list}\nnew_interactable_signatures: {new_interactable_signatures}\nnew_text_input_field_signatures: {new_text_input_field_signatures}\ndiscovered_links_set: {discovered_links_set}\nexcluded_signatures: {excluded_signatures} \n------------"
    )


  return SignatureSequenceActionResults(
    discovered_signature_sequence_list=discovered_signature_sequence_list,
    browser_url_visit=optional_browser_url_visit,
    discovered_links_set=discovered_links_set
  )


async def clone_playwright_and_click_signatures_in_sequence_and_find_new_signatures(
  url: str,
  signature_sequence: SignatureSequence,
  playwright_page_manager: PlaywrightPageManager,
  logger: Optional[Logger] = None,
  **reload_kwargs
) -> Optional[SignatureSequenceActionResults]:
  logger = Logger() if logger is None else logger
  
  logger.log(f"[clone_playwright_and_click_signatures_in_sequence_and_find_new_signatures] called with signature_sequence: {signature_sequence}")
  try:
    async with PlaywrightPageManagerCloneContext(playwright_page_manager) as cloned_playwright_page_manager:
      await cloned_playwright_page_manager.open_url(url)
      await cloned_playwright_page_manager.reload_and_click()
      await reload_url_until_signatures_appear_and_get_signatures(
        playwright_page_manager=cloned_playwright_page_manager, required_signatures=set(signature_sequence.required_signatures), logger=logger, **reload_kwargs)

      optional_signature_sequence_action_results = await click_signatures_in_sequence_and_find_new_signatures(
        signature_sequence=signature_sequence,
        playwright_page_manager=cloned_playwright_page_manager,
        logger=logger
      )
  except Exception as e:
    logger.log(f"[clone_playwright_and_click_signatures_in_sequence_and_find_new_signatures] ERROR in clone_playwright_and_click_signatures_in_sequence_and_find_new_signatures with signature_sequence: {signature_sequence}: ========\n{traceback.format_exc()}\n=============")
    optional_signature_sequence_action_results = None
  else:
    logger.log(f"[clone_playwright_and_click_signatures_in_sequence_and_find_new_signatures] SUCCESS in clone_playwright_and_click_signatures_in_sequence_and_find_new_signatures. discovered_links_set: {optional_signature_sequence_action_results.discovered_links_set}")
  return optional_signature_sequence_action_results


