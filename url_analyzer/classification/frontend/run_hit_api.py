import argparse
import json
import os
import sys

sys.path.append(os.path.join(os.path.join(os.path.dirname(__file__), '..'), '..'))

from url_analyzer.frontend.utilities import UrlClassifierInterface



def main(args):
  url_classifier_interface = UrlClassifierInterface(use_local=args.use_local)  # Initialize the checker
  api_key = url_classifier_interface.get_api_key()  # Get the API key
  result = url_classifier_interface.check_url(args.target_url, api_key=api_key)  # Check the URL
  print(json.dumps(result, indent=2))
    


# Usage example:
if __name__ == '__main__':
  """
  python url_analyzer/frontend/run_hit_api.py --target_url=https://danshiebler.com --use_local

  python url_analyzer/frontend/run_hit_api.py --target_url=https://danshiebler.com --use_local

  """
  parser = argparse.ArgumentParser()
  parser.add_argument("--target_url", type=str, required=True)
  parser.add_argument("--use_local", action="store_true")
  args = parser.parse_args()

