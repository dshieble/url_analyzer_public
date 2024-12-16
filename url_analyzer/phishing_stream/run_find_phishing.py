# Inspired by https://github.com/x0rz/phishing_catcher
import argparse
import os
import ssl
import sys

import certifi
import certstream

sys.path.append(os.path.join(os.path.join(os.path.dirname(__file__), '..'), '..'))

from url_analyzer.phishing_stream.processor import Processor

CERTSTREAM_URL = 'wss://certstream.calidog.io'

if __name__ == '__main__':
  """
  python url_analyzer/phishing_stream/run_find_phishing.py
  """

  parser = argparse.ArgumentParser()
  parser.add_argument("--run_whois", action="store_true")

  args = parser.parse_args()

  sslopt = {"cert_reqs": ssl.CERT_REQUIRED, "ca_certs": certifi.where()}
  processor = Processor(run_whois=args.run_whois)
  certstream.listen_for_events(processor.callback, url=CERTSTREAM_URL, sslopt=sslopt)
