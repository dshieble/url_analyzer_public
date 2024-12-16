import json
import unittest
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from url_analyzer.classification.html_understanding.html_minify import HTML_MINIFIER, MARKDOWN_CONVERTER

class TestMinifier(unittest.TestCase):


  def test_markdown_converter_1(self):
    html_input = """
    <html><body>
    <p>Your account has been compromised, please secure it now by <a href="http://fakeurl.com/secure">clicking here</a>.</p>
    <form action="http://fakeurl.com/submit"><input type="password"></form>
    <p>Contact support at support@fakeemail.com for more information.</p>
    <img src="http://fakeurl.com/warning.png">
    <p>This is an important security update regarding your account.</p>
    <p>Failure to act now could result in permanent loss of access to your account.</p>
    <a href="http://anotherfakeurl.com/recover">Recover your account</a>.
    </body></html>
    """
    result = json.dumps(MARKDOWN_CONVERTER.clean(html_input))

    # Check for multiple suspicious elements being captured
    self.assertIn("compromised, please secure it now", result)
    self.assertIn("http://fakeurl.com/secure", result)
    self.assertIn("support@fakeemail.com", result)
    self.assertIn("important security update", result)

  def test_markdown_converter_1(self):
    html_input = """
    <html><body><p>Please verify your account 
    <a href="http://phishing.com/login">here</a>.</p>
    <form action="http://phishing.com/submit">
    <input type="password"></form>
    <img src="http://phishing.com/image.png">
    <p>Contact: phishing@example.com</p></body></html>
    """
    result = json.dumps(MARKDOWN_CONVERTER.clean(html_input))
    # Check for multiple suspicious elements being captured
    self.assertIn("http://phishing.com/login", result)
    self.assertIn("phishing@example.com", result)


if __name__ == '__main__':
  unittest.main()
