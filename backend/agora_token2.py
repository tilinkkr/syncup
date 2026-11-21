"""Minimal Agora AccessToken2 ("007") builder for combined RTC + RTM tokens.

Faithful port of the RTC/RTM parts of Agora's official AccessToken2.py / RtcTokenBuilder2.build_token_with_rtm
(github.com/AgoraIO/Tools/tree/master/DynamicKey/AgoraDynamicKey/python3). Needed because ConvoAI with
`advanced_features.enable_rtm` requires the agent token to carry BOTH RTC and RTM privileges, and RTM 2.x clients
log in with 007 tokens. The legacy `agora_token_builder` package only emits 006 tokens.
"""
import base64
import hmac
import secrets
import struct
import time
import zlib
from hashlib import sha256

SERVICE_RTC, SERVICE_RTM = 1, 2
PRIV_JOIN, PRIV_PUB_AUDIO, PRIV_PUB_VIDEO, PRIV_PUB_DATA = 1, 2, 3, 4
PRIV_RTM_LOGIN = 1


def _u16(x: int) -> bytes:
    return struct.pack("<H", int(x))


def _u32(x: int) -> bytes:
    return struct.pack("<I", int(x))


def _str(b: bytes) -> bytes:
    return _u16(len(b)) + b


def _privileges(privs: dict[int, int]) -> bytes:
    return _u16(len(privs)) + b"".join(_u16(k) + _u32(v) for k, v in sorted(privs.items()))


def build_rtc_rtm_token(app_id: str, app_certificate: str, channel_name: str, account: str,
                        expire_seconds: int = 3600, issue_ts: int | None = None, salt: int | None = None) -> str:
    """Publisher RTC privileges on `channel_name` for user `account` + RTM login as `account`.
    `expire_seconds` is relative (seconds from now), as in the official builder."""
    issue_ts = issue_ts or int(time.time())
    salt = salt or secrets.SystemRandom().randint(1, 99999999)
    acct = account.encode()
    rtc_uid = b"" if account in ("", "0") else acct

    rtc = (_u16(SERVICE_RTC)
           + _privileges({PRIV_JOIN: expire_seconds, PRIV_PUB_AUDIO: expire_seconds,
                          PRIV_PUB_VIDEO: expire_seconds, PRIV_PUB_DATA: expire_seconds})
           + _str(channel_name.encode()) + _str(rtc_uid))
    rtm = _u16(SERVICE_RTM) + _privileges({PRIV_RTM_LOGIN: expire_seconds}) + _str(acct)

    signing_info = (_str(app_id.encode()) + _u32(issue_ts) + _u32(expire_seconds) + _u32(salt)
                    + _u16(2) + rtc + rtm)
    signing = hmac.new(_u32(issue_ts), app_certificate.encode(), sha256).digest()
    signing = hmac.new(_u32(salt), signing, sha256).digest()
    signature = hmac.new(signing, signing_info, sha256).digest()
    return "007" + base64.b64encode(zlib.compress(_str(signature) + signing_info)).decode()
