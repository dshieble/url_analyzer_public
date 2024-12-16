import base64
import json
import logging
from typing import Optional

from pydantic import BaseModel
from url_analyzer.classification.browser_automation.response_record import ResponseRecord
from url_analyzer.classification.classifier.prompts import CLASSIFICATION_FUNCTION, CLASSIFY_URL, DOMAIN_DATA_DESCRIPTION_STRING_TEMPLATE, PHISHING_CLASSIFICATION_PROMPT_TEMPLATE, URL_TO_CLASSIFY_PROMPT_STRING_TEMPLATE
from url_analyzer.classification.llm.utilities import cutoff_string_at_token_count
from url_analyzer.classification.llm.openai_interface import get_response_from_prompt_one_shot
from url_analyzer.classification.llm.constants import LLMResponse
from url_analyzer.classification.llm.formatting_utils import load_function_call
from url_analyzer.classification.html_understanding.html_understanding import HTMLEncoding, get_processed_html_string
from url_analyzer.classification.classifier.image_understanding import get_image_description_string_from_url_to_classify
from url_analyzer.classification.classifier.domain_data import DomainData
from url_analyzer.classification.classifier.url_to_classify import UrlToClassify



class PageData(BaseModel):
  base64_encoded_image: Optional[bytes] = None

  @classmethod
  async def from_url_to_classify(cls, url_to_classify: UrlToClassify) -> "PageData":
    screenshot_bytes = await url_to_classify.url_screenshot_response.get_screenshot_bytes()
    base64_encoded_image = base64.b64encode(screenshot_bytes).decode("utf-8")
    return cls(
      base64_encoded_image=base64_encoded_image
    )

URL_CLASSIFICATION_FIELDS = [
  "page_summary",
  "impersonation_strategy",
  "credential_theft_strategy",
  "thought_process",
  "classification",
  "justification"
]
class UrlClassification(BaseModel):
  page_summary: str
  impersonation_strategy: str
  credential_theft_strategy: str
  thought_process: str
  classification: str
  justification: str

  def display(self):
    print(json.dumps(self.model_dump_json(), indent=2))
  
class RichUrlClassificationResponse(BaseModel):
  page_data: PageData
  domain_data: DomainData
  url_classification: Optional[UrlClassification] = None
  llm_response: LLMResponse

  @classmethod
  async def construct(
    cls,
    url_to_classify: UrlToClassify,
    domain_data: DomainData,
    llm_response: LLMResponse
  ) -> "RichUrlClassificationResponse":
    
    url_classification = None
    if llm_response.response is not None:
      maybe_formatted_response = load_function_call(raw_llm_response=llm_response.response, argument_name=CLASSIFY_URL)
      if (
        maybe_formatted_response.content is not None
        and set(URL_CLASSIFICATION_FIELDS) <= set(maybe_formatted_response.content.keys())
      ):
        url_classification = UrlClassification(**{
          key: maybe_formatted_response.content[key]
          for key in URL_CLASSIFICATION_FIELDS
        })
      else:
        logging.error(
          f"""Could not extract url classification from response!
          llm_response.response
          {llm_response.response}

          maybe_formatted_response
          {maybe_formatted_response}
          """
        )
    return cls(
      page_data=await PageData.from_url_to_classify(url_to_classify=url_to_classify),
      domain_data=domain_data,
      url_classification=url_classification,
      llm_response=llm_response
    )

def get_network_log_string_from_response_log(
  response_log: list[ResponseRecord],
  link_token_count_max: int = 100,
  total_token_count_max: int = 5000
) -> str:
  
  processed_response_record_list = [
    f"{response_record.request_method} to "
      + cutoff_string_at_token_count(
        string=response_record.request_url,
        max_token_count=link_token_count_max
      )
      + ("" if response_record.request_post_data is None else f"with data {response_record.request_post_data}")
    for response_record in response_log
  ]
  raw_processed_response_record_list_string = "\n".join(
    processed_response_record_list
  )
  return cutoff_string_at_token_count(
    string=raw_processed_response_record_list_string,
    max_token_count=total_token_count_max
  )



async def convert_url_to_classify_to_string(
  url_to_classify: UrlToClassify,
  domain_data: DomainData,
  max_html_token_count: int = 4000,
  max_urls_on_page_string_token_count: int = 4000,
  max_network_log_string_token_count: int = 4000,
  html_encoding: str = HTMLEncoding.RAW,
  generate_llm_screenshot_description: bool = True
) -> str:
  """
  A method to convert a UrlToClassify object to a string that can be used as a prompt for an LLM
  """
  print(f"[convert_url_to_classify_to_string] Converting url to string: {url_to_classify.url}")

  # Domain Data String
  if domain_data is None:
    raise ValueError("Domain data must be provided to convert_url_to_classify_to_string")
  
  domain_data_description_string = DOMAIN_DATA_DESCRIPTION_STRING_TEMPLATE.format(
    domain_data_json_dump=domain_data.model_dump_json()
  )

  # Image description
  if generate_llm_screenshot_description:
    print(f"[convert_url_to_classify_to_string] Generating an LLM image description of the url screenshot for {url_to_classify.url}")
    optional_image_description_string = await get_image_description_string_from_url_to_classify(url_to_classify=url_to_classify)
    image_description_string = optional_image_description_string if optional_image_description_string is not None else ""
  else:
    print(f"[convert_url_to_classify_to_string] Skipping image description generation for {url_to_classify.url}")
    image_description_string = ""

  # HTML String
  processed_html_string = get_processed_html_string(
    html=url_to_classify.html,
    html_encoding=html_encoding
  )
  trimmed_ending_html = cutoff_string_at_token_count(
    string=processed_html_string, max_token_count=max_html_token_count)

  # Urls on Page String 
  # TODO: Do something smarter where you order urls by domain in a way that you preferentially cut off urls from domains where other urls are in the prompt
  trimmed_urls_on_page_string = cutoff_string_at_token_count(
    string="\n".join(url_to_classify.urls_on_page),
    max_token_count=max_urls_on_page_string_token_count
  )

  # Network Log String
  network_log_string = get_network_log_string_from_response_log(response_log=url_to_classify.response_log)
  trimmed_network_log_string = cutoff_string_at_token_count(
    string=network_log_string,
    max_token_count=max_network_log_string_token_count
  )

  return URL_TO_CLASSIFY_PROMPT_STRING_TEMPLATE.format(
    url=url_to_classify.url,
    domain_data_description_string=domain_data_description_string,
    image_description_string=image_description_string,
    trimmed_html=trimmed_ending_html,
    urls_on_page_string=trimmed_urls_on_page_string,
    network_log_string=trimmed_network_log_string
  )


async def get_phishing_classification_prompt_from_url_to_classify(
  url_to_classify: UrlToClassify,
  domain_data: DomainData,
  max_html_token_count: int = 4000,
  html_encoding: str = HTMLEncoding.RAW
) -> str:
  url_to_classify_string = await convert_url_to_classify_to_string(
    url_to_classify=url_to_classify,
    domain_data=domain_data,
    max_html_token_count=max_html_token_count,
    html_encoding=html_encoding
  )
  return PHISHING_CLASSIFICATION_PROMPT_TEMPLATE.format(url_to_classify_string=url_to_classify_string)

async def get_raw_url_classification_llm_response_from_url_to_classify(
  url_to_classify: UrlToClassify,
  domain_data: DomainData,
  max_html_token_count: int = 2000,
  html_encoding: str = HTMLEncoding.RAW
) -> LLMResponse:

  phishing_classification_prompt = await get_phishing_classification_prompt_from_url_to_classify(
    url_to_classify=url_to_classify,
    domain_data=domain_data,
    max_html_token_count=max_html_token_count,
    html_encoding=html_encoding
  )
  llm_response = await get_response_from_prompt_one_shot(
    prompt=phishing_classification_prompt,
    tools=[CLASSIFICATION_FUNCTION],
    tool_choice="auto",
  )
  return llm_response
  

async def classify_url(
  url_to_classify: UrlToClassify,
  max_html_token_count: int = 2000,
  html_encoding: str = HTMLEncoding.RAW
) -> RichUrlClassificationResponse:
  
  domain_data = await DomainData.from_url(url=url_to_classify.url)

  llm_response = await get_raw_url_classification_llm_response_from_url_to_classify(
    url_to_classify=url_to_classify,
    domain_data=domain_data,
    max_html_token_count=max_html_token_count,
    html_encoding=html_encoding
  )
  return await RichUrlClassificationResponse.construct(
    url_to_classify=url_to_classify,
    domain_data=domain_data,
    llm_response=llm_response
  )

