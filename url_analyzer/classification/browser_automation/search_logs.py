
import argparse
from collections import defaultdict
import sys
import os
import time
from dataclasses import dataclass
import sys
import os
from typing import Any, Dict, List, Optional, Set, Tuple, TypeVar
import uuid
from playwright.async_api import async_playwright
import asyncio
from urllib.parse import urlparse, parse_qsl
import re



from url_analyzer.classification.browser_automation.playwright_spider import VisitedUrl
from url_analyzer.classification.utilities.utilities import load_pydantic_model_from_file_path, load_pydantic_model_from_directory_path
from url_analyzer.classification.browser_automation.datamodel import NetworkLog
from url_analyzer.classification.browser_automation.response_record import ResponseRecord





@dataclass
class SearchRegexResults:
  url_matches: Set[str]
  request_header_matches: Set[str]
  response_header_matches: Set[str]
  post_data_matches: Set[str]
  response_text_matches: Set[str]
  filtered_responses: Dict[str, List[Dict[str, Any]]]

  def get_response_list(self):
    return [response for response_list in self.filtered_responses.values() for response in response_list]

def get_search_regex_results(all_responses: List[Dict[str, Any]], search_regex: str) -> SearchRegexResults:
  """
  Given a list of HTTP responses and a regex, search the request and response data for the regex.
  """
  url_matches = set()
  request_header_matches = set()
  response_header_matches = set()
  post_data_matches = set()
  response_text_matches = set()
  filtered_responses = defaultdict(list)

  for response_hash, response_list in all_responses.items():
    for response in response_list:
      append = False
      if match_url(search_regex=search_regex, response=response):
        url_matches.add(response_hash)
        append = True
      if match_request_header(search_regex=search_regex, response=response):
        request_header_matches.add(response_hash)
        append = True
      if match_post_data(search_regex=search_regex, response=response):
        post_data_matches.add(response_hash)
        append = True
      if match_response_header(search_regex=search_regex, response=response):
        response_header_matches.add(response_hash)
        append = True
      if match_response_text(search_regex=search_regex, response=response):
        response_text_matches.add(response_hash)
        append = True

      if append:
        filtered_responses[response_hash].append(response)
  return SearchRegexResults(
    url_matches=url_matches,
    request_header_matches=request_header_matches,
    response_header_matches=response_header_matches,
    post_data_matches=post_data_matches,
    response_text_matches=response_text_matches,
    filtered_responses=filtered_responses,
  )

def match_url(search_regex: str, response: ResponseRecord) -> bool:

  match = False
  if response.response_url is not None:
    url_string = str(response.response_url)
    if re.match(search_regex.lower(), url_string.lower()):
      match = True
  return match

def match_response_text(search_regex: str, response: ResponseRecord) -> bool:

  match = False
  if response.response_text is not None:
    if re.match(search_regex.lower(), response.response_text.lower()):
      match = True
  return match


def match_request_header(search_regex: str, response: ResponseRecord) -> bool:

  match = False
  if response.request_headers is not None:
    request_headers_string = str(response.request_headers)
    if re.match(search_regex.lower(), request_headers_string.lower()):
      match = True
  return match


def match_post_data(search_regex: str, response: ResponseRecord) -> bool:

  match = False
  if response.post_data is not None:
    post_data_string = str(response.post_data)
    if re.match(search_regex.lower(), post_data_string.lower()):
      match = True
  return match


def match_response_header(search_regex: str, response: ResponseRecord) -> bool:

  match = False
  if response.response_headers is not None:
    response_header_string = str(response.response_headers)
    if re.match(search_regex.lower(), response_header_string.lower()):
      match = True
  return match


def get_response_hash(response: ResponseRecord) -> str:
  return hash(
    str(response.request_url) + str(response.request_post_data)
  )




def get_all_responses_from_files(
  network_log_file: Optional[str] = None,
  visited_url_log_dir: Optional[str] = None,
  url_include_regex: Optional[str] = None,
  url_exclude_regex: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
  all_responses = defaultdict(list)

  if network_log_file is not None:
    network_log = load_pydantic_model_from_file_path(cls=NetworkLog, path=network_log_file)
    for r in network_log.response_log:
      all_responses[get_response_hash(r)].append(r)


  action_profile = defaultdict(int)
  if visited_url_log_dir is not None:
    visited_url_log = load_pydantic_model_from_directory_path(cls=VisitedUrl, path=visited_url_log_dir)
    for visited_url in visited_url_log:
      for browser_url_visit in visited_url.get_browser_url_visit_list():
        action_profile[list(browser_url_visit.action.keys())[0]] += 1
        for r in browser_url_visit.response_log:
          all_responses[get_response_hash(r)].append(r)
  print(f"Action Profile: {action_profile}")

  if url_include_regex is not None:
    all_responses = {response_hash: response_list for response_hash, response_list in all_responses.items() if re.match(url_include_regex, response_list[0]['url']['content'])}
  if url_exclude_regex is not None:
    all_responses = {response_hash: response_list for response_hash, response_list in all_responses.items() if not re.match(url_exclude_regex, response_list[0]['url']['content'])}
  return all_responses
