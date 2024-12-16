# https://github.com/ChalkTalk/content-generation/blob/main/utilities.py#L228
import json
import logging
import os
import re
import json5
import traceback
from typing import Any, Dict, Generic, List, Optional, Set, Tuple, TypeVar, Union
from dataclasses import dataclass
from lxml import etree
from io import StringIO 
import sys
import numpy as np

from unidecode import unidecode

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))


from url_analyzer.classification.utilities.utilities import BaseModelWithWrite, Maybe
from url_analyzer.classification.browser_automation.datamodel import ActionRequest


def re_extract_dict_from_json_like_string(json_string: str, expected_arg_list: List[str]) -> Optional[Dict[str, str]]:
  """
  Use regex pattern matching to extract a json-formatted string into a dictionary.
  """
  # pattern r'"question":\s*"(.+?)",\s*"answer":\s*"(.+?)",\s*"process":\s*"(.+?)("\n}|",\n)'

  # Replace the `true`, `false`, and numeric values with string analogs so the regex matches them
  for argname in expected_arg_list:
    json_string = re.sub(r'"%s": (true|false)(,|((\n| |\t)*\}))' % argname, r'"%s": "\1"\2' % argname, json_string)
    json_string = re.sub(r'"%s": (\d+\.\d+)(,|((\n| |\t)*}}))' % argname, r'"%s": "\1"\2\3' % argname, json_string)
    json_string = re.sub(r'"%s": (\d+)(,|((\n| |\t)*}}))' % argname, r'"%s": "\1"\2\3' % argname, json_string)

  pattern = ""
  for arg in expected_arg_list[:-1]:
    pattern += f'"{arg}":\s*"(.+?)",\s*'
  # pattern += f'"{expected_arg_list[-1]}":\s*"(.+?)",?(\n| |\t)*}}'
  pattern += f'"{expected_arg_list[-1]}":\s*("|\[)(.+?)("|\]),?(\n| |\t)*}}'
  print(pattern)
  matches = re.findall(pattern, json_string, re.DOTALL)
  if matches:
    result = {
      arg: m for arg, m in zip(expected_arg_list, matches[0])
    }
  else:
    result = None
  return result


def load_json_with_fallbacks(
  json_string: str,
  expected_arg_list: List[str],
  use_backslash_not_doubled_heuristic: bool = True
) -> Optional[Dict[str, Any]]:
  """
  GPT is inconsistent with how it handles backslashes. Sometimes it doubles up all backslashes, and sometimes it doesn't. Applying json.loads acts as a backslash compressor since it interprets backslashes as escape characters. All double backslashes get compressed to single backslashes when this gets applied.
  
  Therefore, we want to apply json5.loads when GPT has applied double backslashes and manual regex extraction when GPT has applied single backslashes.
  """
  print("load_json_with_fallbacks called with", json_string)


  # First, we try loading with regex-based re-extraction and testing if LaTeX compilation succeeds. If it does, then we can stop. If it doesn't, then we proceed to the heuristics below
  loaded_dict = None

  if use_backslash_not_doubled_heuristic:
    # Use a heuristic to check if the json string contains any escaped characters that would be removed by json.loads. Note that we do not flag on \$ or \% alone,
    backslashes_not_doubled_patterns = [
      r'(?<!\\)\\(hline|cdots|ldots|cdots|dots|times|div|geq|leq)',
      r'\$\\begin{',
      r'(\$|\(|\-|\[|\=|\{)+( )*\\(frac|left|pm|sqrt|cdot|dot)( )*{',
      # open parens and close parens
      r'(?<!\\)\\\((.*?)(?<!\\)\\\)',
      r'(?<!\\)\\\[(.*?)(?<!\\)\\\]'
    ]
    backslashes_not_doubled_heuristic = any(re.search(pattern, json_string) is not None for pattern in backslashes_not_doubled_patterns)
    
    if backslashes_not_doubled_heuristic:
      loaded_dict = re_extract_dict_from_json_like_string(
        json_string=json_string, expected_arg_list=expected_arg_list)
    
  if loaded_dict is None:
    try:
      # NOTE: Json loading will sometimes interpret single backslashes as incorrectly escaped characters
      loaded_dict = json5.loads(json_string)
    except Exception as e:
      # Fallback on json loads within the assumption that backslashes are doubled is to stripping down the double backslashes manually and then using the regex directly
      modified_json_string = json_string.replace("\\\\", "\\") # TODO: If this becomes problematic switch to applying this as a latex compilation fix
      loaded_dict = re_extract_dict_from_json_like_string(
        json_string=modified_json_string, expected_arg_list=expected_arg_list)

  return loaded_dict


def load_json_safe(
  json_string: str,
  expected_arg_list: Optional[List[str]] = None
) -> Optional[Dict[str, Any]]:
  if expected_arg_list is None:
    try:
      json_dict = json5.loads(json_string)
    except Exception as e:
      json_dict = None
  else:
    json_dict = load_json_with_fallbacks(
      json_string=json_string,
      expected_arg_list=expected_arg_list
    )
  return json_dict



def find_matching_pairs(string: str) -> List[Tuple[int, int, Any]]:
  """
  Given a string, returns a list of tuples of the form (opening_index, closing_index, [nested pairs])
  """
  def find_pairs_recursive(substring, start_index):
    pairs = []
    stack = []
    for i, char in enumerate(substring):
      if char == '{':
        stack.append(i)
      elif char == '}':
        if stack:
          opening_index = stack.pop()
          pairs.append((opening_index + start_index, i + start_index, find_pairs_recursive(substring[opening_index + 1:i], opening_index + start_index + 1)))
    return pairs
  return find_pairs_recursive(string, 0)


def find_json_string(
  string_with_json: str,
  expected_arg_list: Optional[List[str]] = None
) -> Maybe[Dict[str, Any]]:
  """
  Find the json string in a body of text that has the expected arguments. If there are multiple json strings, return the last one.
  """
  assert type(string_with_json) == str
  pairs = find_matching_pairs(string_with_json)
  out = Maybe(content=None, error=None)
  for p in reversed(pairs):
    json_string = string_with_json[p[0]:p[1] + 1]
    parsed = load_json_safe(json_string=json_string, expected_arg_list=expected_arg_list)
    if parsed is not None:
      out.content = parsed
      break
  else:
    out.error = "parse_json_safe failed!"
  return out



def load_function_call(
  raw_llm_response: str,
  argument_name: str
) -> Maybe[Dict[str, Any]]:
  """
  Given a raw LLM response, extract the json string corresponding to the function call and return it as a dictionary.
  """
  # First convert the overall response into a dictionary
  maybe_formatted_response = find_json_string(string_with_json=raw_llm_response)
  if maybe_formatted_response.content is not None and argument_name in maybe_formatted_response.content:

    # Then extract the json string corresponding to the function call
    maybe_formatted_response = find_json_string(string_with_json=maybe_formatted_response.content[argument_name])
  return maybe_formatted_response