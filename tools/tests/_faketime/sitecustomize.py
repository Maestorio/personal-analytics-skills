# Сдвиг «сегодня» во всех страницах Playwright — поиск тестов, зависящих от календаря (TST-DATE, docs/TODO.md).
# Не тест и не в реестре. Запуск:
#   PYTHONPATH=tools/tests/_faketime PW_FAKE_NOW=2027-01-15T12:00:00+03:00 python3 tools/run_tests.py --tier browser
# Зелёный сегодня и красный со сдвигом — тест зависит от даты: зафиксировать в нём pg.clock.set_fixed_time(...).
import os
FUT = os.environ.get("PW_FAKE_NOW")
if FUT:
    try:
        from playwright.sync_api._generated import Browser
        _nc, _np = Browser.new_context, Browser.new_page
        def new_context(self, *a, **k):
            ctx = _nc(self, *a, **k)
            try: ctx.clock.set_fixed_time(FUT)
            except Exception: pass
            return ctx
        def new_page(self, *a, **k):
            pg = _np(self, *a, **k)
            try: pg.clock.set_fixed_time(FUT)
            except Exception: pass
            return pg
        Browser.new_context, Browser.new_page = new_context, new_page
    except Exception:
        pass
