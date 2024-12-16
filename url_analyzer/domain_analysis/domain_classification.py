"""
Options
  - https://github.com/pogzyb/whodap
"""

import dns.resolver
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set
from pydantic import BaseModel
from url_analyzer.domain_analysis.config_manager import ConfigManager

def get_parent_domains_of_fqdn(fqdn: str) -> List[str]:
  parts = fqdn.split('.')
  parent_domains = ['.'.join(parts[i:]) for i in range(len(parts))]
  return parent_domains



class DomainClassificationResponse(BaseModel):
  fqdn: str

  # The order of magnitude of the domain rank, or None if it is a low popularity unranked domain
  domain_rank_magnitude: Optional[int]
  best_parent_domain_rank_magnitude: Optional[int]

  # TODO: Break down webhosting and payload domains
  is_webhosting_fqdn: bool
  has_webhosting_domain_parent: bool

  @classmethod
  def from_fqdn(
    cls,
    fqdn: str,
    config_manager: Optional[ConfigManager] = None
  ) -> "DomainClassification":
    config_manager = config_manager if config_manager is not None else ConfigManager()
    parent_domains_list = get_parent_domains_of_fqdn(fqdn=fqdn)
    
    domain_rank_magnitude = config_manager.domain_to_rank_magnitude.get(fqdn)  
    best_parent_domain_rank_magnitude = None
    for parent_domain in parent_domains_list:
      parent_domain_rank_magnitude = config_manager.domain_to_rank_magnitude.get(parent_domain)
      if best_parent_domain_rank_magnitude is None:
        best_parent_domain_rank_magnitude = parent_domain_rank_magnitude
      elif parent_domain_rank_magnitude is not None and parent_domain_rank_magnitude < best_parent_domain_rank_magnitude:
        best_parent_domain_rank_magnitude = parent_domain_rank_magnitude

    is_webhosting_fqdn = fqdn in config_manager.webhosting_domains_set
    has_webhosting_domain_parent = any([parent_domain in config_manager.webhosting_domains_set for parent_domain in parent_domains_list])
    return cls(
      fqdn=fqdn,
      domain_rank_magnitude=domain_rank_magnitude,
      best_parent_domain_rank_magnitude=best_parent_domain_rank_magnitude,
      is_webhosting_fqdn=is_webhosting_fqdn,
      has_webhosting_domain_parent=has_webhosting_domain_parent
    )
  