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
from typing import Any, Callable, Dict, Generic, Iterable, List, Optional, OrderedDict, Tuple, TypeVar, Union
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

from url_analyzer.classification.utilities.utilities import filter_url, get_fqdn_from_url, modify_url, pydantic_create, safe_apply, safe_to_str


BASE_EXCLUDED_HEADERS_TEMPLATE_LIST = [
  "(.*):(.*)", "content-length", "Host", "host"
]

REQUEST_FILE_TEMPLATE = """{method} {url_path_and_query} {http_protocol}
Host: {url_host}
{formatted_headers}

{post_data}"""


async def _get_mystery_attribute_from_playwright_response(
  playwright_response: playwright.async_api._generated.Response,
  attribute_name_list: List[str],
  timeout: int = 5,
  verbose: bool = False,
) -> Optional[Any]:
  """
  This method is required because some attributes will throw errors when we try to access them due to being defined as properties. TBH this is just coping with bad design in the playwright library.
  
  Args:
    request_or_response: A playwright request or response object
    attribute_name_list: A list of attribute keys, such that we will recursively call getattr on the request or response object until we get to the final attribute
  Returns:
    A Maybe object containing the value of the attribute, or an error if it could not be found
  """

  # This iteration intended to capture the case where we nee to repeatedly recurse into the object to get the attribute
  base = playwright_response
  for attribute_name in attribute_name_list:
    try:
      base = getattr(base, attribute_name)
    except Exception as e:
      print(f"===========[_get_mystery_attribute_from_playwright_response called with {attribute_name_list}]===============\n\n\nERROR: error fetching attribute {attribute_name} from {base}: {e}\n\n\n==========================")
    if base is None:
      break
  extractor = base

  output, error = None, None
  if extractor is None:
    error = f"ERROR: Could not find attribute {attribute_name}"
  else:
    try:      
      if asyncio.iscoroutinefunction(extractor):
        # Async function
        potential_output = await asyncio.wait_for(extractor(), timeout=timeout)
      elif callable(extractor):
        # Callable, but not async
        potential_output = extractor()
      else:
        # Just a value to wrap in a Maybe
        potential_output = extractor
    except asyncio.TimeoutError as e:
      error = f"ERROR: TimeoutError extracting  {attribute_name}: {e}"
    except Exception as e:
      error = f"ERROR extracting {attribute_name}: {e}"
    else:
      # We need this to be pickleable in order to save and reload VisitedUrl objects
      try:
        is_pickleable = dill.pickles(potential_output)
      except Exception as e:
        print(f"ERROR: Could not pickle attribute {attribute_name} with value {str(potential_output)}: {e}")
        is_pickleable = False
      if not is_pickleable:
        error = f"ERROR: Could not pickle attribute {attribute_name} with value {str(potential_output)}"
      else:
        output = potential_output

  if verbose and error is not None:
    print(error)
  return output


@dataclass
class PostDataEditor:
  encoding: str
  post_data_dict: Optional[Dict[str, Any]]
  post_data_blob: Optional[str]

  @classmethod
  def from_post_data(cls, post_data: str) -> "PostDataEditor":
    post_data_blob = None
    post_data_dict = None
    encoding = None
    try:
      # Attempt to load as JSON
      post_data_dict = json.loads(post_data)
      encoding = 'json'
    except json.JSONDecodeError:
      pass

    if encoding is None:
      try:
        # Attempt to parse as URL-encoded data
        _post_data_dict = urllib.parse.parse_qs(post_data)
      except Exception:
        pass
      else:
        post_data_dict = _post_data_dict
        encoding = 'url'
    
    if encoding is None:
      # Use chardet to guess the encoding
      post_data_blob = post_data
      encoding = 'blob'

    # Default to utf-8 if all else fails
    return cls(
      encoding=encoding,
      post_data_dict=post_data_dict,
      post_data_blob=post_data_blob
    )

  def to_post_data(self) -> str:
    if self.post_data_blob is not None:
      post_data = self.post_data_blob
    elif self.encoding == "json":
      post_data = json.dumps(self.post_data_dict)
    elif self.encoding == "url":
      post_data = urllib.parse.urlencode(self.post_data_dict)
    else:
      raise ValueError(f"Unknown encoding {self.encoding}")
    return post_data


class ResponseRecord(BaseModel):
  response_url: Optional[str] = None
  response_text: Optional[str] = None
  # response_body: Optional[str] = None
  response_text_length: Optional[int] = None
  response_status: Optional[int] = None
  response_status_text: Optional[str] = None
  response_headers: Optional[Dict[str, str]] = None
  response_redirected_to: Optional[str] = None
  response_redirected_from: Optional[str] = None
  request_url: Optional[str] = None
  request_method: Optional[str] = None
  request_post_data: Optional[str] = None
  request_headers: Optional[Dict[str, str]] = None

  def display(self, verbose=True) -> str:
    return f"""
    -----------------REQUEST----------------------
    request_url: {self.request_url} [{self.request_method}]
    request_headers: {self.request_headers}
    request_post_data: {self.request_post_data}
    request_method: {self.request_method}
    -----------------RESPONSE----------------------
    response_url: {self.response_url}
    response_status: {self.response_status}
    response_headers: {self.response_headers}
     """ if not verbose else f"""
    -----------------REQUEST----------------------
    request_url: {self.request_url} [{self.request_method}]
    request_headers: {self.request_headers}
    request_post_data: {self.request_post_data}
    -----------------RESPONSE----------------------
    response_url: {self.response_url}
    response_status: {self.response_status}
    response_headers: {self.response_headers}
    response_text: {self.response_text}
     """
          

  @classmethod
  def from_request_txt_file_string(
    cls,
    request_txt_file_string: str,
    default_protocol: str = "https"
  ) -> "ResponseRecord":
    request_url = None
    request_method = None
    request_post_data = None
    request_headers = {}

    lines = request_txt_file_string.splitlines()
  
    # Extract headers and POST data
    headers_section = True
    for line in lines[1:]:
      if headers_section:
        if line.strip() == '':  # Empty line denotes end of headers
          headers_section = False
          continue
        header_parts = line.split(':', 1)
        if len(header_parts) == 2:
          header_name = header_parts[0].strip()
          header_value = header_parts[1].strip()
          request_headers[header_name] = header_value
      else:
          # Lines after headers section are considered part of POST data
          if request_post_data is None:
            request_post_data = line.strip()
          else:
            request_post_data += line.strip()


    # Extract the request method and URL from the first line
    first_line_tokens = lines[0].split()
    
    if len(first_line_tokens) >= 2:
      request_method = first_line_tokens[0]
      if request_method not in ["GET", "POST", "HEAD", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH"]:
        raise ValueError(f"Unknown request method {request_method}")
      request_url_path = first_line_tokens[1]
    else:
      raise ValueError(f"Could not parse request method and URL from {lines[0]}")
    # Construct the url from the host header and the path
      
    host_header_list = ["Host", "host"]
    for host_header in host_header_list:
      if request_url_path is not None and host_header in request_headers:
        host = deepcopy(request_headers[host_header])
        if not host.startswith("http"):
          # We use a default protocol of https
          host = f"{default_protocol}://" + host
        request_url = urllib.parse.urljoin(host, request_url_path)

    return cls(
      request_url=request_url,
      request_method=request_method,
      request_post_data=request_post_data,
      request_headers=request_headers
    )

  @classmethod
  def from_path_to_request_txt_file(
    cls,
    path_to_request_txt_file: str
  ) -> "ResponseRecord":

    with open(path_to_request_txt_file, 'r') as file:
      request_txt_file_string = file.read()
    
    return cls.from_request_txt_file_string(request_txt_file_string=request_txt_file_string)

  @classmethod
  async def from_playwright_response(
    cls,
    playwright_response: playwright.async_api._generated.Response,
    verbose: bool = False,
  ) -> "ResponseRecord":

    if playwright_response.url.endswith(".js") or playwright_response.url.endswith(".css"):
      # For assets we don't track the full response in order to save space. These can always be downloaded later
      included_attribute_names = [ 
        ["url"],
        ["status"],
        ["request", "url"],
        ["request", "method"],
      ]
    else:
      included_attribute_names = [ 
        ["url"],
        # ["body"],
        ["text"],
        ["status"],
        ["status_text"],
        ['all_headers'],
        ["request", "url"],
        ["request", "method"],
        ["request", "post_data"],
        ["request", "all_headers"],
        ["request", "redirected_to"],
        ["request", "redirected_from"],
      ]

    async_tasks = {
      '.'.join(attribute_name_list): _get_mystery_attribute_from_playwright_response(
        playwright_response=playwright_response,
        attribute_name_list=attribute_name_list,
        verbose=verbose
      )
      for attribute_name_list in included_attribute_names
    }
      # "json", "server_addr", "security_details", "status", "status_text", "from_service_worker", "ok"
    results = await asyncio.gather(*async_tasks.values())
    response_dict = {key: result for key, result in zip(async_tasks.keys(), results)}

    # We cut the text down in order to save space 
    if response_dict.get("text") is not None:
      response_dict["text_length"] = len(response_dict["text"])
    else:
      response_dict["text_length"] = None
      
    
    # Construct the ResponseRecord object
    response_record = pydantic_create(
      cls=cls,
      response_url=response_dict.get("url"),
      response_text=response_dict.get("text"),
      # response_body=safe_to_str(response_dict.get("body")),
      response_text_length=response_dict.get("text_length"),
      response_status=safe_apply(obj=response_dict.get("status"), fn=int),
      response_status_text=response_dict.get("status_text"),
      response_headers=response_dict.get("all_headers"),
      request_url=response_dict.get("request.url"),
      request_method=response_dict.get("request.method"),
      request_post_data=safe_apply(response_dict.get("request.post_data"), str),
      request_headers=response_dict.get("request.all_headers"),
      response_redirected_to=safe_apply(response_dict.get("request.redirected_to"), str),
      response_redirected_from=safe_apply(response_dict.get("request.redirected_from"), str),
    )
    return response_record


  def get_url_parameters_dict(self) -> Dict[str, str]:
    parsed_url = urllib.parse.urlparse(self.request_url)
    return {} if parsed_url is None or len(parsed_url) == 0 else urllib.parse.parse_qs(parsed_url.query)

  def get_post_data_dict(self) -> Optional[Dict[str, Any]]:
    return None if self.request_post_data is None else PostDataEditor.from_post_data(post_data=self.request_post_data).post_data_dict

  def get_post_data_blob(self) -> Optional[str]:
    return None if self.request_post_data is None else PostDataEditor.from_post_data(post_data=self.request_post_data).post_data_blob



  def clone_with_overrides(
    self,
    base_url: Optional[str] = None,
    url_parameters: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    post_data_dict: Optional[Dict[str, Any]] = None,
    post_data_blob: Optional[str] = None
  ) -> "ResponseRecord":
    """ 
    Clone the request fields in a ResponseRecord


    TODO: Expand this to handle cases where the post data dict is a nested json object
    """
    response_record = ResponseRecord(
      request_url=deepcopy(self.request_url),
      request_method=deepcopy(self.request_method),
      request_headers=deepcopy(self.request_headers),
      request_post_data=deepcopy(self.request_post_data),
    )
    response_record.request_url = modify_url(
      url=response_record.request_url,
      base_url=base_url,
      url_parameters=url_parameters
    )
    if headers is not None:
      response_record.request_headers.update(headers)

    if post_data_dict is not None or post_data_blob is not None:
      if self.request_post_data is None:
        raise ValueError(f"Cannot update post_data_dict {post_data_dict} and post_data_blob {post_data_blob} on post_data {self.request_post_data}")
     
      # Parse the existing post data
      post_data_editor = self.get_post_data_editor()
      if post_data_editor.post_data_dict is not None and post_data_dict is not None:
        post_data_editor.post_data_dict.update(post_data_dict)
      elif post_data_editor.post_data_blob is not None and post_data_blob is not None:
        post_data_editor.post_data_blob = post_data_blob
      else:
        raise ValueError(f"Cannot update post_data_dict {post_data_dict} and post_data_blob {post_data_blob} on post_data {post_data_editor}")
      
      # Write the existing post data
      response_record.request_post_data = post_data_editor.to_post_data()
    return response_record
  

  def get_formatted_request_headers_list(
    self,
    excluded_headers_template_list: Optional[List[str]] = None
  ) -> List[str]:
    excluded_headers_template_list = BASE_EXCLUDED_HEADERS_TEMPLATE_LIST if excluded_headers_template_list is None else excluded_headers_template_list

    return [
      f"{k}: {v}"
      for k, v in self.request_headers.items() if ":" not in k
      and not any(re.match(template, k)
                  for template in excluded_headers_template_list)
    ]

  def print_request_from_response(
    self,
    excluded_headers_template_list: Optional[List[str]] = None,
    http_protocol: str = "HTTP/1.1",
  ) -> str:
    """
    Given a loaded response dict, print the request in the HTTP format (https://github.com/JetBrains/http-request-in-editor-spec/blob/master/spec.md)
    """
    formatted_headers_string = '\n'.join(self.get_formatted_request_headers_list(excluded_headers_template_list=excluded_headers_template_list))
  
    post_data = "" if self.request_post_data is None else self.request_post_data

    parsed_url = urllib.parse.urlparse(self.request_url)
    url_host = f'{parsed_url.scheme}://{parsed_url.netloc}/'
    url_path_and_query = parsed_url.path if parsed_url.query is None or len(parsed_url.query) == 0 else parsed_url.path + "?" + parsed_url.query
    return REQUEST_FILE_TEMPLATE.format(
      method=self.request_method,
      url_host=url_host,
      http_protocol=http_protocol,
      url_path_and_query=url_path_and_query,
      formatted_headers=formatted_headers_string,
      post_data=post_data
    )

  def write_request_from_response(
    self,
    fname: str,
    verbose: bool = True
  ) -> str:
    contents = self.print_request_from_response()
    if verbose:
      print(contents)
    with open(fname, "w") as f:
      f.write(contents)
    
    # Throw an error if the file was not written correctly
    if not os.path.exists(fname):
      raise ValueError(f"Could not write request to {fname}")


async def get_response_log(response_list: List[playwright.async_api._generated.Response], **kwargs) -> List[ResponseRecord]:
  return await asyncio.gather(*[ResponseRecord.from_playwright_response(response, **kwargs) for response in response_list])

def filter_response_record_list(response_record_list: List[ResponseRecord], **filter_kwargs) -> List[ResponseRecord]:
  """
  Given a list of ResponseRecords, filter them by the given kwargs
  """
  return [
    response_record for response_record in response_record_list
    if filter_url(response_record.request_url, **filter_kwargs)
  ]



