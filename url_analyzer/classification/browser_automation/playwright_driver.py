"""
Inspired by https://github.com/richardyc/Chrome-GPT/blob/96e2f6cee8cd5914da4a7f46da809ff9f2285343/chromegpt/tools/selenium.py#L145






TODO: Refactor all interactable element collection into a sane data structure and then pass this data structure both for effective rendering by the describe_website call and for steering the tool


"""
import asyncio
from dataclasses import dataclass
import os
import random
import sys

from typing import Any, Dict, List, Optional, Set, Tuple
import uuid
from bs4 import BeautifulSoup
import urllib.parse
import json
import time
import re
from typing import List, Optional, Union
from pydantic import BaseModel, ValidationError

from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

from unidecode import unidecode
from playwright.async_api._generated import Locator


from url_analyzer.classification.browser_automation.playwright_page_manager import PlaywrightPageManager
from url_analyzer.classification.browser_automation.utilities import get_interactable_locators_from_page, get_visible_text_from_html, prettify_text
from url_analyzer.classification.browser_automation.datamodel import BrowserUrlVisit
from url_analyzer.classification.utilities.utilities import Maybe, pydantic_create, pydantic_validate

# These are the types of form fields that we do not attempt to fill
SUBMIT_TYPE_LIST = ["submit"]
STATIC_TYPE_LIST = ["submit"]




async def get_button_signature_text(button_locator: Locator, max_char_length: int = 100) -> str:
  # TODO: Also include the aria-label?
  components = await asyncio.gather(*[
      button_locator.get_attribute("label"),
      button_locator.get_attribute("aria-label"),
      button_locator.get_attribute("alt"),
      button_locator.inner_text()
    ])

  return "|".join([c for c in components if c is not None])[:max_char_length]


class ActionResponse(BaseModel):
  is_success: Optional[bool] = None
  start_url: Optional[str] = None
  end_url: Optional[str] = None
  browser_url_visit: Optional[BrowserUrlVisit] = None
  warning: Optional[str] = None
  error: Optional[str] = None

  def get_warning_or_error(self) -> str:
    warning_error_list = [x for x in [self.warning, self.error] if x is not None]
    return "" if len(warning_error_list) == 0 else "\n".join([x for x in [self.warning, self.error] if x is not None])
    

  def as_string(self) -> str:
    return f"""
    is_success: {self.is_success}
    start_url: {self.start_url}
    end_url: {self.end_url}
    warning: {self.warning}
    error: {self.error}
    """
    

@dataclass 
class FormField:
  # TODO: Figure out forms in frames
  text: Optional[str]
  locator: "Locator"
  tag_name: Optional[str] = None
  input_type: Optional[str] = None

  @classmethod
  async def from_locator(cls, locator: "Locator") -> "Optional[FormField]":

    try:
      tag_name = (await locator.evaluate('e => e.tagName')).lower()
    except Exception as e:
      tag_name = None
    
    try:
      input_type = await locator.evaluate('e => e.type')
    except Exception as e:
      input_type = None

    label_txt = (
      await locator.get_attribute("name")
      or await locator.get_attribute("aria-label")
      or await locator.inner_text()
    )
    return cls(
      text=(None if label_txt is None else prettify_text(label_txt)),
      locator=locator,
      tag_name=tag_name,
      input_type=input_type
    )
  
  def is_checkbox_or_radio_type(self) -> bool:
    return self.tag_name in ('checkbox', 'radio') or self.input_type in ('checkbox', 'radio')

  def is_select_type(self) -> bool:
    return self.tag_name in ('select') or self.input_type in ('select')

  async def get_options(self) -> Optional[List[str]]:
    # TODO: Add dropdowns - see https://playwright.dev/docs/input

    if self.is_checkbox_or_radio_type():
      options = ['true', 'false']
    elif self.is_select_type():
      options_handle_list = await (self.locator.locator('option').all())
      options = [await option.text_content() for option in options_handle_list]
    else:
      options = None
    return options

  async def fill(self, text: str) -> Optional[str]:
    # TODO: Add dropdowns - see https://playwright.dev/docs/input
    error = None

    if self.is_checkbox_or_radio_type():
      if str(text).lower() == 'true':
        await self.locator.check()
      elif str(text).lower() == 'false':
        await self.locator.uncheck()
      else:
        error = f"ERROR: Cannot fill checkbox/radio with text {text}. Must be either 'true' or 'false'."
    elif self.is_select_type():
      options = await self.get_options()
      if text in options:
        try:
          await self.locator.select_option(text)
        except Exception as e:
          error = str(e)
      else:
        error = f"ERROR: Cannot fill select with text {text}. Must be one of {options}."
    else:
      try:
        await self.locator.fill(text)
      except Exception as e:
        error = str(e)
    return error


@dataclass
class FormFields:
  user_supplied_form_field_list: List[FormField]
  static_form_field_list: List[FormField]
  submit_button: "Optional[Locator]" = None
  form_locator: "Optional[Locator]" = None

@dataclass 
class Button:
  frame_name: str
  text: str
  locator: "Locator"



DEFAULT_ERROR_MESSAGE_REGEX = "(.*)(ERR_SOCKET_NOT_CONNECTED|ERR_CONNECTION_RESET)(.*)"
@dataclass
class PlaywrightDriver:
  """
  This is the class that manages control of a PlaywrightPageManager (button clicks, form inputs, page refreshes, etc). This class is used both by LLM-based and non-LLM based control engines. The scope of this class includes
    - Identifying objects on the page that this class can modify
    - Modifying those objects

  The mechanisms by which descriptions of these objects are derived and passed to LLMs do not belong in this class.
  """

  playwright_page_manager: PlaywrightPageManager

  @classmethod
  async def construct(cls, **kwargs) -> "PlaywrightDriver":
    """Initialize Playwright and start interactive session."""
    playwright_page_manager = await PlaywrightPageManager.construct(**kwargs)
    return cls(playwright_page_manager=playwright_page_manager)

  async def close(self) -> None:
    await self.playwright_page_manager.close()

  
  async def open_url_and_reload_until_no_load_error(
    self,
    url: str,
    num_retries: int = 5,
    error_message_regex: str = DEFAULT_ERROR_MESSAGE_REGEX,
  ) -> ActionResponse:
    action_response = await self.open_url(url=url)

    for _ in range(num_retries):
      if any(re.match(error_message_regex, msg) for msg in action_response.browser_url_visit.console_error_message_log):
        print(f"WARNING: Error message {error_message_regex} found in console log {action_response.browser_url_visit.console_error_message_log}. Reloading page...")
        action_response = ActionResponse(
          is_success=True,
          start_url=action_response.start_url,
          end_url=self.playwright_page_manager.page.url,
          browser_url_visit=await self.playwright_page_manager.reload_and_click(),
        )

    return action_response
  

  async def open_url(self, url: str) -> str:
    start_url = self.playwright_page_manager.page.url
    try:
      browser_url_visit = await self.playwright_page_manager.open_url(url=url)
    except Exception as e:
      browser_url_visit = None
      is_success = False
      error = str(e)
    else:
      is_success = True
      error = None
    return ActionResponse(
      is_success=is_success,
      start_url=start_url,
      end_url=self.playwright_page_manager.page.url,
      browser_url_visit=browser_url_visit,
      error=error
    )


  async def get_form_fields_with_reloads(self, num_reloads: int = 20, delay_seconds: int = 2, **kwargs) -> Maybe[FormFields]:
    maybe_form_fields = Maybe()
    for _ in range(num_reloads):
      maybe_form_fields = await self.get_form_fields()
      if maybe_form_fields.content is not None and len(maybe_form_fields.content.user_supplied_form_field_list) > 0:
        print("Form fields found!")
        break
      else:
        print(f"Form not found. \n--------Content-----\n {await self.playwright_page_manager.page.content()}\n----------\n")
        print("Sleeping and reloading page...")
        await self.playwright_page_manager.reload_and_click()
        await asyncio.sleep(delay_seconds)
    return maybe_form_fields

  async def get_form_fields(self, expected_user_supplied_field_set: Optional[Set[str]] = None, num_reloads: int = 5) -> Maybe[FormFields]:
    """
    Try to extract form fields in a best effort way by starting by looking for a form and then falling back to extracting text fields manually
    """
    maybe_result = await self.get_form_fields_from_single_visible_form(expected_user_supplied_field_set=expected_user_supplied_field_set)
    if maybe_result.content is None:
      # Extract text fields manyaly
      maybe_result = await self.get_form_fields_from_page_directly(expected_user_supplied_field_set=expected_user_supplied_field_set)
    return maybe_result

  async def get_form_fields_from_single_visible_form(self, expected_user_supplied_field_set: Optional[Set[str]] = None) -> Maybe[FormFields]:
    """
    Extracts user editable and static fields from a page with a single visible form. If multiple visible forms are found, the first one is used.
    """
    form_list = (await self.playwright_page_manager.page.locator('form').all())
    visible_form_list = [f for f in form_list if await f.is_visible()]
    if len(visible_form_list) == 0:
      maybe_result = Maybe(error=f"No visible forms found on page {self.playwright_page_manager.page.url}")
    else:
      if len(visible_form_list) > 1:
        print(f"Multiple visible forms found on page {self.playwright_page_manager.page.url}. Forms found: {visible_form_list}. Using first one.")
      maybe_result = await self._get_form_fields_from_locator(locator=visible_form_list[0], expected_user_supplied_field_set=expected_user_supplied_field_set)
    return maybe_result


  async def get_form_fields_from_page_directly(self, expected_user_supplied_field_set: Optional[Set[str]] = None) -> Maybe[FormFields]:
    """
    Extracts input fields from a page without attempting to group the fields by a form first
    """
    maybe_result = await self._get_form_fields_from_locator(locator=self.playwright_page_manager.page, expected_user_supplied_field_set=expected_user_supplied_field_set)
    return maybe_result

  async def get_non_form_input_form_fields_from_page_directly(self, expected_user_supplied_field_set: Optional[Set[str]] = None) -> Maybe[FormFields]:
    """
    Extracts input fields from a page without attempting to group the fields by a form first
    """
    maybe_all_fields = await self._get_form_fields_from_locator(locator=self.playwright_page_manager.page, expected_user_supplied_field_set=expected_user_supplied_field_set)
    maybe_form_fields = await self.get_form_fields_from_single_visible_form()

    if maybe_all_fields.content is None or maybe_form_fields.content is None:
      maybe_non_form_fields = maybe_all_fields
    else:
      non_form_fields = FormFields(
        user_supplied_form_field_list=[f for f in maybe_all_fields.content.user_supplied_form_field_list if f not in maybe_form_fields.content.user_supplied_form_field_list],
        static_form_field_list=[f for f in maybe_all_fields.content.static_form_field_list if f not in maybe_form_fields.content.static_form_field_list],
        submit_button=None,
        form_locator=None
      )
      maybe_non_form_fields = Maybe(content=non_form_fields)
    return maybe_non_form_fields


  async def _get_form_fields_from_locator(self, locator: "Locator", expected_user_supplied_field_set: Optional[Set[str]] = None) -> Maybe[FormFields]:
    """
    Extracts user editable and static fields from a page with a single visible form
    """


    # TODO: Potentially replace this with the locator for text fields, maybe as a fallback?
    form_field_locator_list = (
      await locator.locator('input').all()
      + await locator.locator('textarea').all()
      + await locator.locator('select').all() 
    )

    user_supplied_form_field_list = []
    static_form_field_list = []
    submit_button = None
    # Iterate through the discovered forms
    for form_field_locator in form_field_locator_list:
      form_field = await FormField.from_locator(locator=form_field_locator)
      name = await form_field.locator.get_attribute('name')
      attribute_type = await form_field.locator.get_attribute('type')
  
      # NOTE: This kind of user-supplied and static field heuristic-based matching is exactly what the LLM should help with
      if attribute_type in SUBMIT_TYPE_LIST:
        # A submit button is present so we add this
        submit_button = form_field.locator
      elif await form_field.locator.is_visible() and await form_field.locator.is_editable() and attribute_type not in STATIC_TYPE_LIST:

        # If expected_user_supplied_field_set is provided then we only add the field to the user_supplied_field_list if it is in the set
        if expected_user_supplied_field_set is None or name in expected_user_supplied_field_set:
          user_supplied_form_field_list.append(form_field)
        else:
          print(f"Found unexpected user supplied field {name} on page {self.playwright_page_manager.page.url}. This field is not in the expected user supplied field set {expected_user_supplied_field_set}. Adding to static field list!")
          static_form_field_list.append(form_field)
      else:
        static_form_field_list.append(form_field)
    maybe_result = Maybe(content=FormFields(
      user_supplied_form_field_list=user_supplied_form_field_list,
      static_form_field_list=static_form_field_list,
      submit_button=submit_button,
      form_locator=locator
    ))
    return maybe_result


  # async def get_all_form_field_list(self) -> List[FormField]:
  #   """
  #   Get the list of all forms on the page, including invisible ones
  #   """
  #   form_field_list = []
    
  #   for locator in (await self.playwright_page_manager.page.locator("textarea, input").all()):
  #     form_field = await FormField.from_locator(locator=locator)
  #     if (
  #       form_field.text is not None
  #     ):
  #       form_field_list.append(form_field)
  #   return form_field_list

  # async def get_visible_form_field_list(self) -> List[FormField]:
  #   """
  #   Get the list of all forms on the page, excluding invisible ones

  #   TODO: Modify this to work by iterating through the forms that are visible on the page and selecting a particular form to display

  #   """
  #   all_form_field_list = await self.get_all_form_field_list()
  #   form_field_list = [
  #     form_field
  #     for form_field in all_form_field_list
  #     if (
  #       await form_field.locator.is_enabled()
  #       # TODO: Potentially change this in the future so we can submit to invisible fields
  #       and await form_field.locator.is_visible()
  #     )
  #   ]
    
  #   return form_field_list

  


  """
  # Some sample code that might make it possible to submit forms in a more generalizable way beyond just pressing
  async def fill_and_submit(page, form_data):
    # Fill each field in the form
    for name, value in form_data.items():
        field = await page.locator(f'input[name="{name}"]')
        if not field:
            field = await page.locator(f'textarea[name="{name}"]')
        if not field:
            field = await page.locator(f'select[name="{name}"]')
        if field:
            field_type = await field.get_attribute('type')
            if field_type == 'checkbox' or field_type == 'radio':
                if value:
                    await field.check()
                else:
                    await field.uncheck()
            else:
                await field.fill(value)

    # Try to submit the form by clicking the submit button
    submit_button = await page.locator('input[type="submit"]')
    if submit_button:
        await submit_button.click()

    # If the above didn't work, try submitting the form using JavaScript
    else:
        await page.evaluate("document.querySelector('form').submit()")

    # If the form has a file upload field, handle it
    file_input = await page.locator('input[type="file"]')
    if file_input and 'file' in form_data:
        await file_input.set_input_files(form_data['file'])

    # Add error handling
    try:
        # The code that could potentially throw an error goes here
        pass
    except Exception as e:
        print(f'An error occurred: {e}')
    """

  async def submit_form(
    self,
    form_field_list: List[FormField],
    submit_button: "Optional[Locator]" = None
  ) -> BrowserUrlVisit:
    
    if len(form_field_list) == 0:
      raise ValueError(f"Cannot submit form with no form fields!")
    else:

      browser_url_visit = None
      if submit_button is not None:
        try:
          # Attempt to submit the form using the submit button, and fall back on focus_and_press if this doesn't work
          print(f"Attempting to submit form using submit button {submit_button}...")
          browser_url_visit = await self.playwright_page_manager.click_locator(locator=submit_button)
        except Exception as e:
          print(f"ERROR: Could not submit form using submit button: {str(e)}")
        else:
          print(f"Successfully submitted form using submit button {submit_button}!")

      if browser_url_visit is None:
        print(f"Attempting to submit form using focus_and_press on the first form field {form_field_list[0]}...")
        browser_url_visit = await self.playwright_page_manager.focus_and_press(locator=form_field_list[0].locator)
    return browser_url_visit


  async def fill_out_form(
    self,
    form_fields: List[FormField],
    **kwargs
  ) -> ActionResponse:
    return await self.fill_out_form_with_form_field_list(
      form_field_list=form_fields.user_supplied_form_field_list,
      submit_button=form_fields.submit_button,
       **kwargs
    )
  
  async def fill_out_form_with_form_field_list(
    self,
    form_input: Dict[str, Any],
    form_field_list: List[FormField],
    hard_fail_on_form_fill_failure: bool = True,
    submit_button: "Optional[Locator]" = None
  ) -> ActionResponse:
    start_url = self.playwright_page_manager.page.url
    
    browser_url_visit = None

    # Fill out the fields
    form_fill_error_dict = {}
    warning = None
    error = None
    for form_field in form_field_list:
      # We will only try to fill out the intersection of the form fields and the form input
      if form_field.text in form_input:
        # TODO: Potentially make this resilient to failures like "input of type submit cannot be filled" rather than just erroring out here
        form_fill_error = await form_field.fill(form_input[form_field.text])
        if form_fill_error is not None:
          form_fill_error_dict[form_field.text] = form_fill_error

    if hard_fail_on_form_fill_failure and len(form_fill_error_dict) > 0:
      is_success = False
      error = f"[ERROR] Error filling out form with input {form_input}, message: {form_fill_error_dict}"      
    else:
      # Submit the form now that the fields are filled out
      try:
        # TODO: Handle forms in frames when this comes up
        browser_url_visit = await self.submit_form(form_field_list=form_field_list, submit_button=submit_button)
      except Exception as e:
        is_success = False
        error = f"[ERROR] Error filling out form with input {form_input}, message: {str(e)}"
      else:
        is_success = True
    end_url = self.playwright_page_manager.page.url

    # We are treating extra inputs as a warning rather than an error to add resilience
    unused_form_input_keys = set(form_input.keys()) - {form_field.text for form_field in form_field_list}
    if len(unused_form_input_keys) > 0:
      warning = ("" if warning is None else warning) + f"\nWARNING: The form input keys: {unused_form_input_keys} did not match any form fields on the page."

    # We are treating missing inputs as a warning rather than an error to add resilience
    extra_form_input_keys = {form_field.text for form_field in form_field_list} - set(form_input.keys())
    if len(extra_form_input_keys) > 0:
      warning = ("" if warning is None else warning) + f"\nWARNING: No input was provided for the form fields: {extra_form_input_keys}. The default value is being used"

    if not hard_fail_on_form_fill_failure and len(form_fill_error_dict) > 0:
      warning = ("" if warning is None else warning) + f"\nWARNING: Not all provided form fields were filled correctly. Errors: {form_fill_error_dict}"

    if browser_url_visit is not None:
      pydantic_validate(BrowserUrlVisit, browser_url_visit)
    return pydantic_create(
      cls=ActionResponse,
      is_success=is_success,
      start_url=start_url,
      end_url=end_url,
      browser_url_visit=browser_url_visit,
      warning=warning,
      error=error
    )  


  async def get_button_list(self, **locator_is_interactable_kwargs) -> List[Button]:
    button_list = []
    for frame in self.playwright_page_manager.page.frames:
      interactable_locators_list = await get_interactable_locators_from_page(
        page_or_frame=frame,
        filter_invisible=True,
        # We do want to include button pushes that trigger page changes
        filter_navigable=False,
        filter_disabled=True,
        **locator_is_interactable_kwargs
      )

      for locator in interactable_locators_list:
        try:
          button_text = await get_button_signature_text(button_locator=locator)
        except Exception as e:
          print(f"[get_button_list] ERROR on locator.inner_text() for locator {locator}. Skipping...")
        else:
          if (
            button_text
            # TODO: Maybe add uniqueness conditiuon
            #  and button_text not in interactable_texts
          ):
            button_list.append(
              Button(
                frame_name=frame.name,
                text=button_text,
                locator=locator
            ))
    return button_list


  async def click_button_by_text(self, button_text: str) -> ActionResponse:
    # TODO: Switch to a better definition of button text that includes aria-text etc





    button_list = await self.get_button_list()
    # If there are string surrounded by double quotes, extract them
    if button_text.count('"') > 1:
      try:
        button_text = re.findall(r'"([^"]*)"', button_text)[0]
      except IndexError:
        # No text surrounded by double quotes
        pass

    # Gather all buttons that exactly match the button_text
    selected_button_list = [
      button for button in button_list if button_text == button.text
    ]
    if len(selected_button_list) == 0:
      return pydantic_create(
        cls=ActionResponse,
        is_success=False,
        start_url=self.playwright_page_manager.page.url,
        end_url=self.playwright_page_manager.page.url,
        browser_url_visit=None,
        error=f"[ERROR] No interactable element found with text: {button_text}. Available buttons: {[b.text for b in button_list]}"
      )
    else:
      if len(selected_button_list) > 1:
        print(f"WARNING: Multiple ({len(selected_button_list)}) buttons found with text {button_text}. Clicking them one at a time until the page changes...")

      action_response = await self.click_buttons_until_change(selected_button_list=selected_button_list)
    return action_response

  async def click_button(self, button: Button) -> ActionResponse:
    return await self.click_buttons_until_change(selected_button_list=[button])

  async def click_buttons_until_change(self, selected_button_list: List[Button]) -> ActionResponse:
    """
    Iterate through the buttons in the selected_button_list, clicking each one until the page changes
    """
    start_url = self.playwright_page_manager.page.url

    # Iterate through the buttons clicking each one. Stop when the page changes.
    browser_url_visit = None
    button_click_error_response_list = []
    button_click_success = False
    button_click_changed_webpage = False
    for button in selected_button_list:
      try:          
        browser_url_visit = await self.playwright_page_manager.click_locator(locator=button.locator)
      except Exception as e:
        button_click_error_response_list.append(str(e))
      else:
        # At least one click was successful so we can mark this as a success and keep clicking if needed
        button_click_success = True
        
        if get_visible_text_from_html(browser_url_visit.starting_html) != get_visible_text_from_html(browser_url_visit.ending_html):
          # The page has changed in response to the button click, we can stop clicking buttons
          button_click_changed_webpage = True
          break

    warning = None
    error = None
    if not button_click_success:
      is_success = False
      error = f"[ERROR] No button click was successful! Error: {button_click_error_response_list}"
    elif not button_click_changed_webpage:
      is_success = True
      warning = f"[WARNING] Successfully clicked button, but the website did not change..."
    else:
      is_success = True

    end_url = self.playwright_page_manager.page.url
    if browser_url_visit is not None:
      pydantic_validate(BrowserUrlVisit, browser_url_visit)
    return pydantic_create(
      cls=ActionResponse,
      is_success=is_success,
      start_url=start_url,
      end_url=end_url,
      browser_url_visit=browser_url_visit,
      error=error,
      warning=warning
    )
  
