from datetime import datetime
import dns.resolver
import logging
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, TypeVar, Union

from pydantic import BaseModel
import asyncwhois
import whodap

import numpy as np
import asyncio
import httpx
import tldextract

import whois


def safe_to_str(value: Optional[Any]) -> Optional[str]:
  if value is None:
    return None
  else:
    try:
      return str(value)
    except ValueError as e:
      return None
    

async def call_with_rate_limit_retry(
  fn: Callable[[Any], Coroutine],
  exception: Exception,
  sleep_seconds_min: int = 2,
  sleep_seconds_max: int = 10,
  **kwargs
) -> Any:
  try:
    out = await fn(**kwargs)
  except exception as e:
    print(f"Exception {str(e)} caught in call_with_rate_limit_retry")
    sleep_seconds = 2 + (np.random.random() * (sleep_seconds_max - sleep_seconds_min))
    
    # NOTE: asyncio.sleep will only cause this async run to sleep, not the whole program
    await asyncio.sleep(sleep_seconds)
    out = await fn(**kwargs)
  return out


def get_rdn_from_url(url: str) -> str:
  tld_extract_result = tldextract.extract(url)
  return tld_extract_result.registered_domain


class DomainLookupField:
  # NOTE: These need to all be fields in DomainLookupResponse
  REGISTRANT_NAME = "registrant_name"
  REGISTRAR_NAME = "registrar_name"
  STATUS = "status"
  NAMESERVERS = "nameservers"
  EXPIRES = "expires"
  UPDATED = "updated"
  CREATED = "created"

CRITICAL_DOMAIN_LOOKUP_FIELDS = [DomainLookupField.CREATED, DomainLookupField.REGISTRAR_NAME]


def _parse_whois_date(date_or_list: Union[str, datetime, List[Union[str, datetime]]]) -> str:
  """
  The input to this 
  """
  date = (date_or_list[-1] if isinstance(date_or_list, list) else date_or_list)
  return date.isoformat() if hasattr(date, 'isoformat') else str(date)


T1 = TypeVar("T1")
T2 = TypeVar("T2")

class AsyncCache:

  def __init__(self, async_fn: Callable[[T1], Coroutine], time_delay: int = 2, verbose: bool = False):
    self.request_set = set()
    self.cache = {}
    self.async_fn = async_fn
    self.time_delay = time_delay
    self.verbose = verbose

  async def run(self, key: T1, **kwargs) -> T2:
    """
    This is a method that captures an async-await cache pattern
    """
    while True:
      if key in self.request_set:
        # This is being processed on another thread. Go to sleep for a few seconds before checking again.
        if self.verbose:
          print(f"[AsyncCache] with fn: {self.async_fn} sleeping on {key}")
        await asyncio.sleep(self.time_delay)
      elif key in self.cache:
        return self.cache[key]
      else:
        # First add the key to the request_set synchronously so no other thread will try to process it
        assert key not in self.request_set
        self.request_set.add(key)

        # Await the result of the async_fn
        value = await self.async_fn(key, **kwargs)

        # Add the value to the cache and remove the key from the request set
        self.cache[key] = value
        self.request_set.remove(key)
        assert key not in self.request_set
        return self.cache[key]

class DomainLookupTool:

  # TODO: Make the caching more advanced so that the same domain never gets queried multiple times in parallel, and one query propagates to all domains
  # TODO: Add a fallback to synchronous whois

  """
  This class serves as an interface to RDAP and Whois APIs that caches calls for particular domains
  """
  FIELD_TO_RDAP_EXTRACTOR = {
    DomainLookupField.REGISTRANT_NAME: lambda whois_dict: whois_dict.get("registrant_name"),
    DomainLookupField.REGISTRAR_NAME: lambda whois_dict: whois_dict.get("registrar_name"),
    DomainLookupField.STATUS:  lambda whois_dict: whois_dict.get("status"),
    DomainLookupField.NAMESERVERS:lambda whois_dict: whois_dict.get("nameservers"),
    DomainLookupField.EXPIRES: lambda whois_dict: None if whois_dict.get("expires") is None else _parse_whois_date(whois_dict["expires"]),
    DomainLookupField.UPDATED: lambda whois_dict: None if whois_dict.get("updated") is None else _parse_whois_date(whois_dict["updated"]),
    DomainLookupField.CREATED: lambda whois_dict: None if whois_dict.get("created") is None else _parse_whois_date(whois_dict["created"]),
  }

  FIELD_TO_WHOIS_EXTRACTOR = {
    DomainLookupField.REGISTRANT_NAME: lambda whois_dict: whois_dict.get("registrant"),
    DomainLookupField.REGISTRAR_NAME: lambda whois_dict: whois_dict.get("registrar"),
    DomainLookupField.STATUS: lambda whois_dict: whois_dict.get("status"),
    DomainLookupField.NAMESERVERS: lambda whois_dict: whois_dict.get("name_servers"),
    DomainLookupField.EXPIRES: lambda whois_dict: None if whois_dict.get("expiration_date") is None else _parse_whois_date(whois_dict["expiration_date"]),
    DomainLookupField.UPDATED: lambda whois_dict: None if whois_dict.get("updated_date") is None else _parse_whois_date(whois_dict["updated_date"]),
    DomainLookupField.CREATED: lambda whois_dict: None if whois_dict.get("creation_date") is None else _parse_whois_date(whois_dict["creation_date"]),
  }


  def __init__(self, verbose: bool = False):
    self.rdap_cache = AsyncCache(self._get_rdap_response_from_registered_domain, verbose=verbose)
    self.async_whois_cache = AsyncCache(self._get_async_whois_response_from_registered_domain, verbose=verbose)
    self.sync_whois_cache = AsyncCache(self._get_sync_whois_response_from_registered_domain, verbose=verbose)

  async def _get_sync_whois_response_from_registered_domain(
    self,
    registered_domain_name: str
  ) -> Dict[str, Any]:
    """
    Run a whois lookup using https://pypi.org/project/python-whois/

    This is the older domain lookup standard, but it will have data for ccTLD domains that RDAP does not support.
    """
    print(f"RUNNING SYNC WHOIS LOOKUP FOR {registered_domain_name}")
    try:
      response_dict = whois.whois(registered_domain_name)
    except Exception as e:
      # NOTE: In the future we will want to distinguish between the different kinds of errors. For example, the `whodap.errors.NotFoundError` is likely indicative of something different than the `whodap.errors.RateLimitError`
      logging.error(f"Error in _get_sync_whois_response_from_registered_domain on {registered_domain_name}: {e}")
      response_dict = {}

    whois_field_to_value = {
      field_name: whois_response_extractor(response_dict)
      for field_name, whois_response_extractor in self.FIELD_TO_WHOIS_EXTRACTOR.items()
    }
    return whois_field_to_value
  
  async def get_sync_whois_response_from_registered_domain(
    self,
    registered_domain_name: str
  ) -> Dict[str, Any]:
    return await self.sync_whois_cache.run(registered_domain_name)

  
  async def _get_async_whois_response_from_registered_domain(
    self,
    registered_domain_name: str
  ) -> Dict[str, Any]:
    """
    Run a whois lookup using https://github.com/pogzyb/asyncwhois

    This is the older domain lookup standard, but it will have data for ccTLD domains that RDAP does not support.
    """
    print(f"RUNNING ASYNC WHOIS LOOKUP FOR {registered_domain_name}")
    try:
      # NOTE: The asyncwhois package does not work for whois queries
      # raw_response = whois.query(registered_domain_name)
      query_output = (await asyncwhois.aio_whois_domain(registered_domain_name)).query_output
    except Exception as e:
      # NOTE: In the future we will want to distinguish between the different kinds of errors. For example, the `whodap.errors.NotFoundError` is likely indicative of something different than the `whodap.errors.RateLimitError`
      logging.error(f"Error in _get_async_whois_response_from_registered_domain on {registered_domain_name}: {e}")
      response_dict = {}
    else:
      # NOTE: This is an OSS contribution candidate
      # NOTE: The builtin parser to asyncwhois is not very good. The parser in the whois library is better. So I'm using the raw query output from the asynciowhois and piping it to the whois parser

      # TODO: Potentially switch to https://github.com/DannyCork/python-whois/blob/83112c5fb8e15abd7f9c9a69653e22896299ac3d/whois/__init__.py#L169 if you want to improve parsing
      response_dict = (
        None if query_output is None else
        whois.parser.WhoisEntry.load(registered_domain_name, query_output)
      )
    whois_field_to_value = {
      field_name: whois_response_extractor(response_dict)
      for field_name, whois_response_extractor in self.FIELD_TO_WHOIS_EXTRACTOR.items()
    }
    return whois_field_to_value
  
  async def get_async_whois_response_from_registered_domain(
    self,
    registered_domain_name: str
  ) -> Dict[str, Any]:
    return await self.async_whois_cache.run(registered_domain_name)

  async def _get_rdap_response_from_registered_domain(
    self,
    registered_domain_name: str,
    httpx_client: httpx.AsyncClient,
    verbose: bool = True
  ) -> Optional[Dict[str, Any]]:
    """
    Run a whois lookup using https://github.com/pogzyb/whodap

    This is the newer domain lookup standard, but it will not cover ccTLD domains
    """
    print(f"RUNNING RDAP LOOKUP FOR {registered_domain_name}")
    tld_extract_result = tldextract.extract(registered_domain_name)
    extracted_domain_name = tld_extract_result.domain
    tld = tld_extract_result.suffix.split(".")[-1]
    try:
      response = await call_with_rate_limit_retry(
        fn=whodap.aio_lookup_domain,
        exception=whodap.errors.RateLimitError,
        domain=extracted_domain_name,
        # NOTE: This means that co.uk will get .uk as the tld
        tld=tld,
        httpx_client=httpx_client,
      )

      # NOTE: There are some bugs in whodap that can cause this to fail with a TypeError
      response_dict = response.to_whois_dict()
    except Exception as e:
      # NOTE: In the future we will want to distinguish between the different kinds of errors. For example, the `whodap.errors.NotFoundError` is likely indicative of something different than the `whodap.errors.RateLimitError`
      if verbose:
        print(f"Error in get_rdap_response_from_domain on {registered_domain_name}: {e}")
      response_dict = {}
      
    rdap_field_to_value = {
      field_name: (None if field_name not in response_dict else rdap_response_extractor(response_dict))
      for field_name, rdap_response_extractor in self.FIELD_TO_RDAP_EXTRACTOR.items()
    }

    return rdap_field_to_value
  
  async def get_rdap_response_from_registered_domain(
    self,
    registered_domain_name: str,
    httpx_client: httpx.AsyncClient,
    verbose: bool = True
  ) -> Dict[str, Any]:
    return await self.rdap_cache.run(registered_domain_name, httpx_client=httpx_client, verbose=verbose)



class DomainLookupResponse(BaseModel):
  # NOTE: These need to be a superset of the fields on DomainLookupField
  fqdn: str
  registrant_name: Optional[str]
  registrar_name: Optional[str]
  status: Optional[str]
  nameservers: Optional[str]
  expires: Optional[str]
  updated: Optional[str]
  created: Optional[str]


  def display(self):
    print(f"""
      fqdn: {self.fqdn}
      registrant_name: {self.registrant_name}
      registrar_name: {self.registrar_name}
      status: {self.status}
      nameservers: {self.nameservers}
      expires: {self.expires}
      updated: {self.updated}
      created: {self.created}
    """)

  @classmethod
  async def from_fqdn(
    cls,
    fqdn: str,
    domain_lookup_tool: "Optional[DomainLookupTool]" = None,
    httpx_client: Optional[httpx.AsyncClient] = None,
    verbose: bool = True,
    try_rdap: bool = True,
    try_async_whois: bool = True
  ) -> "DomainLookupResponse":
    
    registered_domain_name = get_rdn_from_url(fqdn)
    domain_lookup_tool = domain_lookup_tool if domain_lookup_tool is not None else DomainLookupTool()
    httpx_client = httpx_client if httpx_client is not None else httpx.AsyncClient(verify=False)
    
    whois_rdap_field_to_value = {}
    # RDAP is the first try
    if try_rdap:
      whois_rdap_field_to_value = await domain_lookup_tool.get_rdap_response_from_registered_domain(
        registered_domain_name=registered_domain_name,
        httpx_client=httpx_client,
        verbose=verbose
      )
      
    # Then try async whois
    if try_async_whois:
      if any([whois_rdap_field_to_value.get(response) is None for response in CRITICAL_DOMAIN_LOOKUP_FIELDS]):
        async_whois_response = await domain_lookup_tool.get_async_whois_response_from_registered_domain(registered_domain_name=registered_domain_name)
        for field_name, field_value in async_whois_response.items():
          if whois_rdap_field_to_value.get(field_name) is None:
            whois_rdap_field_to_value[field_name] = field_value

    # Final fallback is sync whois (slow)
    if any([whois_rdap_field_to_value.get(response) is None for response in CRITICAL_DOMAIN_LOOKUP_FIELDS]):
      sync_whois_response = await domain_lookup_tool.get_sync_whois_response_from_registered_domain(registered_domain_name=registered_domain_name)
      for field_name, field_value in sync_whois_response.items():
        if whois_rdap_field_to_value.get(field_name) is None:
          whois_rdap_field_to_value[field_name] = field_value

    # NOTE: We need to use safe_to_str because whois data is not consistently normalized, some fields might be lists sometimes and strings other times
    return cls(
      fqdn=fqdn,
      registrant_name=safe_to_str(whois_rdap_field_to_value.get("registrant_name")),
      registrar_name=safe_to_str(whois_rdap_field_to_value.get("registrar_name")),
      status=safe_to_str(whois_rdap_field_to_value.get("status")),
      nameservers=safe_to_str(whois_rdap_field_to_value.get("nameservers")),
      expires=safe_to_str(whois_rdap_field_to_value.get("expires")),
      updated=safe_to_str(whois_rdap_field_to_value.get("updated")),
      created=safe_to_str(whois_rdap_field_to_value.get("created"))
    )
