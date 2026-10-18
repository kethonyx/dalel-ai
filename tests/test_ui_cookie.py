import time
import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app import config, main


def req(cookie=None):
    return SimpleNamespace(cookies={main.UI_COOKIE: cookie} if cookie else {})


class UiCookie(unittest.TestCase):
    def test_key_still_works(self):
        main.require_key(req(), config.API_KEY)

    def test_no_key_no_cookie_401(self):
        with self.assertRaises(HTTPException):
            main.require_key(req(), None)

    def test_cookie_from_index_passes(self):
        main.require_key(req(main._ui_cookie_value()), None)

    def test_forged_and_expired_cookie_401(self):
        old = int(time.time()) - 10
        for bad in ["123.abc", "garbage", f"{old}." + "0" * 64]:
            with self.assertRaises(HTTPException):
                main.require_key(req(bad), None)

    def test_cookie_ignored_when_ui_closed(self):
        value, saved = main._ui_cookie_value(), config.UI_OPEN
        config.UI_OPEN = False
        try:
            with self.assertRaises(HTTPException):
                main.require_key(req(value), None)
        finally:
            config.UI_OPEN = saved


if __name__ == "__main__":
    unittest.main()
