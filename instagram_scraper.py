from __future__ import annotations

import os
import time
from typing import List, Optional, Set, Tuple

from playwright.sync_api import (
	Playwright,
	sync_playwright,
	TimeoutError as PlaywrightTimeoutError,
)

from config import (
	INSTAGRAM_PASSWORD,
	INSTAGRAM_USERNAME,
	MAX_LIKES_PER_POST,
	NAVIGATION_TIMEOUT_MS,
	NUM_POSTS,
	PLAYWRIGHT_SLOW_MO_MS,
	SELECTOR_TIMEOUT_MS,
	TARGET_ACCOUNT_HANDLE,
	TARGET_ACCOUNT_QUERY,
	WORKSHEET_NAME,
	GAS_WEBAPP_URL,
	AUTH_STORAGE_PATH,
)
from apps_script_client import append_rows_via_gas
import re
from typing import Pattern


def wait_and_click(page, selector: str, timeout: int = SELECTOR_TIMEOUT_MS) -> bool:
	try:
		page.wait_for_selector(selector, timeout=timeout, state="visible")
		page.click(selector, timeout=timeout)
		return True
	except PlaywrightTimeoutError:
		return False


def element_is_present(page, selector: str, timeout: int = 2_000) -> bool:
	try:
		page.wait_for_selector(selector, timeout=timeout)
		return True
	except PlaywrightTimeoutError:
		return False


def login_if_needed(page) -> None:
	# If already logged in, Instagram will redirect to home
	page.goto("https://www.instagram.com/", timeout=NAVIGATION_TIMEOUT_MS)
	page.wait_for_load_state("domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)

	# Accept cookies if prompted
	# Use short timeouts to avoid long initial delays when banners are absent
	wait_and_click(page, 'button:has-text("Allow all cookies")', timeout=2_000) \
		or wait_and_click(page, 'button:has-text("Allow essential cookies")', timeout=2_000) \
		or wait_and_click(page, 'button:has-text("Accept")', timeout=2_000)

	# Check for login form
	if not element_is_present(page, 'input[name="username"]', timeout=2_000):
		# Likely already logged in
		return

	if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
		raise RuntimeError("INSTAGRAM_USERNAME/INSTAGRAM_PASSWORD must be set in config.py for automated login.")

	page.fill('input[name="username"]', INSTAGRAM_USERNAME, timeout=SELECTOR_TIMEOUT_MS)
	page.fill('input[name="password"]', INSTAGRAM_PASSWORD, timeout=SELECTOR_TIMEOUT_MS)
	wait_and_click(page, 'button[type="submit"]')

	# Wait for potential login challenges/2FA; user can complete in the visible browser
	# Wait for URL to change away from login (without forcing a navigation)
	try:
		page.wait_for_url(re.compile(r"instagram\.com/(?!accounts/login)"), timeout=NAVIGATION_TIMEOUT_MS)
	except Exception:
		pass
	# Relax to domcontentloaded to avoid long idle waits
	page.wait_for_load_state("domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)

	# Dismiss "Save Your Login Info?" if present
	wait_and_click(page, 'button:has-text("Not now")', timeout=2_000)
	# Dismiss "Turn on Notifications" if present
	wait_and_click(page, 'button:has-text("Not Now")', timeout=2_000) or wait_and_click(page, 'div[role="dialog"] button:has-text("Not Now")', timeout=2_000)


def save_storage_state(context) -> None:
	try:
		context.storage_state(path=AUTH_STORAGE_PATH)
	except Exception:
		pass


def create_browser_context(playwright: Playwright):
	browser = playwright.chromium.launch(headless=False, slow_mo=PLAYWRIGHT_SLOW_MO_MS)
	context_args = {}
	if os.path.exists(AUTH_STORAGE_PATH):
		context_args["storage_state"] = AUTH_STORAGE_PATH
	context = browser.new_context(**context_args)
	# Make selectors faster/more consistent
	try:
		context.set_default_timeout(SELECTOR_TIMEOUT_MS)
		context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
	except Exception:
		pass
	return browser, context


def try_open_search(page) -> bool:
	# Several possible entry points to the search UI depending on layout
	# Prefer role-based targeting first (more resilient)
	try:
		page.get_by_role("link", name="Search").click(timeout=6_000)
		return True
	except Exception:
		pass

	return (
		wait_and_click(page, 'a[href="/explore/search/"]')
		or wait_and_click(page, 'svg[aria-label="Search"]')
		or wait_and_click(page, 'input[placeholder="Search"]')
		or wait_and_click(page, 'input[aria-label*="Search"]')
	)


def search_and_open_account(page, query_text: str, expected_handle: str) -> bool:
	page.goto("https://www.instagram.com/", timeout=NAVIGATION_TIMEOUT_MS)
	page.wait_for_load_state("domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)

	opened = try_open_search(page)
	if not opened:
		return False

	# Focus the search input robustly
	input_candidates = [
		'input[placeholder="Search"]',
		'input[aria-label*="Search"]',
		'input[type="search"]',
		'input[type="text"]',
	]
	for sel in input_candidates:
		if element_is_present(page, sel, timeout=2_000):
			try:
				page.fill(sel, "")
				page.fill(sel, query_text, timeout=SELECTOR_TIMEOUT_MS)
				break
			except Exception:
				continue
	else:
		# Fallback to simply typing if focus is already in the box
		page.keyboard.type(query_text, delay=30)

	time.sleep(1.0)

	# Try to click result whose href ends with expected handle
	# New search results often render anchors with profile URLs
	candidate_selectors = [
		f'a[href$="/{expected_handle}/"]',
		f'a[href*="/{expected_handle}/"]',
		# Fallback: any link that contains the handle text
		f'a:has-text("{expected_handle}")',
	]
	for sel in candidate_selectors:
		if wait_and_click(page, sel):
			page.wait_for_load_state("networkidle", timeout=NAVIGATION_TIMEOUT_MS)
			return True

	return False


def navigate_to_account(page, handle: str, query_text: str) -> None:
	# Prefer visible search for the user's visibility request
	if search_and_open_account(page, query_text=query_text, expected_handle=handle):
		return

	# Fallback: direct navigation
	page.goto(f"https://www.instagram.com/{handle}/", timeout=NAVIGATION_TIMEOUT_MS)
	page.wait_for_load_state("domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)


def get_recent_post_urls_from_profile(page, limit: int) -> List[str]:
	# Wait for profile to render; then collect anchors to posts (photos/reels).
	page.wait_for_load_state("domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
	
	# Prefer directly finding anchors without assuming an article wrapper
	anchors = page.query_selector_all('a[href*="/p/"], a[href*="/reel/"]')
	if not anchors:
		# Try a quick scroll to trigger lazy load then re-query
		try:
			page.mouse.wheel(0, 1200)
			time.sleep(0.8)
			anchors = page.query_selector_all('a[href*="/p/"], a[href*="/reel/"]')
		except Exception:
			pass

	post_urls: List[str] = []
	seen: Set[str] = set()
	for a in anchors:
		href = a.get_attribute("href") or ""
		if not href:
			continue
		if href.startswith("/"):
			href = "https://www.instagram.com" + href
		if href in seen:
			continue
		seen.add(href)
		post_urls.append(href)
		if len(post_urls) >= limit:
			break
	return post_urls


def open_likers_list(page) -> bool:
	"""
	Deprecated in this flow: we now prefer navigating directly to /liked_by/.
	Kept for potential future fallback.
	"""
	selector_candidates = [
		'a[href$="/liked_by/"]',
		'div[role="dialog"] a[href$="/liked_by/"]',
		'div[role="dialog"] div a:has-text(" likes")',
		'section a:has-text(" likes")',
		'button:has-text(" likes")',
		'section a span:has-text(" likes")',
		'div[role="button"]:has-text(" likes")',
		'button[aria-label*="likes"]',
	]
	for sel in selector_candidates:
		if wait_and_click(page, sel):
			return True
	return False


def extract_usernames_from_likers_dialog(page, max_users: int) -> List[str]:
	"""
	Scroll the likers dialog and collect usernames.
	Tries to detect the scrollable container inside the dialog.
	"""
	usernames: List[str] = []
	seen: Set[str] = set()

	# Identify the dialog root
	if not element_is_present(page, 'div[role="dialog"]', timeout=SELECTOR_TIMEOUT_MS):
		return usernames

	# The scrollable container can vary; try common patterns
	scroll_container_selectors = [
		'div[role="dialog"] div[style*="overflow"]',
		'div[role="dialog"] ul',
		'div[role="dialog"] div[role="dialog"]',  # nested
	]

	scroll_container = None
	for sel in scroll_container_selectors:
		try:
			scroll_container = page.query_selector(sel)
			if scroll_container:
				break
		except Exception:
			continue

	# Fallback to the dialog itself if none found
	if scroll_container is None:
		scroll_container = page.query_selector('div[role="dialog"]')

	# Helper to read currently rendered usernames
	def read_visible_usernames() -> List[str]:
		# User rows often contain anchors to profile pages with the username as text
		anchors = page.query_selector_all('div[role="dialog"] a[href*="/"]:not([href*="/p/"]):not([href*="/reel/"])')
		found: List[str] = []
		for a in anchors:
			href = a.get_attribute("href") or ""
			if not href.startswith("/"):
				continue
			# Heuristic: profile links are like "/username/"
			parts = href.strip("/").split("/")
			if len(parts) == 1 and parts[0]:
				text = (a.inner_text() or "").strip()
				# Prefer the href-derived username
				username = parts[0]
				if username and username not in found:
					found.append(username)
		return found

	# Scroll loop
	last_height = -1
	stable_rounds = 0

	while len(usernames) < max_users and stable_rounds < 4:
		for u in read_visible_usernames():
			if u not in seen:
				seen.add(u)
				usernames.append(u)
				if len(usernames) >= max_users:
					break

		# Scroll down a bit
		try:
			page.evaluate("(el) => el.scrollBy(0, el.clientHeight)", scroll_container)
		except Exception:
			# Fallback: page scroll
			page.mouse.wheel(0, 1000)

		time.sleep(0.8)

		# Detect if we are no longer loading new content
		try:
			current_height = page.evaluate("(el) => el.scrollHeight", scroll_container)
		except Exception:
			current_height = last_height

		if current_height == last_height:
			stable_rounds += 1
		else:
			stable_rounds = 0
			last_height = current_height

	return usernames


def extract_usernames_from_liked_by_page(page, max_users: int) -> List[str]:
	"""
	Fallback method: if we can navigate to a /liked_by/ page, scroll and collect.
	"""
	usernames: List[str] = []
	seen: Set[str] = set()

	username_re = re.compile(r"^[A-Za-z0-9._]{1,30}$")
	denylist = {name for name in [INSTAGRAM_USERNAME.lower() if INSTAGRAM_USERNAME else "", "ABOUT", "HELP", "PRESS", "API", "JOBS", "PRIVACY", "TERMS", "LOCATIONS", "META VERIFIED", "Home", "Search", "Explore", "Reels", "Messages", "Notifications", "Create", "Profile", "More", "Also from Meta"] if name}

	def read_on_page() -> List[str]:
		results: List[str] = []

		# Read only anchors that point to profile roots: "/username/"
		anchors = page.query_selector_all('a[href^="/"]:not([href*="/p/"]):not([href*="/reel/"]):not([href^="/explore/"]):not([href^="/reels/"])')
		for a in anchors:
			href = a.get_attribute("href") or ""
			parts = href.strip("/").split("/")
			# Only accept hrefs that are exactly one segment like "/d.a.v.i.d._2.3/"
			if len(parts) == 1 and parts[0] and username_re.match(parts[0]):
				username = parts[0]
				if username.lower() in denylist:
					continue
				if username not in results:
					results.append(username)

		return results

	last_total = -1
	stable_rounds = 0
	while len(usernames) < max_users and stable_rounds < 4:
		for u in read_on_page():
			if u not in seen:
				seen.add(u)
				usernames.append(u)
				if len(usernames) >= max_users:
					break
		page.mouse.wheel(0, 1500)
		time.sleep(1.0)
		if len(usernames) == last_total:
			stable_rounds += 1
		else:
			stable_rounds = 0
			last_total = len(usernames)

	return usernames


def extract_post_shortcode(url: str) -> str:
	"""
	Extract shortcode from an Instagram post/reel URL.
	Supports URLs with or without a username segment, e.g.:
	- https://www.instagram.com/p/SHORTCODE/
	- https://www.instagram.com/reel/SHORTCODE/
	- https://www.instagram.com/<user>/p/SHORTCODE/
	- https://www.instagram.com/<user>/reel/SHORTCODE/
	"""
	# Strict 11-char shortcode first
	m = re.search(r"/(?:p|reel)/([A-Za-z0-9_-]{11})(?:[/?#]|$)", url)
	if m:
		return m.group(1)
	# Looser fallback 5-20 chars if needed
	m2 = re.search(r"/(?:p|reel)/([A-Za-z0-9_-]{5,20})(?:[/?#]|$)", url)
	if m2:
		return m2.group(1)
	raise ValueError(f"Could not parse post shortcode from URL: {url}")


def navigate_to_liked_by_url(page, liked_by_url: str):
	"""
	Try to reach the liked_by page using multiple variants and strategies.
	Returns (active_page, success). The active_page can be a new tab.
	"""
	candidates = [liked_by_url]
	pattern = re.compile(r"/liked_by/?")

	for url in candidates:
		# Strategy A: direct goto
		try:
			page.goto(url, timeout=NAVIGATION_TIMEOUT_MS, wait_until="domcontentloaded")
			page.wait_for_url(pattern, timeout=NAVIGATION_TIMEOUT_MS)
			return page, True
		except PlaywrightTimeoutError:
			pass

		# Strategy B: window.location
		try:
			page.evaluate("(u) => { window.location.href = u; }", url)
			page.wait_for_url(pattern, timeout=NAVIGATION_TIMEOUT_MS)
			return page, True
		except PlaywrightTimeoutError:
			pass

		# Strategy C: open in a new tab
		try:
			new_page = page.context.new_page()
			new_page.goto(url, timeout=NAVIGATION_TIMEOUT_MS, wait_until="domcontentloaded")
			new_page.wait_for_url(pattern, timeout=NAVIGATION_TIMEOUT_MS)
			return new_page, True
		except PlaywrightTimeoutError:
			try:
				new_page.close()
			except Exception:
				pass
			continue

	return page, False


def try_collect_likers(page, post_url: str, max_users: int) -> List[str]:
	"""
	Deterministic approach per user request:
	1) Load the post URL explicitly
	2) Navigate to post_url + 'liked_by'
	3) Scroll and extract usernames using both anchor and class-based strategies
	"""
	try:
		# Ensure we are on the post page to resolve canonical URL, then go to liked_by
		page.goto(post_url, timeout=NAVIGATION_TIMEOUT_MS, wait_until="domcontentloaded")
		page.wait_for_load_state("domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)

		shortcode = extract_post_shortcode(page.url or post_url)
		liked_by_url = f"https://www.instagram.com/p/{shortcode}/liked_by"

		active_page, ok = navigate_to_liked_by_url(page, liked_by_url)
		if not ok:
			return []

		users = extract_usernames_from_liked_by_page(active_page, max_users=max_users)

		# Close temp page if we opened a new tab
		if active_page is not page:
			try:
				active_page.close()
			except Exception:
				pass

		return users
	except PlaywrightTimeoutError:
		return []


def main() -> None:
	if not GAS_WEBAPP_URL:
		raise RuntimeError("GAS_WEBAPP_URL must be set in config.py to write results to Google Sheets via Apps Script.")

	with sync_playwright() as p:
		browser, context = create_browser_context(p)
		page = context.new_page()

		try:
			# Login or reuse session
			login_if_needed(page)

			# Navigate to account (search UI preferred)
			navigate_to_account(page, handle=TARGET_ACCOUNT_HANDLE, query_text=TARGET_ACCOUNT_QUERY)

			# Collect recent post URLs
			post_urls = get_recent_post_urls_from_profile(page, limit=NUM_POSTS)
			if not post_urls:
				raise RuntimeError("No posts found on the profile grid.")

			total_appended = 0

			for idx, post_url in enumerate(post_urls, start=1):
				page.goto(post_url, timeout=NAVIGATION_TIMEOUT_MS)
				page.wait_for_load_state("domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)

				# Attempt to collect likers
				usernames = try_collect_likers(page, post_url=post_url, max_users=MAX_LIKES_PER_POST)
				if not usernames:
					print(f"[{idx}/{len(post_urls)}] No likers found or failed to read likers for: {post_url}")
					continue

				# Build rows: [timestamp_iso, account_handle, post_url, username]
				import datetime as dt
				timestamp = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
				rows = [[timestamp, TARGET_ACCOUNT_HANDLE, post_url, u] for u in usernames]

				# Append via Apps Script Web App
				added = append_rows_via_gas(GAS_WEBAPP_URL, WORKSHEET_NAME, rows)
				total_appended += added
				print(f"[{idx}/{len(post_urls)}] Appended {added} rows for: {post_url}")

			print(f"Done. Total rows appended: {total_appended}")

		finally:
			# Save session for next run
			save_storage_state(context)
			context.close()
			browser.close()


if __name__ == "__main__":
	main()


