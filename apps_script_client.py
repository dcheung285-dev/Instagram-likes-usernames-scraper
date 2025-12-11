from __future__ import annotations

import json
from typing import List, Optional

import requests


def append_rows_via_gas(webapp_url: str, worksheet_name: str, rows: List[List[str]]) -> int:
	"""
	POST rows to a Google Apps Script Web App that appends data to a Sheet.
	Returns the number of rows appended as reported by the service.
	"""
	if not webapp_url:
		raise ValueError("GAS Web App URL is not set. Please set GAS_WEBAPP_URL in config.py.")

	payload = {
		"worksheetName": worksheet_name,
		"rows": rows,
	}

	resp = requests.post(webapp_url, json=payload, timeout=60)
	resp.raise_for_status()
	data = resp.json()

	if not isinstance(data, dict) or not data.get("ok"):
		raise RuntimeError(f"Apps Script responded with an error: {data}")

	return int(data.get("appended", 0))


