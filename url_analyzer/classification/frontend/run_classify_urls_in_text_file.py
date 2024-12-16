import argparse
import asyncio
import json
import os
import time
from typing import Any, Dict
import sys
import uuid

sys.path.append(os.path.join(os.path.join(os.path.dirname(__file__), '..'), '..'))

from url_analyzer.frontend.utilities import classify_urls_in_text_file

OUTPUT_ROOT_PATH = os.path.join(os.path.join(os.path.dirname(__file__), '..'), '..', 'outputs', 'scans')



async def main(args):
  log_file = os.path.join(OUTPUT_ROOT_PATH, f'{int(time.time())}_{str(uuid.uuid4())[:4]}.log')
  print(f"\n--------\nWriting to log file: {log_file}\n--------\n")

  # Classify the URLs in the text file using the classification service
  url_to_response_dict = await classify_urls_in_text_file(
    path_to_file_with_urls=args.path_to_file_with_urls,
    log_file=log_file,
    use_local=args.use_local
  )



# Usage example:
if __name__ == '__main__':
  """
  python url_analyzer/frontend/run_classify_urls_in_text_file.py \
    --path_to_file_with_urls /Users/danshiebler/workspace/personal/phishing/url_analyzer/data/test_attack_urls.txt

  python url_analyzer/frontend/run_classify_urls_in_text_file.py \
    --path_to_file_with_urls /Users/danshiebler/workspace/personal/phishing/url_analyzer/data/test_safe_urls.txt

  python url_analyzer/frontend/run_classify_urls_in_text_file.py \
    --path_to_file_with_urls /Users/danshiebler/workspace/personal/phishing/url_analyzer/data/test_safe_urls.txt \
    --use_local
  """
  parser = argparse.ArgumentParser()
  parser.add_argument("--path_to_file_with_urls", type=str, required=True)
  parser.add_argument("--use_local", action="store_true")
  args = parser.parse_args()

  asyncio.run(main(args=args))
    
