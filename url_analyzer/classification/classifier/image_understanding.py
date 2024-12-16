

import logging
from typing import Optional
from url_analyzer.classification.classifier.prompts import IMAGE_DESCRIPTION_PROMPT_TEMPLATE, IMAGE_DESCRIPTION_STRING_TEMPLATE
from url_analyzer.classification.llm.openai_interface import DEFAULT_VISION_MODEL_NAME, get_response_from_prompt_one_shot
from url_analyzer.classification.browser_automation.playwright_spider import VisitedUrl
from url_analyzer.classification.classifier.url_to_classify import UrlToClassify
from url_analyzer.classification.utilities.utilities import Maybe


async def get_image_summary(
  url: str,
  image_path: str,
  model_name: str = DEFAULT_VISION_MODEL_NAME
) -> Optional[str]:
  
  prompt = IMAGE_DESCRIPTION_PROMPT_TEMPLATE.format(url=url)
  llm_response = await get_response_from_prompt_one_shot(
    prompt=prompt,
    image_path=image_path,
    model_name=model_name
  )
  if llm_response.error is not None:
    print(f"[get_image_summary] Error getting image summary: {llm_response.error}")
  return llm_response.response

async def get_image_description_string_from_url_to_classify(
  url_to_classify: UrlToClassify,
  model_name: str = DEFAULT_VISION_MODEL_NAME
) -> Optional[str]:
  llm_written_screenshot_description = await get_image_summary(
    url=url_to_classify.url,
    image_path=url_to_classify.url_screenshot_response.screenshot_path,
    model_name=model_name
  )

  if llm_written_screenshot_description is not None:
    image_description_string = IMAGE_DESCRIPTION_STRING_TEMPLATE.format(
      llm_written_screenshot_description=llm_written_screenshot_description
    )
  else:
    logging.error(f"Could not generate an LLM image description for {url_to_classify.url}")
    image_description_string = None
  return image_description_string