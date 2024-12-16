import os

CONFIG_ROOT_PATH = os.path.join(os.path.dirname(__file__), "../../configs")
WEBHOSTING_DOMAINS_FILE_LOCAL_PATH = os.path.join(CONFIG_ROOT_PATH, "webhosting_domains.txt")


DOMAIN_RANK_MAGNITUDES = [1000, 10000, 100000, 1000000]
TOP_DOMAINS_FILE_LOCAL_PATH_DICT = {
  k: os.path.join(CONFIG_ROOT_PATH, f"top_domains_{k}.txt")
  for k in DOMAIN_RANK_MAGNITUDES
}

class ConfigManager:

  def __init__(self):
    with open(WEBHOSTING_DOMAINS_FILE_LOCAL_PATH, "r") as f:
      self.webhosting_domains_set = set([line.strip() for line in f.readlines()])

    count_to_top_domains_set = {}
    for rank_magnitude, path in TOP_DOMAINS_FILE_LOCAL_PATH_DICT.items():
      with open(path, "r") as f:
        count_to_top_domains_set[rank_magnitude] = set([line.strip() for line in f.readlines()])
    
    # Map from domain_name to the order of magnitude of its domain rank
    self.domain_to_rank_magnitude = {}
    for rank_magnitude in DOMAIN_RANK_MAGNITUDES:
      for domain in count_to_top_domains_set[rank_magnitude]:
        # We iterate through the rank magnitudes from smaller to larger, so we don't overwrite a 10k magnitude with a 100k magnitude
        if domain not in self.domain_to_rank_magnitude:
          self.domain_to_rank_magnitude[domain] = rank_magnitude