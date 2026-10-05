# BTC Trading Analyzer

BTC 현재가, 확정 봉 차트, 다섯 시간대의 중장기 신호와 과거 유사 사례 기반 예측을 보는 가벼운 Streamlit 대시보드입니다. 실제 주문 기능은 없습니다.

## 인터넷에서 이용하기

공개 배포 진입점은 **`web_app.py`**입니다. [Streamlit 배포 안내](docs/deployment.md)에 따라 배포하면 휴대폰과 PC에서 같은 주소로 접속할 수 있습니다. 이용자의 Python 설치나 거래소 API 키는 필요하지 않습니다.

공개 웹 기본값은 **Binance · BTC/USDT · Live · 일봉 차트**입니다. 상단에서 **Binance BTC/USDT와 Upbit KRW-BTC의 현재가와 작은 가격 그래프**를 함께 봅니다. 분석은 선택한 거래소의 원래 통화를 사용하며 두 시장의 가격을 합치거나 원화로 환산하지 않습니다.

화면은 **시장 개요 / 기술 지표 / 다중 시간대 / 미래 예측** 네 탭입니다. 백테스트·전략 검증·몬테카를로·모의거래·신호 기록·설정 탭과 계좌/전략 설정, 일목 읽는 법 카드, 관찰용 가격 영역과 목표·손절선 표시를 제거했습니다. 앱은 별도 연구 전략이나 모의계좌·신호 기록 DB를 실행하지 않습니다. 기존 로컬 DB 파일은 보존합니다.

## 처음 실행하기

Python 3.11 이상을 설치합니다. 개발·검증 환경은 Python 3.12입니다. 터미널에서 프로젝트 폴더로 이동하세요.

### Windows PowerShell

```powershell
cd btc-trading-analyzer
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock
Copy-Item .env.example .env
.\.venv\Scripts\python -m streamlit run app.py
```

Python 3.12 대신 3.11을 설치했다면 첫 명령을 `py -3.11 -m venv .venv`로 바꿉니다. 가상환경을 활성화하지 않고도 위 명령으로 실행할 수 있습니다. 설치 오류가 있으면 64비트 Python을 사용하세요.

### macOS / Linux

```bash
cd btc-trading-analyzer
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cp .env.example .env
.venv/bin/python -m streamlit run app.py
```

`.venv`는 프로젝트 전용 라이브러리 공간입니다. `requirements.lock`은 전체 의존성의 정확한 버전을 고정하며, 설치 시 TLS 인증을 끄지 않습니다. SQLite는 Python 표준 라이브러리를 사용합니다. `.env`에는 DB 경로와 로그 수준만 설정하면 됩니다.

`uv`를 이미 사용한다면 다음 명령으로 동일하게 설치합니다.

```bash
uv pip sync requirements.lock --python .venv/bin/python
```

패키지 사양은 `pyproject.toml`에서 변경하고, 의존성을 의도적으로 갱신할 때만 다음을 실행합니다.

```bash
uv pip compile requirements-dev.in -o requirements.lock --python .venv/bin/python --python-version 3.11 --universal --no-emit-index-url
uv pip compile pyproject.toml -o requirements.txt --python .venv/bin/python --python-version 3.11 --universal --no-emit-index-url
```

## 대시보드 사용

1. 상단에서 분석 거래소와 데이터 모드를 선택합니다. 공개 웹은 Live, 로컬 `app.py`는 Demo가 기본입니다. Demo는 합성 자료임을 표시하고 외부 현재가 위젯을 연결하지 않습니다.
2. Live 상단은 **BTC·ETH·원/달러 환율·BTC 김치프리미엄** 네 카드입니다. Binance BTC/ETH는 최근 1시간 그래프와 24시간 변화율을 표시합니다. 환율은 고시 날짜/시각, 김프는 환산 자료의 수신 상태를 함께 표시합니다. 시각은 KST입니다.
3. **시장 개요**에서 중장기 매수·매도·관망 판단을 봅니다. 차트 시간대는 1시간·4시간·일봉·주봉·월봉이며 간편/상세 보기와 일목균형표·이동평균선·볼린저밴드를 선택합니다. 확정 봉 차트와 실시간 현재가는 구분합니다.
4. **기술 지표**는 시간대별 RSI·MACD·변동성, **다중 시간대**는 방향·비중·자료 충족 상태를 보여줍니다. 일목은 기본 9/26/52/26봉으로 계산하며 차트와 종합 판단에 계속 반영합니다.
5. **미래 예측**에서 1주·1개월·3개월·6개월 후의 예상 경로와 범위를 봅니다. 예측 차트의 주황색은 가장 닮은 과거 사례의 실제 경로를 현재 기준 종가에 맞춘 재현입니다. 유사도 순으로 사례를 바꿔 파란 예상선과 비교할 수 있습니다. 별도 과거 비교에서도 당시 이후 실제 결과를 확인합니다. 직접 설정과 전체 사례 겹치기도 지원합니다. [예측과 과거 유사성 설명](docs/historical-similarity.md)을 참고하세요.

종합 신호는 일봉·주봉·월봉 85%, 단기 봉 15%를 반영합니다. 가격 매력과 하락 진정을 별도로 평가해 단기 상승 전의 눌림목도 검토합니다. 데이터 부족·급락·지지 이탈은 매수를 보류합니다. 점수는 성공 확률이 아니며 예측은 미래 가격을 보장하지 않습니다. [종합 신호 설명](docs/composite-signals.md)에 계산 조건이 있습니다.

RSI·ADX·CMF는 예측 근거에서 확인할 수 있습니다. 실제 자료 검증에서 일관된 정확도 개선이 확인되지 않아 추가 지표를 기본 예상 가격의 가중치로 사용하지 않습니다.

## 실시간 연결과 갱신

- 브라우저가 Binance `data-stream.binance.vision`의 BTC/ETH와 김프 계산용 Upbit `api.upbit.com` BTC 공개 WebSocket을 구독합니다. 업비트 가격 카드는 표시하지 않습니다. 숫자와 Canvas 그래프만 최대 4회/초 갱신하며 틱 수신으로 Python 분석을 다시 실행하지 않습니다.
- 시작할 때 Binance BTC/ETH의 최근 60개 분봉을 공개 REST로 받습니다. 이후 현재 틱을 마지막 분의 점에 반영하며 최대 61개 점을 유지합니다. 최근 이력 조회가 실패해도 수신한 가격부터 선을 그립니다.
- BTC/ETH 분봉 요청이 실패하거나 제한되면 자동 재시도합니다. 최근 이력은 같은 브라우저 탭에 잠시 저장해 새로고침에서도 복원합니다. 캐시와 분봉 가격을 실시간 수신으로 표시하지 않습니다.
- WebSocket이 연결되지 않으면 같은 거래소 REST API로 Binance 10초·Upbit 11초 간격으로 조회하고 조회 주기를 표시합니다. 15초 이상 갱신되지 않은 값은 **수신 지연 · 마지막 가격**으로 표시합니다. 잘못된 가격·다른 시장·이전 시각 메시지는 반영하지 않습니다.
- 재연결 간격은 1초부터 최대 30초까지 늘어납니다. 숨긴 페이지는 연결을 해제하고 돌아오면 다시 구독합니다. 화면의 분석 탭 전환은 가격 연결을 유지합니다.
- 분석용 확정 봉은 60초마다 확인하며 이미 받은 봉과 계산을 재사용합니다. 수동 새로고침은 해당 시장 자료를 갱신합니다. 현재가 연결과 봉 수집이 독립적이므로 봉 API 오류가 현재가 위젯을 멈추지 않습니다.

원/달러 환율은 두나무의 은행 고시 조회를 우선하고, 실패하면 Frankfurter의 ECB 일별 자료를 사용합니다. 60초마다 조회해도 원자료가 실시간 외환 체결가는 아닙니다. 김프는 `(Upbit BTC/KRW ÷ (Binance BTC/USDT × Coinbase USDT/USD × USD/KRW) − 1) × 100`입니다. USDT를 1달러로 고정하지 않으며 수수료는 제외합니다. 코인·환율·환산 자료가 없거나 지연되면 새 계산을 보류하고 마지막 값은 회색으로 구분합니다.

Binance REST는 공식 시장 데이터 전용 `data-api.binance.vision`, Upbit REST는 `api.upbit.com`을 사용합니다. 네트워크·지역 제한이 있으면 해당 연결의 실제 오류/지연 상태를 표시합니다. Live 실패를 합성 데이터로 대체하지 않습니다. 서버의 분석 자료 연결과 방문자 브라우저의 현재가 연결은 각각 접근 가능해야 합니다.

## 테스트와 성능

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/smoke.py
.venv/bin/ruff check src tests app.py web_app.py checkout_bootstrap.py scripts
.venv/bin/python scripts/check_deployment.py
.venv/bin/python scripts/benchmark_ui.py --repeats 9
```

pytest와 배포 검사는 외부 인터넷 없이 계산·캐시 무효화·UI와 공개 진입점을 확인합니다. Playwright와 Chromium이 설치된 개발 환경에서는 `python scripts/check_live_widget.py`로 거래소 메시지 형식을 사용한 오프라인 브라우저 검사를 실행할 수 있습니다. `--app-url <실행 중인 Live 앱 주소>`를 추가하면 임베딩과 분석 탭 전환도 검사합니다. 실제 거래소 연결 성공을 대신하는 검사는 아닙니다.

반복 실행·초기 실행·차트 크기의 비교 조건과 결과는 [성능 기록](docs/performance.md)에 있습니다. 로컬 계산 시간이 실제 호스팅의 전체 접속 시간을 뜻하지는 않습니다.

## 기존 명령행 연구 도구

이전 연구·검증 모듈은 `btc_analyzer.cli`에 남아 있으며 웹 화면에서 호출하지 않습니다. CLI를 직접 실행한 경우에만 해당 연구 작업과 기록을 사용합니다. 기존 `data/` DB와 보고서는 삭제하지 않습니다.

## 문제 해결

- `ModuleNotFoundError` / `ImportError`: 공개 배포의 `main` / `web_app.py`와 설치 로그를 확인합니다. 새 체크아웃은 editable 설치 없이 실행되도록 검사합니다. 수정 반영 후에도 이전 오류가 남으면 Manage app → Reboot app을 사용하세요.
- `403 / 451 / ProxyError`: 해당 호스트의 네트워크·서비스 지역 제한을 확인합니다. 인증서 검증을 끄지 않습니다.
- 시세가 회색으로 표시됨: 마지막 수신 시각을 확인하세요. 연결이 회복되면 자동 갱신합니다. REST만 가능하면 10초 또는 11초 조회로 표시됩니다.
- 데이터 부족: 월봉 EMA200 등 실제 이력이 없는 지표를 채워 넣지 않습니다. 부족한 자료 때문에 신호나 예측을 보류할 수 있습니다.
- SQLite 오류: 기존 파일을 삭제하지 말고 쓰기 권한과 캐시 경로를 확인합니다. 공개 가격 캐시에는 OHLCV만 저장합니다.

`.env`, 키, DB와 로그를 공개 저장소에 올리지 마세요. 이 앱은 공개 데이터만 사용합니다. 작업 단계와 다음 실행의 시작 지점은 [PROGRESS.md](PROGRESS.md)에 기록합니다.
