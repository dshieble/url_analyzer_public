import base64
import json
import os

from dataclasses import dataclass
import traceback
import asyncio
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np
from openai import AsyncOpenAI, RateLimitError


from url_analyzer.classification.llm.constants import LLMResponse
from url_analyzer.classification.llm.utilities import get_token_count_from_prompt
from url_analyzer.classification.utilities.utilities import Maybe, json_dumps_safe


DEFAULT_SYSTEM_PROMPT = "You are an extremely powerful and helpful assistant. Please respond to the following prompt"
### Conversation Prompts ###
DEFAULT_REQUEST_TO_CHOOSE_FUNCTION_NAME_PROMPT = "Now please select the name of the function you would like to call"
DEFAULT_REQUEST_TO_GENERATE_FUNCTION_PROMPT = "Okay, please call one of the provided functions. Your answer must be the function you are calling in json format and nothing else."


DEFAULT_MODEL_NAME = "gpt-4o-mini"
BEST_MODEL_NAME = "gpt-4o"
DEFAULT_VISION_MODEL_NAME = "gpt-4o-mini"
# DEFAULT_VISION_MODEL_NAME = "gpt-4-vision-preview"

@dataclass
class LLMResponseWithHistory:
  """A response from LLM with the prompt and response history."""
  history: List[str]
  response: str


async def chat_complete_with_rate_limit_retry(client: Optional[AsyncOpenAI] = None, minimum_interval=10, maximum_interval=30, **kwargs) -> dict:
  """
  This function is a wrapper around openai.ChatCompletion.acreate that retries with a randomly chosen delay if we get a rate limit error
  """
  client = client or AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
  try:
    raw_response = await client.chat.completions.create(seed=0, **kwargs)
  except RateLimitError as e:
    print(f"EXCEPTION: {e}. Retrying...")
    # Sleep for a random interval between 5 seconds and 30 seconds
    await asyncio.sleep(minimum_interval + (maximum_interval - minimum_interval)*np.random.random())
    raw_response = await client.chat.completions.create(seed=0, **kwargs)
  return raw_response



class MessageManager:
  # A simple chat interface directly with openai
  def __init__(self, messages: List[Dict[str, str]]):
    assert os.environ["OPENAI_API_KEY"] is not None
    self.client =  AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    self.messages = messages


  def add_message(self, role: str, text_content: str, image_path: Optional[str] = None):
    if image_path is None:
      self.messages.append({"role": role, "content": text_content})
    else:
      with open(image_path, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode('utf-8')
      self.messages.append({"role": role, "content": [
        {
          "type": "text",
          "text": text_content
        },
        {
          "type": "image_url",
          "image_url": {
            "url": f"data:image/jpeg;base64,{base64_image}"
          },
        },
      ]
    })

  async def _get_raw_response(
    self,
    prompt: str,
    image_path: Optional[str] = None,
    temperature: float = 0,
    model_name: str = DEFAULT_MODEL_NAME,
    **kwargs
  ) -> Maybe[Dict[str, Any]]:
    self.add_message(role="user", text_content=prompt, image_path=image_path)


    prompt_to_print = prompt if image_path is None else f"{prompt} [{image_path}]"
    print(f"\n\n=====PROMPT [{get_token_count_from_prompt(prompt)} tokens]====\n\n{prompt_to_print}")
    if kwargs.get("tools") is not None:
      print(f"TOOLS: {json_dumps_safe(kwargs.get('tools'))}")

    try:
      raw_response = await chat_complete_with_rate_limit_retry(
        client=self.client,
        model=model_name,
        messages=self.messages,
        temperature=temperature,
        **kwargs)
    except Exception as e:
      error = traceback.format_exc()
      maybe_raw_response = Maybe(content=None, error=error)
      print(
        f"""ERROR Calling chat_complete_with_rate_limit_retry with
        --- messages ---
        messages: {json_dumps_safe(self.messages)}
        ---- kwargs ---
        kwargs: {json_dumps_safe(kwargs)}
        ---- error ---
        error: {error}
        -------------
        """
      )
    else:
      maybe_raw_response = Maybe(content=raw_response)

    return maybe_raw_response

  async def get_response(self, prompt: str, image_path: Optional[str] = None, model_name: str = DEFAULT_MODEL_NAME, temperature: float = 0, **kwargs) -> Maybe[str]:
    content = None
    maybe_raw_response = await self._get_raw_response(prompt=prompt, image_path=image_path, temperature=temperature, model_name=model_name, **kwargs)
    if maybe_raw_response.content is None:
      maybe_response = maybe_raw_response
    else:
      if maybe_raw_response.content.choices[0].message.content is not None:
        content = maybe_raw_response.content.choices[0].message.content
        self.add_message(role="assistant", text_content=str(content))
        maybe_response = Maybe(content=content, error=None)
      elif maybe_raw_response.content.choices[0].message.tool_calls is not None:
        content = {}
        for tool_call in maybe_raw_response.content.choices[0].message.tool_calls:
          function = tool_call.function
          content[function.name] = function.arguments
        self.add_message(role="assistant", text_content=str(content))
        maybe_response = Maybe(content=content, error=None)
      else:
        maybe_response = Maybe(content=None, error="No response from LLM")

    print(f"\n\n=====RESPONSE {maybe_response} [{None if maybe_response.content is None else get_token_count_from_prompt(str(maybe_response.content))} tokens] ====\n\n{content}")
    return maybe_response


async def get_response_from_prompt_one_shot(
  prompt: str,
  image_path: Optional[str] = None,
  temperature: float = 0,
  top_p: float = 1,
  model_name: str = DEFAULT_MODEL_NAME,
  system_prompt: str = DEFAULT_SYSTEM_PROMPT,
  **kwargs
) -> LLMResponse:
  if not isinstance(prompt, str):
    raise ValueError(f"Prompt must be a string, not {type(prompt)}")
  try:
    message_manager = MessageManager(
      messages=[
        {"role": "system", "content": system_prompt},
      ])

    maybe_response = await message_manager.get_response(
      prompt=prompt,
      image_path=image_path,
      model_name=model_name,
      temperature=temperature,
      top_p=top_p,
      **kwargs
    )
  
  except Exception as e:
    maybe_response = Maybe(content=None, error=f"START EXCEPTION\n-----\n{traceback.format_exc()}\n-----\nEND EXCEPTION")
  return LLMResponse(
    prompt=prompt,
    # The response should always be a string, even if the openai response is a dict
    response=str(maybe_response.content) if maybe_response.content is not None else None,
    error=maybe_response.error,
    prompt_tokens=get_token_count_from_prompt(prompt),
    messages_json_string=json.dumps(message_manager.messages)
  )



 
