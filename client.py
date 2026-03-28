#!/usr/bin/env python3
"""Robust client for submitting JSON data to a remote server with retries.

Requirements covered:
1) Create and save original JSON (original.json)
2) POST JSON data to server
3) Retry forever with delay when request fails
4) Log all attempts and errors to client.log
5) Save successful response as modified.json
6) Compare original vs modified and print differences
"""

from __future__ import annotations

import json
import logging
import mimetypes
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib import error, request


SERVER_URL = "https://student-server-production-528a.up.railway.app/submit-file"
ORIGINAL_JSON_PATH = Path("original.json")
MODIFIED_JSON_PATH = Path("modified.json")
LOG_FILE_PATH = Path("client.log")
RETRY_DELAY_SECONDS = 10
REQUEST_TIMEOUT_SECONDS = 15
SERVER_OPEN_HOUR = 9
SERVER_CLOSE_HOUR = 18


def configure_logger(log_path: Path) -> logging.Logger:
    """Configure and return a file logger for client activity."""
    logger = logging.getLogger("robust_client")
    logger.setLevel(logging.INFO)

    # Prevent duplicate handlers if script is run multiple times in one process.
    if not logger.handlers:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S"
        )
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def create_personal_info() -> Dict[str, Any]:
    """Create the required personal info dictionary."""
    return {
        "first_name": "Salih",
        "last_name": "Sefer",
        "age": 20,
        "interests": ["Cybersecurity", "Python", "Penetration Testing"],
    }


def save_json(data: Dict[str, Any], path: Path) -> None:
    """Write dictionary data to disk as pretty JSON."""
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)


def load_json(path: Path) -> Dict[str, Any]:
    """Load and return JSON object from a file."""
    with path.open("r", encoding="utf-8") as file:
        loaded = json.load(file)

    if not isinstance(loaded, dict):
        raise ValueError(f"Expected a JSON object in {path}, got {type(loaded).__name__}")

    return loaded


def build_multipart_body(field_name: str, file_path: Path) -> Tuple[bytes, str]:
    """Build a multipart/form-data body for a single file field."""
    boundary = f"----PythonClientBoundary{uuid.uuid4().hex}"
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/json"

    with file_path.open("rb") as file:
        file_data = file.read()

    body_parts = [
        f"--{boundary}\r\n".encode("utf-8"),
        (
            f'Content-Disposition: form-data; name="{field_name}"; '
            f'filename="{file_path.name}"\r\n'
        ).encode("utf-8"),
        f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
        file_data,
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]

    return b"".join(body_parts), boundary


def post_json_file(url: str, json_path: Path) -> Tuple[int, bytes]:
    """Submit the JSON file using multipart/form-data and return status/body."""
    body, boundary = build_multipart_body("file", json_path)
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.getcode(), response.read()


def post_json_payload(url: str, payload: Dict[str, Any]) -> Tuple[int, bytes]:
    """Submit JSON directly as application/json payload and return status/body."""
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.getcode(), response.read()


def submit_with_retry(url: str, json_path: Path, logger: logging.Logger) -> Dict[str, Any]:
    """Retry submission forever until a valid JSON response is received."""
    attempt = 0

    while True:
        attempt += 1

        try:
            # Try file upload first, then JSON body as fallback for compatibility.
            status_code, response_body = post_json_file(url, json_path)
            if status_code < 200 or status_code >= 300:
                payload = load_json(json_path)
                status_code, response_body = post_json_payload(url, payload)

            try:
                response_data = json.loads(response_body.decode("utf-8"))
            except json.JSONDecodeError as err:
                logger.error(
                    "Attempt %d failed: response is not valid JSON (%s). Body: %s",
                    attempt,
                    err,
                    response_body.decode("utf-8", errors="replace")[:500],
                )
                print(
                    f"Attempt {attempt} failed: invalid JSON response. "
                    f"Retrying in {RETRY_DELAY_SECONDS} seconds..."
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue

            if not isinstance(response_data, dict):
                logger.error(
                    "Attempt %d failed: response JSON is not an object. Got: %s",
                    attempt,
                    type(response_data).__name__,
                )
                print(
                    f"Attempt {attempt} failed: response JSON is not an object. "
                    f"Retrying in {RETRY_DELAY_SECONDS} seconds..."
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue

            logger.info("Attempt %d succeeded with status code %d.", attempt, status_code)
            print(f"Attempt {attempt} succeeded (HTTP {status_code}).")
            return response_data

        except error.HTTPError as http_error:
            logger.error(
                "Attempt %d failed: HTTPError %s: %s",
                attempt,
                http_error.code,
                http_error,
            )
            print(
                f"Attempt {attempt} failed: HTTP error {http_error.code}. "
                f"Retrying in {RETRY_DELAY_SECONDS} seconds..."
            )
        except error.URLError as url_error:
            logger.error("Attempt %d failed: ConnectionError/URLError: %s", attempt, url_error)
            print(
                f"Attempt {attempt} failed: connection problem. "
                f"Retrying in {RETRY_DELAY_SECONDS} seconds..."
            )
        except socket.timeout as timeout_error:
            logger.error("Attempt %d failed: Timeout: %s", attempt, timeout_error)
            print(
                f"Attempt {attempt} failed: timeout. "
                f"Retrying in {RETRY_DELAY_SECONDS} seconds..."
            )
        except json.JSONDecodeError as err:
            logger.error("Attempt %d failed: local JSON parsing error: %s", attempt, err)
            print(
                f"Attempt {attempt} failed: local JSON parsing error. "
                f"Retrying in {RETRY_DELAY_SECONDS} seconds..."
            )
        except ValueError as err:
            logger.error("Attempt %d failed: ValueError: %s", attempt, err)
            print(
                f"Attempt {attempt} failed: value error. "
                f"Retrying in {RETRY_DELAY_SECONDS} seconds..."
            )
        except Exception as err:  
            logger.exception("Attempt %d failed with unexpected error: %s", attempt, err)
            print(
                f"Attempt {attempt} failed: unexpected error. "
                f"Retrying in {RETRY_DELAY_SECONDS} seconds..."
            )

        time.sleep(RETRY_DELAY_SECONDS)

def compare_json_objects(
    original_data: Dict[str, Any], modified_data: Dict[str, Any]
) -> Tuple[List[str], List[str], List[str]]:
    """Return lists describing added, modified, and unchanged top-level fields."""
    added_fields: List[str] = []
    modified_fields: List[str] = []
    unchanged_fields: List[str] = []

    original_keys = set(original_data.keys())
    modified_keys = set(modified_data.keys())

    for key in sorted(modified_keys - original_keys):
        added_fields.append(f"{key}: {modified_data[key]!r}")

    for key in sorted(original_keys & modified_keys):
        if original_data[key] == modified_data[key]:
            unchanged_fields.append(f"{key}: {original_data[key]!r}")
        else:
            modified_fields.append(
                f"{key}: {original_data[key]!r} -> {modified_data[key]!r}"
            )

    return added_fields, modified_fields, unchanged_fields


def print_difference_report(original_path: Path, modified_path: Path) -> None:
    """Read JSON files, compare them, and print a clear difference report."""
    try:
        original_data = load_json(original_path)
        modified_data = load_json(modified_path)
    except json.JSONDecodeError as error:
        print(f"Could not compare files due to JSON parsing error: {error}")
        return
    except ValueError as error:
        print(f"Could not compare files: {error}")
        return

    added_fields, modified_fields, unchanged_fields = compare_json_objects(
        original_data, modified_data
    )

    print("\n===== JSON Difference Analysis =====")

    print("\nNewly added fields:")
    if added_fields:
        for item in added_fields:
            print(f"- {item}")
    else:
        print("- None")

    print("\nModified values:")
    if modified_fields:
        for item in modified_fields:
            print(f"- {item}")
    else:
        print("- None")

    print("\nUnchanged fields:")
    if unchanged_fields:
        for item in unchanged_fields:
            print(f"- {item}")
    else:
        print("- None")


def main() -> None:
    """Run the full client workflow."""
    logger = configure_logger(LOG_FILE_PATH)
    logger.info("Client execution started.")

    personal_info = create_personal_info()
    save_json(personal_info, ORIGINAL_JSON_PATH)
    logger.info("Created and saved %s.", ORIGINAL_JSON_PATH)

    response_data = submit_with_retry(SERVER_URL, ORIGINAL_JSON_PATH, logger)

    save_json(response_data, MODIFIED_JSON_PATH)
    logger.info("Saved server response to %s.", MODIFIED_JSON_PATH)
    logger.info("Client execution completed successfully.")

    print(f"Server response saved to {MODIFIED_JSON_PATH}.")
    print_difference_report(ORIGINAL_JSON_PATH, MODIFIED_JSON_PATH)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nClient terminated by user (Ctrl+C). Exiting gracefully...")