import requests
import time
import random
from .driver import Driver, Resp
from bs4 import BeautifulSoup
import re


class RequestsDriver(Driver):
    def __init__(self, timeout=30, max_retries=3, **kwargs):
        self._timeout = timeout
        self._max_retries = max_retries
        self.session = requests.Session()
        # Set modern browser headers to avoid bot detection
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        })

    def download_raw(self, filename, url: str):
        # Add delay to avoid aggressive scraping detection
        time.sleep(random.uniform(1.5, 3.0))

        # Retry mechanism for handling temporary failures
        for attempt in range(self._max_retries):
            try:
                response = self.session.get(url, stream=True, timeout=self._timeout)
                response.raise_for_status()  # Raise an exception for HTTP errors
                break
            except requests.exceptions.RequestException as e:
                if attempt == self._max_retries - 1:
                    raise e
                # Exponential backoff for retries
                time.sleep(2 ** attempt + random.uniform(0, 1))

        content_type = response.headers.get("Content-Type", "").lower()

        if "text/html" in content_type:
            # Parse HTML and get the title safely
            soup = BeautifulSoup(response.text, 'html.parser')
            title = None
            if soup.title and soup.title.string:
                title = soup.title.string.strip()

            # Sanitize title for filename, fallback to original filename if no title
            if title:
                sanitized_title = re.sub(r'\s+', ' ', re.sub(r'[\\/:"*?<>|]+', ' ', title)).strip()
                filename = sanitized_title + '.html' if sanitized_title else filename.rstrip('.html') + '.html'
            else:
                filename = filename.rstrip('.html') + '.html'

            with open(filename, "w", encoding="utf-8") as file:
                file.write(response.text)
        else:
            with open(filename, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)

        return filename,Resp(
            html_content=response.text if "text/html" in content_type else None,
            is_html="text/html" in content_type,
            true_url=response.url,
        )

    def close(self):
        self.session.close()
