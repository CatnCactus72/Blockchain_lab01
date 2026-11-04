"""
Định nghĩa các hằng số tách miền chữ ký (signing domains), nhãn băm (hash tags)
và các mã lý do từ chối liên quan đến mật mã cho Chat Chain.
"""

from __future__ import annotations

# ============================================================================
# Các miền chữ ký (Signing Domains) - dùng trong sign() và verify()
# ============================================================================
TX: str = "TX"
HEADER: str = "HEADER"
PROPOSAL: str = "PROPOSAL"
VOTE: str = "VOTE"

# Bí danh có tiền tố DOMAIN_ để thuận tiện khi import từ các module khác
DOMAIN_TX: str = TX
DOMAIN_HEADER: str = HEADER
DOMAIN_PROPOSAL: str = PROPOSAL
DOMAIN_VOTE: str = VOTE

# Danh sách cố định tất cả các domain dùng để ký (phục vụ kiểm tra WRONG_DOMAIN)
SIGNING_DOMAINS: tuple[str, ...] = (TX, HEADER, PROPOSAL, VOTE)
ALL_DOMAINS: tuple[str, ...] = SIGNING_DOMAINS

# ============================================================================
# Các nhãn chỉ dùng để băm (Hash Tags - không dùng để ký)
# ============================================================================
BLOCK: str = "BLOCK"
MSG: str = "MSG"
STATE: str = "STATE"
TXROOT: str = "TXROOT"
TXID: str = "TXID"
KEY: str = "KEY"
GENESIS: str = "GENESIS"

# Bí danh có tiền tố TAG_ để thuận tiện khi import
TAG_BLOCK: str = BLOCK
TAG_MSG: str = MSG
TAG_STATE: str = STATE
TAG_TXROOT: str = TXROOT
TAG_TXID: str = TXID
TAG_KEY: str = KEY
TAG_GENESIS: str = GENESIS

# Danh sách tất cả các nhãn hash
HASH_TAGS: tuple[str, ...] = (BLOCK, MSG, STATE, TXROOT, TXID, KEY, GENESIS)

# ============================================================================
# Các vai trò sinh khóa (Key Derivation Roles)
# ============================================================================
ROLE_VALIDATOR: str = "validator"
ROLE_USER: str = "user"
VALID_ROLES: tuple[str, ...] = (ROLE_VALIDATOR, ROLE_USER)

# ============================================================================
# Mã lý do từ chối ở tầng mật mã
# ============================================================================
BAD_SIGNATURE: str = "BAD_SIGNATURE"
WRONG_DOMAIN: str = "WRONG_DOMAIN"
WRONG_CHAIN: str = "WRONG_CHAIN"
