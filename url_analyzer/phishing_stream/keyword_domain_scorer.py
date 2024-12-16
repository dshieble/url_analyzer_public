# Inspired by https://github.com/x0rz/phishing_catcher
import math as math
import re
import tqdm
import yaml
import os
from Levenshtein import distance
from tld import get_tld

from confusables import normalize

CERTSTREAM_URL = 'wss://certstream.calidog.io'
CONFIG_ROOT_PATH = os.path.join(os.path.dirname(__file__), "../../configs")
SUSPICIOUS_DOMAIN_KEYWORDS_CONFIG_PATH = os.path.join(CONFIG_ROOT_PATH, "suspicious_domain_keywords.yaml")

pbar = tqdm.tqdm(desc='certificate_update', unit='cert')


def entropy(string):
  """Calculates the Shannon entropy of a string"""
  prob = [ float(string.count(c)) / len(string) for c in dict.fromkeys(list(string)) ]
  entropy = - sum([ p * math.log(p) / math.log(2.0) for p in prob ])
  return entropy

class KeywordDomainScorer:

  def __init__(self):
    with open(SUSPICIOUS_DOMAIN_KEYWORDS_CONFIG_PATH, 'r') as f:
      self.config = yaml.safe_load(f)
  
  def score_domain(self, domain: str) -> int:
    """Score `domain`.

    The highest score, the most probable `domain` is a phishing site.

    Args:
      domain (str): the domain to check.

    Returns:
      int: the score of `domain`.
    """
    score = 0
    for t in self.config['tlds']:
      if domain.endswith(t):
        score += 20

    # Remove initial '*.' for wildcard certificates bug
    if domain.startswith('*.'):
      domain = domain[2:]

    # Removing TLD to catch inner TLD in subdomain (ie. paypal.com.domain.com)
    try:
      res = get_tld(domain, as_object=True, fail_silently=True, fix_protocol=True)
      domain = '.'.join([res.subdomain, res.domain])
    except Exception:
      pass

    # Higer entropy is kind of suspicious
    score += int(round(entropy(domain)*10))

    # Remove lookalike characters using list from http://www.unicode.org/reports/tr39
    domain = normalize(domain)[0]

    words_in_domain = re.split("\W+", domain)

    # ie. detect fake .com (ie. *.com-account-management.info)
    if words_in_domain[0] in ['com', 'net', 'org']:
      score += 10

    # Testing keywords
    for word in self.config['keywords']:
      if word in domain:
        score += self.config['keywords'][word]

    # Testing Levenshtein distance for strong keywords (>= 70 points) (ie. paypol)
    for key in [k for (k,s) in self.config['keywords'].items() if s >= 70]:
      # Removing too generic keywords (ie. mail.domain.com)
      for word in [w for w in words_in_domain if w not in ['email', 'mail', 'cloud']]:
        if distance(str(word), str(key)) == 1:
          score += 70

    # Lots of '-' (ie. www.paypal-datacenter.com-acccount-alert.com)
    if 'xn--' not in domain and domain.count('-') >= 4:
      score += domain.count('-') * 3

    # Deeply nested subdomains (ie. www.paypal.com.security.accountupdate.gq)
    if domain.count('.') >= 3:
      score += domain.count('.') * 3


    return score
