from __future__ import annotations

import re
import uuid

from app.safety.conversation_scrubber import ConversationScrubber

# Golden corpus — benign strings typical of DVWA / Juice Shop HTTP responses.
# No real secrets; all strings < 200 chars.

_DVWA_LIKE_STRINGS = [
    "<html><body><h1>DVWA</h1></body></html>",
    '<form method="POST" action="/login.php">',
    '<input type="text" name="username" value="">',
    '<input type="password" name="password" value="">',
    "Welcome to Damn Vulnerable Web Application",
    "You have an error in your SQL syntax near 'ORDER BY'",
    "Warning: mysql_fetch_array() expects parameter 1",
    '{"status": "success", "message": "Login successful"}',
    '{"error": "Invalid credentials", "code": 401}',
    "GET /vulnerabilities/sqli/?id=1&Submit=Submit HTTP/1.1",
    "POST /login.php HTTP/1.1",
    "Cookie: PHPSESSID=abcdef1234567890; security=low",
    "Content-Type: application/x-www-form-urlencoded",
    "username=admin&password=password&Login=Login",
    "SELECT * FROM users WHERE user='admin' AND password='password'",
    "You have 1 result. First name: admin Last name: admin",
    '<img src="/hackable/uploads/shell.php" />',
    "File successfully uploaded!",
    "CSRF token mismatch. Please try again.",
    "The file you selected exceeds the maximum allowed file size.",
    "HTTP/1.1 200 OK",
    "Server: Apache/2.4.25 (Debian)",
    "X-Powered-By: PHP/7.0.30",
    "Content-Length: 1234",
    "Location: /index.php",
    "Referer: http://dvwa.local/login.php",
    "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept: text/html,application/xhtml+xml,application/xml;q=0.9",
    "Connection: keep-alive",
    "Transfer-Encoding: chunked",
]

_JUICE_SHOP_LIKE_STRINGS = [
    '{"id": 1, "name": "Apple Juice", "price": 1.99, "description": "The all-time classic."}',
    '{"id": 2, "name": "Orange Juice", "price": 2.99, "category": "Juice"}',
    '{"id": 3, "name": "Banana Juice", "price": 1.49, "category": "Juice"}',
    '{"status": "success", "data": {"token": "login-success"}}',
    "Set-Cookie: token=; Path=/; HttpOnly",
    "Authorization header name: Bearer",
    "Vue component: ProductListComponent",
    "Vue component: BasketItemComponent",
    "Vue component: UserProfileComponent",
    "Product category: Electronics",
    "Product category: Fruit Juice",
    "Search query: apple",
    "Search query: orange juice",
    "GET /api/Products HTTP/1.1",
    "GET /api/BasketItems HTTP/1.1",
    "POST /api/Users/login HTTP/1.1",
    '{"email": "user@juice-sh.op", "password": "secret"}',
    "HTTP/1.1 401 Unauthorized",
    "HTTP/1.1 403 Forbidden",
    "HTTP/1.1 404 Not Found",
    "Content-Type: application/json; charset=utf-8",
    "X-Content-Type-Options: nosniff",
    "X-Frame-Options: SAMEORIGIN",
    "Strict-Transport-Security: max-age=31536000",
    '{"message": "Invalid email or password."}',
    '{"message": "You successfully solved a challenge: Login Admin"}',
    "Route: /score-board",
    "Route: /about",
    "Route: /contact",
    "Juice Shop version 14.0.0",
]

_TOKEN_SPLIT = re.compile(r"[\s\W]+")


class TestL2EntropyFPR:
    def test_l2_fpr_under_one_percent(self):
        session_id = uuid.uuid4()
        scrubber = ConversationScrubber(
            session_id,
            l2_entropy_threshold=4.5,
            l4_bucket_capacity=10000,
            l4_refill_per_sec=0.0,
        )

        corpus = _DVWA_LIKE_STRINGS + _JUICE_SHOP_LIKE_STRINGS
        total_tokens = 0
        l2_hits = 0
        false_positive_samples: list[str] = []

        from app.safety.conversation_scrubber import _shannon_entropy

        for text in corpus:
            tokens = [t for t in _TOKEN_SPLIT.split(text) if t]
            total_tokens += len(tokens)

            # Fresh scrubber per string so bucket/hits don't compound
            fresh = ConversationScrubber(
                session_id,
                l2_entropy_threshold=4.5,
                l4_bucket_capacity=10000,
                l4_refill_per_sec=0.0,
            )
            result = fresh.scrub(text)

            l2_only = result.layer_hits["l2"]
            if l2_only > 0:
                l2_hits += l2_only
                for token in tokens:
                    if len(token) >= 20:
                        entropy = _shannon_entropy(token)
                        if entropy >= 4.5 and len(false_positive_samples) < 5:
                            false_positive_samples.append(token)

        fpr = l2_hits / total_tokens if total_tokens > 0 else 0.0

        assert fpr < 0.01, (
            f"L2 FPR={fpr:.4f} exceeds 1% threshold. "
            f"({l2_hits} hits / {total_tokens} tokens). "
            f"Sample false positives: {false_positive_samples[:5]}. "
            f"Suggestion: raise l2_entropy_threshold from 4.5 to 5.0."
        )

    def test_l2_threshold_is_configurable(self):
        sid = uuid.uuid4()
        corpus = _DVWA_LIKE_STRINGS + _JUICE_SHOP_LIKE_STRINGS

        hits_default = 0
        hits_high = 0

        for text in corpus:
            s_default = ConversationScrubber(sid, l2_entropy_threshold=4.5, l4_bucket_capacity=10000, l4_refill_per_sec=0.0)
            s_high = ConversationScrubber(sid, l2_entropy_threshold=6.0, l4_bucket_capacity=10000, l4_refill_per_sec=0.0)
            hits_default += s_default.scrub(text).layer_hits["l2"]
            hits_high += s_high.scrub(text).layer_hits["l2"]

        assert hits_high <= hits_default
