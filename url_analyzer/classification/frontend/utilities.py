import asyncio
import json
import os
from typing import Any, Dict
import requests
from typing import Dict


class UrlClassifierInterface:
  """
  An interface to the UrlClassification service that is running elsewhere. It's important to have separation of batch analytics through this kind of REST interface since the urls that are being checked are potentially malicious, and we want to ensure some separation between the batch analytics and the actual classification service.
  """
  def __init__(self, use_local: bool):

    self.base_path = (
      'http://0.0.0.0:8000' if use_local else os.environ["URL_CLASSIFIER_REMOTE_BASE_PATH"]
    )
    print(f"Connecting to url classification service at {self.base_path}")
    self.api_key = self.get_api_key()

  def get_api_key(self):
    path = f'{self.base_path}/get_api_key'
    response = requests.get(path)
    response.raise_for_status()
    data = response.json()
    return data.get('api_key')

  async def classify_url(self, url: str) -> Dict[str, Any]:
    """
    Given a URL, use the classify endpoint to get the classification results

    Args:
      url: str: The URL to classify
    Returns:
      Dict[str, Any]: The classification results
    
    """
    # TODO: Change this to be actually async with httpx or something
    try:
      print(f'Checking URL: {url}')
      headers = {
        'Authorization': f'Bearer {self.api_key}',
        'Content-Type': 'application/json'
      }

      params = {
        "url": url
      }

      path = f'{self.base_path}/classify'
      print(
        f"""
        Sending request!
        ----target----
        {path}
        ---headers-----
        {headers}
        ----params----
        {params}
        --------
        """
      )
      response = requests.post(path, params=params,  headers=headers)
    except requests.RequestException as e:
      print(f'Error checking URL: {e}')
      result = {'error': 'Failed to check URL'}
    else:
      print(f'Response: {response}')
      data = response.json()

      if response.status_code != 200:
        print(f'Setting error: {data.get("detail")}')
        result = {'error': data.get('detail')}
      else:
        print(f'Setting result: {data}')
        result = data

    return result



  async def classify_url_and_log_results_to_file(self, url: str, log_file: str) -> Dict[str, Any]:
    """
    Given a URL, use the classify endpoint to get the classification results and log them to a file

    Args:
      url: str: The URL to classify
      log_file: str: The path to the log file
    """
    response_dict = await self.classify_url(url=url)
    if response_dict.get("error") is not None:
      filtered_response_dict = response_dict
    else:
      filtered_response_dict = response_dict.get("url_classification")
      if filtered_response_dict is None or len(filtered_response_dict) == 0:
        print(f"Error: No keys in 'url_classification' key in response: \n-----\n{json.dumps(response_dict, indent=2)}\n----\n")
        filtered_response_dict = {}

    print(f"Logging results for {url} to {log_file}")
    with open(log_file, "a") as f:
      f.write(
        json.dumps({url: filtered_response_dict}, indent=2)
      )
      f.write("\n---------\n")
    return response_dict




async def classify_urls_in_text_file(
  path_to_file_with_urls: str,
  log_file: str,
  use_local: bool = False
) -> Dict[str, Dict[str, Any]]:
  """
  Args:
    path_to_file_with_urls: str: Path to a file in which each line is a URL
    chunk_size: int: The number of URLs to check at once
  Returns:
    Dict[str, Dict[str, Any]]: A dictionary mapping URLs to their classification results
  """
  with open(path_to_file_with_urls, 'r') as f:
    url_list = [url.strip() for url in f.readlines()]

  url_classifier_interface = UrlClassifierInterface(use_local=use_local)

  return await asyncio.gather(
    *[url_classifier_interface.classify_url_and_log_results_to_file(url=url, log_file=log_file) for url in url_list]
  )
