import asyncio
import json
import unittest
import sys
import os


sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from url_analyzer.classification.classifier.classifier import BasicUrlClassifier

class TestEndToEnd(unittest.TestCase):

  def test_end_to_end_1(self):
    maybe_rich_classification_response = asyncio.run(BasicUrlClassifier().classify_url(
      url="https://danshiebler.com"
    ))
    assert maybe_rich_classification_response.content.url_classification.classification == "Benign"


  def test_end_to_end_2(self):
    maybe_rich_classification_response = asyncio.run(BasicUrlClassifier().classify_url(
      url="https://danshiebler.com/fake"
    ))
    assert maybe_rich_classification_response.content.url_classification.classification == "Inactive"

  def test_end_to_end_3(self):
    maybe_rich_classification_response = asyncio.run(BasicUrlClassifier().classify_url(
      url="fake"
    ))
    assert maybe_rich_classification_response.error is not None


if __name__ == '__main__':
  # python  tests/test_end_to_end.py
  unittest.main()
