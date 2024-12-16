from typing import Optional

from pydantic import BaseModel
from url_analyzer.domain_analysis.domain_classification import DomainClassificationResponse
from url_analyzer.domain_analysis.domain_lookup import DomainLookupResponse
from url_analyzer.classification.utilities.utilities import get_fqdn_from_url, get_rdn_from_fqdn


class DomainData(BaseModel):

  # The fully qualified domain name of the url
  fqdn: str

  # The registered domain name of the url
  rdn: str

  # True if the domain is a webhosting domain, such as pages.dev or github.io
  is_webhosting_domain: bool

  # A string that represents the popularity of the domain
  domain_rank_magnitude_string: str

  # The name of the registrant of the domain. This is often a placeholder
  registrant_name: Optional[str]

  # The name of the registrar of the domain
  registrar_name: Optional[str]

  # The date the domain expires
  expires: Optional[str]

  # The date the domain was last updated
  updated: Optional[str]

  # The date the domain was created
  created: Optional[str]

  @classmethod
  async def from_fqdn(cls, fqdn: str) -> "DomainData":
    domain_classification_response = DomainClassificationResponse.from_fqdn(fqdn=fqdn)
    domain_lookup_response = await DomainLookupResponse.from_fqdn(fqdn=fqdn)

    # Derived attribute that corresponds to whether this domain is a webhosting domain
    is_webhosting_domain = (
      domain_classification_response.is_webhosting_fqdn
      or domain_classification_response.has_webhosting_domain_parent
    )
    assert isinstance(is_webhosting_domain, bool)

    # Derived attribute that corresponds to how popular the domain is
    domain_rank_magnitude = None
    if domain_classification_response.domain_rank_magnitude is not None:
      domain_rank_magnitude = domain_classification_response.domain_rank_magnitude
    elif (
      domain_classification_response.best_parent_domain_rank_magnitude is not None
      and (domain_rank_magnitude is None or domain_classification_response.best_parent_domain_rank_magnitude < domain_rank_magnitude)
    ):
      domain_rank_magnitude = domain_classification_response.best_parent_domain_rank_magnitude

    domain_rank_magnitude_string = f"Within the top {domain_rank_magnitude} domains" if domain_rank_magnitude is not None else "Not in the top 1M domains"

    return cls(
      fqdn=fqdn,
      rdn=get_rdn_from_fqdn(fqdn=fqdn),
      is_webhosting_domain=is_webhosting_domain,
      domain_rank_magnitude_string=domain_rank_magnitude_string,
      registrant_name=domain_lookup_response.registrant_name,
      registrar_name=domain_lookup_response.registrar_name,
      expires=domain_lookup_response.expires,
      updated=domain_lookup_response.updated,
      created=domain_lookup_response.created
    )

  @classmethod
  async def from_url(cls, url: str) -> "DomainData":
    return await cls.from_fqdn(fqdn=get_fqdn_from_url(url=url))

