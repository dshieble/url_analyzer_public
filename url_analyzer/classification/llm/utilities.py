from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass
from bs4 import BeautifulSoup
from typing import List, Optional
from diff_match_patch import diff_match_patch
import tiktoken


# Function to compare HTML files and return the differences as a string

DEFAULT_ENCODER = tiktoken.encoding_for_model('gpt-3.5-turbo-0125')


def get_token_count_from_prompt(prompt: str) -> int:
  return len(DEFAULT_ENCODER.encode(str(prompt)))


def cutoff_string_at_token_count(string: str, max_token_count: Optional[int]) -> str:
  """
  Cutoff a string at a certain token count
  """
  encoded = DEFAULT_ENCODER.encode(string)
  if max_token_count is None or len(encoded) <= max_token_count:
    cutoff_string = string
  else:
    cutoff_string = DEFAULT_ENCODER.decode(encoded[:max_token_count]) + f"...[cutoff {len(encoded) - max_token_count} out of {len(encoded)} total tokens]"
  return str(cutoff_string)

def get_diff_string_from_html_strings(starting_html: str, ending_html: str, buffer: int = 0, max_token_count_per_section: Optional[int] = None) -> str:
  """"
  Given two html strings, return a string that describes the differences between them
  """
  if starting_html is None or ending_html is None:
    raise ValueError(f"Both starting_html and ending_html must be provided. starting_html: {starting_html}, ending_html: {ending_html}")
  dmp = diff_match_patch()
  # Compute the diff
  diffs = dmp.diff_main(starting_html, ending_html)
  dmp.diff_cleanupSemantic(diffs)

  # Format the diffs into a single string
  diff_string = ""
  for (op, text) in diffs:

    # diff_string_segment will be the empty string on unchanged segments
    diff_string_segment = ""
    if buffer == 0:
      # If the buffer is 0, we just present the text
      if op == 1: # DIFF_INSERT
        diff_string_segment = f"Insert: {text}"
      elif op == -1: # DIFF_DELETE
        diff_string_segment = f"Delete: {text}"
    else:
      # If the buffer is not 0, we present the text with a buffer around it
      if op == 1: # DIFF_INSERT
        # Find the position of the insertion
        pos = ending_html.find(text)
        # Extract the surrounding context
        surrounding_context = ending_html[max(0, pos - buffer):pos + len(text) + buffer]
        diff_string_segment =f"Insert: {surrounding_context}"
      elif op == -1: # DIFF_DELETE
        # Find the position of the deletion
        pos = starting_html.find(text)
        # Extract the surrounding context
        surrounding_context = starting_html[max(0, pos - buffer):pos + len(text) + buffer]
        diff_string_segment = f"Delete: {surrounding_context}"

    # apply a cutoff on each section based on the token count
    diff_string_segment = cutoff_string_at_token_count(string=diff_string_segment, max_token_count=max_token_count_per_section) + "\n"
    diff_string += diff_string_segment
  return diff_string





class HTMLChunker:
  """
  This class enables chunking html documents with beautiful soup
  """
  def __init__(self, max_chunk_token_size: int, max_token_overlap: int = 0, encoder = DEFAULT_ENCODER):
    self.max_chunk_token_size = max_chunk_token_size
    self.max_token_overlap = max_token_overlap
    self.encoder = encoder

    self.chunks = []
    self.encoded_current_chunk = []
  
  def add_string_to_chunk(self, encoded_node_string: List[int]):
    assert len(encoded_node_string) <= self.max_chunk_token_size
    
    if len(self.encoded_current_chunk + encoded_node_string) <= self.max_chunk_token_size:
      self.encoded_current_chunk += encoded_node_string
    else:
      self.chunks.append(self.encoder.decode(self.encoded_current_chunk))
      self.encoded_current_chunk = encoded_node_string

  def traverse(self, node: "Node"):
    encoded_node_string = self.encoder.encode(str(node))

    if len(encoded_node_string) <= self.max_chunk_token_size:
      self.add_string_to_chunk(encoded_node_string=encoded_node_string)
    elif len(list(node.children)) == 1:

      # The step size will be smaller than the max_chunk_token_size if the max_token_overlap is greater than 0
      step_size = self.max_chunk_token_size - self.max_token_overlap
      for i in range(0, len(encoded_node_string), step_size):
        self.add_string_to_chunk(encoded_node_string=encoded_node_string[i:i + self.max_chunk_token_size])
    else:
      for child in node.children:
        self.traverse(node=child)


  def split_html(self, html: str):
    soup = BeautifulSoup(html, 'html.parser')
    self.chunks = []

    self.traverse(node=soup)
    if self.encoded_current_chunk:
      self.chunks.append(self.encoder.decode(self.encoded_current_chunk))

    return self.chunks

