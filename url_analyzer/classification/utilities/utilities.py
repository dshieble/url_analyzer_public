import asyncio
import json
import logging
import os
import re
import subprocess
import time
import traceback
import uuid
import aiohttp
import chardet
import httpx
import numpy as np
from pydantic import BaseModel, ConfigDict, ValidationError
import urllib.parse
import requests
import tldextract
from typing import Any, Awaitable, Callable, Coroutine, Dict, Generic, List, Optional, OrderedDict, Set, Tuple, TypeVar
from dataclasses import dataclass
from diff_match_patch import diff_match_patch
import yaml
import string


class BaseModelWithWrite(BaseModel):
  def write_to_file(self, filepath: str) -> str:
    object_json = self.model_dump_json(indent=2)

    with open(filepath, 'w') as file:
      print(f"Writing {self.__class__} to {file.name}")
      file.write(object_json)
    return filepath

T = TypeVar('T')
@dataclass
class Maybe(Generic[T]):
  content: Optional[T] = None
  error: Optional[str] = None

  def display(self):
    if self.content is None:
      return self.error
    else:
      return self.content

  def apply(self, fn: Callable[[T], Any], **kwargs) -> 'Maybe[T]':
    return self if self.content is None else Maybe(content=fn(self.content, **kwargs))

  def monad_join(self, fn: Callable[[T], Any], **kwargs) -> 'Maybe[T]':
    return self if self.content is None else fn(self.content, **kwargs)

  def unwrap(self) -> T:
    if self.content is None:
      raise ValueError(f"Cannot unwrap Maybe with error: {self.error}")
    else:
      return self.content


T1 = TypeVar('T1')
T2 = TypeVar('T2')
def maybe_apply(maybe: Maybe[T], fn: Callable[[T1, Any], T2], **kwargs) -> Maybe[T2]:
  return maybe if maybe.content is None else Maybe(content=fn(maybe.content, **kwargs))

T1 = TypeVar('T1')
T2 = TypeVar('T2')
def maybe_monad_join(maybe: Maybe[T], fn: Callable[[T1, Any], Maybe[T2]], **kwargs) -> Maybe[T2]:
  # This is a monadic join
  return maybe if maybe.content is None else fn(maybe.content, **kwargs)

T1 = TypeVar('T1')
T2 = TypeVar('T2')
async def async_maybe_monad_join(maybe: Maybe[T], fn: Callable[[T1, Any], Maybe[T2]], **kwargs) -> Maybe[T2]:
  # This is a monadic join
  return maybe if maybe.content is None else await fn(maybe.content, **kwargs)




async def chunked_gather(awaitable_list: List[Awaitable], chunk_size: int = 100, verbose: bool = False, use_subchunking_for_first_iteration: bool = False) -> List[Any]:
  """
  Given a list of awaitables, gather them in chunks of 1000 to avoid overloading the event loop.
  """
  start = time.time()
  gathered_list = []
  if len(awaitable_list) == 0:
    print("WARNING: chunked_gather called with empty awaitable_list")
  else:
    chunk_size = min(len(awaitable_list), chunk_size)

    if use_subchunking_for_first_iteration:
      subchunk_size = int(chunk_size // 5)
      for i in range(0, chunk_size, subchunk_size):
        end_index = min(chunk_size, i+subchunk_size)
        if verbose:
          print(f"Batch {i}:{min(len(awaitable_list), end_index)} out of {len(awaitable_list)} [{int(time.time() - start)} seconds]")
        gathered_list += await asyncio.gather(*awaitable_list[i:end_index])
      start_index = chunk_size
    else:
      start_index = 0
    for i in range(start_index, len(awaitable_list), chunk_size):
      if verbose:
        print(f"Batch {i}:{min(len(awaitable_list), i+chunk_size)} out of {len(awaitable_list)} [{int(time.time() - start)} seconds]")
      gathered_list += await asyncio.gather(*awaitable_list[i:i+chunk_size])
  return gathered_list


def safe_to_int(value: Optional[Any]) -> Optional[int]:
  if value is None:
    return None
  else:
    try:
      return int(value)
    except ValueError as e:
      return None

def safe_to_str(value: Optional[Any]) -> Optional[str]:
  if value is None:
    return None
  else:
    try:
      return str(value)
    except ValueError as e:
      return None
    
def zip_with_exception(l1: List[Any], l2: List[Any]) -> List[Tuple[Any, Any]]:
  if len(l1) != len(l2):
    raise ValueError(f"Lists must be the same length to zip. Lengths: {len(l1)}, {len(l2)}")
  return list(zip(l1, l2))


def memoize(func):
  """
  (c) 2021 Nathan Henrie, MIT License
  https://n8henrie.com/2021/11/decorator-to-memoize-sync-or-async-functions-in-python/
  """
  cache = {}

  async def memoized_async_func(*args, **kwargs):
    key = (args, frozenset(sorted(kwargs.items())))
    if key in cache:
      return cache[key]
    result = await func(*args, **kwargs)
    cache[key] = result
    return result

  def memoized_sync_func(*args, **kwargs):
    key = (args, frozenset(sorted(kwargs.items())))
    if key in cache:
      return cache[key]
    result = func(*args, **kwargs)
    cache[key] = result
    return result

  if asyncio.iscoroutinefunction(func):
    return memoized_async_func
  return memoized_sync_func




def get_rdn_from_url(url: str) -> str:
  tld_extract_result = tldextract.extract(url)
  return tld_extract_result.registered_domain

def get_fqdn_from_url(url: str) -> str:
  tld_extract_result = tldextract.extract(url)
  return '.'.join([r for r in [tld_extract_result.subdomain, tld_extract_result.domain, tld_extract_result.suffix] if len(r) > 0])

def get_rdn_from_fqdn(fqdn: str) -> str:
  return get_rdn_from_url("http://" + fqdn)


def get_url_from_domain(domain: str) -> str:
  # Try making an http call, and see if it redirects to https
  try:
    r = requests.get(f'https://{domain}')
    if str(r.status_code)[0] == '2':
      return f'https://{domain}'      
  except Exception as e:
    pass
  return f'http://{domain}'
  

def read_yaml_file(file_path: str) -> Dict[str, Any]:
  with open(file_path, 'r') as file:
    data = yaml.safe_load(file)
  return data

def write_yaml_file(data: Dict[str, Any], file_path: str):
  with open(file_path, 'w') as file:
    yaml.dump(data, file)

async def run_with_logs(*args, process_name: str):
  args_string = " ".join(args)
  print(f"Running {process_name} with {args_string}...")
  with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
    for s in [process.stdout, process.stderr]:
      if s is not None:
        for line in s:
          print(line.decode('utf8'))



T = TypeVar("T")
def load_pydantic_model_from_file_path(path: str, cls: T) -> T:
  with open(path, "r") as f:
    return cls.model_validate_json(f.read())


T = TypeVar("T")
def load_pydantic_model_from_directory_path(path: str, cls: T) -> List[T]:
  fname_list = os.listdir(path)
  print(f"Loading {len(fname_list)} files from path: {path}")

  visited_url_list = []
  for fname in fname_list:
    # Subdirectories should not be loaded
    fpath = os.path.join(path, fname)
    if os.path.isfile(fpath) and fname.endswith(".json"):
      with open(fpath, "r") as f:
        try:
          visited_url_list.append(cls.model_validate_json(f.read()))
        except Exception as e:
          print(f"ERROR on fpath: {fpath}")
          raise e
    else:
      print(f"Skipping {fpath} because it is not a file or does not end with .json")
  return visited_url_list


def modify_url(url: str, base_url: Optional[str] = None, url_parameters: Optional[Dict[str, Any]] = None) -> str:
  # Parse the original URL
  parsed_url = urllib.parse.urlparse(url)
  
  # If base_url is provided, parse it and use its scheme, netloc, and path
  if base_url is not None:
    parsed_base = urllib.parse.urlparse(base_url)
    scheme, netloc, path = parsed_base.scheme, parsed_base.netloc, parsed_base.path
  else:
    scheme, netloc, path = parsed_url.scheme, parsed_url.netloc, parsed_url.path
  
  # Parse existing query parameters from the URL
  url_params_dict = urllib.parse.parse_qs(parsed_url.query)
  
  # If url_parameters is provided, update existing parameters with new ones
  if url_parameters is not None:
    url_params_dict.update(url_parameters)
  
  # Build new query string
  query = urllib.parse.urlencode(url_params_dict, doseq=True)
  
  # Reconstruct the URL with the new scheme, netloc, path, and query
  new_url = urllib.parse.urlunparse((scheme, netloc, path, '', query, ''))
  
  return new_url


def filter_url(
  url: str,
  included_fqdn_regex: Optional[str] = None,
  excluded_fqdn_regex_list: Optional[List[str]] = None,
  included_url_regex: Optional[str] = None,
  excluded_url_regex_list: Optional[List[str]]  = None
) -> bool:
  """
  Return True if the url matches the filter
  """

  print(f"filter_url called with url: {url} included_fqdn_regex: {included_fqdn_regex} excluded_fqdn_regex_list: {excluded_fqdn_regex_list} included_url_regex: {included_url_regex} excluded_url_regex_list: {excluded_url_regex_list}")


  fqdn = get_fqdn_from_url(url)

  included = True
  if included and included_fqdn_regex is not None:
    included = re.fullmatch(included_fqdn_regex, fqdn) is not None
  if included and included_url_regex is not None:
    included = re.fullmatch(included_url_regex, url) is not None
  if included and  excluded_fqdn_regex_list is not None and len(excluded_fqdn_regex_list) > 0:
    included = not any(re.fullmatch(excluded_fqdn_regex, fqdn) is not None for excluded_fqdn_regex in excluded_fqdn_regex_list)
  if included and excluded_url_regex_list is not None and len(excluded_url_regex_list) > 0:
    included = not any(re.fullmatch(excluded_url_regex, url) is not None for excluded_url_regex in excluded_url_regex_list)
  return included


def filter_url_list(
  url_list: List[str],
  **kwargs
) -> bool:
  """
  Return the list of urls that match the filter
  """
  return [url for url in url_list if filter_url(url, **kwargs)]
  

def safe_apply(obj, fn):
 return None if obj is None else fn(obj)

def pydantic_validate(cls, obj):
  try:
    cls.model_validate(obj)
  except Exception as e:
    print("---ERROR in pydantic_validate ----")
    for k, v in obj.__dict__.items():
      print(k, type(v))

    if isinstance(obj, cls):
      print(obj.model_dump_json(indent=2))

    raise e

def pydantic_create(cls, **kwargs):
  try:
    output = cls(**kwargs)
    cls.model_validate(output)
  except Exception as e:
    for k, v in kwargs.items():
      print(k, type(v))
    raise e
  return output



def url_to_filepath(url: str) -> str:
  return url.split("?")[0].replace("/", "_").replace(":", "_")[:100] + str(uuid.uuid4())

def get_base_url_from_url(url: str) -> str:
  return url.split("?")[0]


def is_json(string: str) -> bool:
  try:
    json.loads(string)
  except Exception as e:
    return False
  else:
    return True

async def get_response_value_from_domain(
  client: httpx.AsyncClient,
  fqdn: str,
  fn: Callable[[aiohttp.ClientResponse], T],
  method_string: str = "get"
) -> Optional[T]:

  headers = {'Host': fqdn}

  client_method = {
    "get": client.get,
    "head": client.head
  }[method_string]
  try:
    try:
      response = await client_method(f"https://{fqdn}", headers=headers, follow_redirects=True)
      response_value = fn(response)
    except Exception as e:
      # We start with https and fall back to http if it fails
      response = await client_method(f"http://{fqdn}", headers=headers, follow_redirects=True)
      response_value = fn(response)
  except Exception as e:
    print(f"[get_response_value_from_domain] Exception on domain: {fqdn}: -------START EXCEPTION----------\n{e}\n-------END EXCEPTION-------")
    response_value = None
  return response_value


T = TypeVar("T")
async def get_domain_to_response_value_list(fqdn_list: List[str], fn: Callable[[aiohttp.ClientResponse], T], method_string: str = "get") -> Dict[str, Optional[T]]:

  async with httpx.AsyncClient(verify=False) as client:
    extracted_value_list = await chunked_gather([get_response_value_from_domain(client=client, fqdn=fqdn, fn=fn, method_string=method_string) for fqdn in fqdn_list])
  return dict(zip(fqdn_list, extracted_value_list))


def json_dumps_safe(obj: Any) -> Optional[str]:
  if obj is None:
    return None
  else:
    return json.dumps(obj, indent=2, sort_keys=True, default=str)
  


def replace_in_dict(d: Dict[str, Any], to_replace: str, replacement: str) -> Dict[str, Any]:
  """
  Recursively replace all occurrences of 'to_replace' with 'replacement' in a dictionary.
  
  :param d: The dictionary to traverse.
  :param to_replace: The string to be replaced.
  :param replacement: The string to replace 'to_replace' with.
  """
  for key, value in d.items():
    if isinstance(value, dict):
      # If the value is a dictionary, recursively apply the function
      replace_in_dict(d=value, to_replace=to_replace, replacement=replacement)
    elif isinstance(value, str):
      # If the value is a string, replace occurrences of 'to_replace'
      d[key] = value.replace(to_replace, replacement)
    # If the value is neither a dictionary nor a string, it remains unchanged
  return d


def get_single_html_diff_string(starting_html: str, ending_html: str, buffer: int) -> str:
  # Returns the sections of the ending_html that are different from the starting_html
  dmp = diff_match_patch()
  patches = dmp.patch_make(starting_html=starting_html, ending_html=ending_html)
  diff_list = [ending_html[p.start2 - buffer:p.start2 + p.length2 + buffer] for p in patches]
  return "|".join(diff_list)


def ensure_url_encoded(input_string: str) -> str:
  """
  Given an input string, check if it's already URL encoded. If it's not, encode it.
  """
  # Try decoding the string
  decoded_string = str(urllib.parse.unquote(input_string))
  
  # If the decoded string is different from the original, it's likely encoded
  if decoded_string != input_string:
    output_string = input_string # Already encoded, return as is
  else:
    # Not encoded, encode it
    output_string = str(urllib.parse.quote(input_string))
  return output_string


def contains_non_url_encoded_characters(input_string: str) -> bool:
  """
  Returns True if a string is definitely not a valid URL-encoded string, and False otherwise.


  NOTE: This may be less useful than you thought, since non-standard characters are actually allowed in the query part of a URL. See https://web.archive.org/web/20151229061347/http://blog.lunatech.com/2009/02/03/what-every-web-developer-must-know-about-url-encoding. 
  """

  # Whitelist of characters allowed in a URL
  # allowed_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~:/?#[]@!$&'()*+,;="
  allowed_chars = set(list(string.ascii_letters) + list(string.digits) + ['-', '_', '.', '~'])

  # Check if each character in the string is allowed in a URL
  for i, char in enumerate(input_string):
    if char not in allowed_chars:
      # Check if the character is already part of a URL encoding
      if not re.match(r'%[0-9A-Fa-f]{2}', input_string[i:i+3]):
        return True  # Requires URL encoding

  return False  # No encoding required

  # is_equal_to_decoded_string = str(urllib.parse.unquote(input_string)) == input_string
  # string_is_not_equal_to_url_decoded_string = str(urllib.parse.unquote(input_string)) != input_string

  # contains_non_url_encoded_characters = False
  # # Iterate through the string
  # for i in range(len(input_string)):
  #   # Check if the current character is part of a URL-encoded sequence
  #   if input_string[i] == '%' and i + 2 < len(input_string) and input_string[i+2:i+3].isalnum():
  #     # Skip the next two characters as they are part of the URL-encoded sequence
  #     i += 2
  #   else:
  #     # If the character is not part of a URL-encoded sequence, set the flag to False
  #     contains_non_url_encoded_characters = True
  #     print(f"i: {i}")
  #     break

  # # If the string contains non-encoded characters but these characters don't decode, then this is definitely not a valid URL-encoded string
  # return contains_non_url_encoded_characters# and is_equal_to_decoded_string





