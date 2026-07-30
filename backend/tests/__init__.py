"""백엔드 테스트 패키지.

패키지로 만든 이유 — `test_schema.py`가 `tests.conftest`에서 공용 상수를
import한다. `__init__.py`가 없으면 그 import가 되지 않고, 상수를 두 곳에
복사해 둬야 한다.
"""
