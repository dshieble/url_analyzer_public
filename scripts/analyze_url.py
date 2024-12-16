

import argparse
import sys
import os
from playwright.async_api import async_playwright
import asyncio


sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from url_analyzer.classification.browser_automation.playwright_page_manager import PlaywrightPageManager, PlaywrightPageManagerContext
from url_analyzer.classification.browser_automation.playwright_spider import PlaywrightSpider
from url_analyzer.classification.browser_automation.utilities import ScreenshotType

async def main(args):

  playwright_spider = await PlaywrightSpider.construct(
    url_list=[args.target_url],
    included_fqdn_regex=(".*" if args.included_fqdn_regex is None else args.included_fqdn_regex),
    screenshot_type=args.screenshot_type
  )
  async with PlaywrightPageManagerContext(playwright_page_manager=(
    await PlaywrightPageManager.construct(headless=not args.not_headless)
  )) as playwright_page_manager:
    visited_url = await playwright_spider.get_visited_url(
      url=args.target_url,
      playwright_page_manager=playwright_page_manager
    )
    visited_url.write_to_directory(directory=playwright_spider.directory)



if __name__ == "__main__":
  """
  
  python scripts/analyze_url.py \
    --target_url=http://my.tomorrowland.com/
  
  python scripts/analyze_url.py \
    --target_url=http://5hpf7vz.nickleonardson.com/ \
    --not_headless
  """

  parser = argparse.ArgumentParser()
  parser.add_argument("--target_url", type=str, required=True)
  parser.add_argument("--included_fqdn_regex", type=str, default=None)
  parser.add_argument("--not_headless",  action="store_true")
  parser.add_argument("--screenshot_type", type=str, default=ScreenshotType.VIEWPORT_SCREENSHOT)


  args = parser.parse_args()

  asyncio.run(main(args=args))
  