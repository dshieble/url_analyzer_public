from bs4 import BeautifulSoup
from typing import List, Set
import re


from bs4 import BeautifulSoup
import re

STRING_REGEX = r'"([^"]*)"|\'([^\']*)\''
TAG_LIST = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'li', 'span', 'strong', 'em', 'u', 's', 'div']

def extract_html_content_strings(html_page: str) -> Set[str]:
  # Create a BeautifulSoup object and specify the parser
  soup = BeautifulSoup(html_page, 'html.parser')

  # Find all tags that could contain strings, and extract their string content
  strings = []
  for tag in TAG_LIST:
    elements = soup.find_all(tag)
    for element in elements:
      if element.string:
        strings.append(element.string)

  # Extract all id and class attribute values
  ids = [element.get('id') for element in soup.find_all(id=True)]
  classes = [element.get('class') for element in soup.find_all(class_=True)]

  # Remove None values and flatten the list of classes
  ids = [i for i in ids if i]
  classes = [item for sublist in classes for item in sublist if item]

  # Combine all strings, ids, and classes into one list
  all_strings = strings + ids + classes

  return set([s.strip() for s in all_strings])

def extract_quoted_strings(html_string: str) -> Set[str]:
  quoted_string_tuples = re.findall(STRING_REGEX, html_string)
  all_strings = [''.join(quote) for quote in quoted_string_tuples]
  return set([s.strip() for s in all_strings])
                                  
def extract_strings(html_string: str) -> Set[str]:
  return set(extract_quoted_strings(html_string)).union(set(extract_html_content_strings(html_string)))
