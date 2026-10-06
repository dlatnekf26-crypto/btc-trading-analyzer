# 무료 공개 웹 배포

이용자는 Python을 설치하지 않고 웹 주소로 접속합니다. **호스팅 계정에서 최초 배포를 완료해야 실제 공개 주소가 생깁니다.** Codex 환경 저장/게시만으로 인터넷 웹사이트가 배포되지는 않습니다.

## Streamlit Community Cloud

1. [Streamlit Community Cloud](https://share.streamlit.io/)에 본인의 GitHub 계정으로 로그인합니다. 저장소 접근 권한을 연결합니다. 비밀번호·인증 토큰을 채팅이나 소스 파일에 넣지 않습니다.
2. **Create app** / **New app**에서 다음을 입력합니다.

   | 항목 | 값 |
   |---|---|
   | Repository | `dlatnekf26-crypto/btc-trading-analyzer` |
   | Branch | `main` |
   | Main file path | `web_app.py` |
   | Python version · Advanced settings | `3.12` |

3. **Deploy**를 누릅니다. 빌드 후 서비스가 제공하는 `https://…streamlit.app` 주소를 휴대폰/PC에서 엽니다. 공유하려면 앱의 공개 접근 설정도 확인합니다.

`requirements.txt`에 런타임 라이브러리의 정확한 버전을 직접 나열합니다. 앱은 진입점 위치를 기준으로 `src/`를 읽으므로 프로젝트의 별도 editable 설치나 서버 작업 디렉터리에 의존하지 않습니다. 분석에는 거래소 API 키가 필요하지 않습니다. 자동 설치 실패 시 앱 로그에서 Python 버전과 설치 오류를 확인합니다. 저장소 파일이 GitHub의 `main`에 올라 있어야 배포할 수 있습니다.

## 이미 배포된 앱에 수정 반영하기

연결된 GitHub 브랜치의 변경 사항은 Community Cloud가 자동 반영합니다. 코드나 의존성 변경 후 빌드가 완료될 때까지 기다린 뒤 새로고침하세요. 같은 오류 화면이 계속되면 **Manage app → Reboot app**을 사용합니다. 새 앱을 만들 필요는 없습니다.

`ModuleNotFoundError`가 계속되면 Manage app의 로그에서 마지막 `No module named '…'`와 의존성 설치 오류를 확인합니다. 개발 환경과 같은 설치 상태라는 가정 없이 검증하려면 아래를 새 가상환경에서 실행합니다.

```bash
python -m pip install -r requirements.txt
python -I scripts/check_deployment.py
```

이 검사는 개발 전용 CCXT 응답 주입으로 Binance Live의 네 개 탭·다섯 시간대 차트·기간별 예측·과거 비교와 계좌 저장을 생성하지 않는 시작 경로를 확인합니다. 제품에는 Demo 선택이나 숨은 테스트 모드가 없습니다. CI에서도 개발 패키지 설치와 별개로 검증합니다.

`ImportError`가 `from btc_analyzer.candles import candle_boundary`에서 발생하면, 이전 버전의 Python 모듈이 서버 메모리에 남아 있는 경우를 확인합니다. 소스에 함수가 있어도 `sys.modules`의 이전 모듈에는 없을 수 있습니다. 현재 진입점은 프로젝트 코드의 내용과 로딩 경로를 확인하고 버전이 달라진 경우에만 자체 패키지·공개 계산 캐시를 갱신합니다. 같은 버전의 일반 새로고침에서는 모듈과 계산 캐시를 유지합니다. 계좌 DB나 개인 기록 파일을 삭제하지 않습니다.

오래된 모듈이 남은 업데이트 상황도 별도로 검사할 수 있습니다.

```bash
BTC_CHECK_STALE_IMPORTS=1 python -I scripts/check_deployment.py
```

이 검사는 이전 `candles` 모듈을 먼저 로딩한 상태에서 공개 앱을 실행하고, 최신 모듈로 복구된 뒤 반복 실행에서는 같은 모듈을 유지하는지 확인합니다. 이미 실패 중인 Community Cloud 앱은 수정 코드 반영 후 **Manage app → Reboot app**으로 기존 프로세스를 한 번 정리할 수 있습니다.

로컬과 공개 앱 모두 Binance BTC/USDT Live로 고정합니다. 상단은 BTC/ETH·환율·김프·NQ 연속 선물·미국 10년물 금리의 여섯 카드입니다. Upbit BTC는 김프 산출용으로만 수신합니다. Binance는 연결 하나의 BTC/ETH aggTrade+ticker를 사용하며 REST 대체 조회는 두 심볼을 묶어 5초마다 수행합니다. Upbit는 11초 간격을 유지합니다. API 키는 필요하지 않습니다.

NQ와 미국 10년물은 서버가 `query1.finance.yahoo.com`의 공개 chart v8 자료를 직접 읽고 작은 SVG 그래프를 그립니다. `NQ=F`는 NQ 선물, `^TNX`는 CBOE 10년물 수익률 지표(%)입니다. 현물 지수·CFD·국채 가격으로 대체하지 않으며 ^TNX를 10으로 나누지 않습니다. Yahoo 제공 시각과 지연 정보, 휴장 시 마지막 거래 시세를 표시합니다. 지원하지 않는 TradingView 외부 임베드는 제거했습니다. 요청 실패는 대기/갱신 지연으로 표시하며 실제 시세를 만들어 넣지 않습니다.

뉴스는 서버에서 `news.google.com` 한국어·영어 RSS를 읽습니다. 자료원별 한 요청만 진행하며 최대 4개 백그라운드 작업, 시세 60초·뉴스 300초 캐시, 연결/읽기 제한과 본문 크기 제한, 오류 시 지수 대기와 Retry-After를 적용합니다. 첫 코인 화면은 이 요청 완료를 기다리지 않습니다. 자료원이 늦어도 정상 시세/봉 분석을 유지합니다. 뉴스·거시 카드 fragment는 5초마다 캐시만 확인하고, 예측 fragment는 60초마다 최근 뉴스 시나리오를 갱신합니다. API 키나 새 운영 의존성은 필요하지 않습니다.

환율·김프에는 브라우저에서 `quotation-api-cdn.dunamu.com`(은행 고시), `api.frankfurter.dev`(일별 대체 환율), `api.exchange.coinbase.com`(USDT/USD)도 접근 가능해야 합니다. 인증키를 요구하지 않는 공개 조회이며 요청에 계좌 정보를 넣지 않습니다. 환율과 USDT/USD는 분 단위로 조회합니다. CORS·지역·서비스 제한으로 접근하지 못하면 숫자를 만들어 넣지 않고 대기/지연으로 표시합니다.

개발 클라우드의 기존 허용 목록은 Binance·Upbit만 포함했습니다. 새 세 자료원은 실제 요청에서 프록시 CONNECT 403이었고 필요한 도메인을 보존·추가한 환경 설정 **초안**을 저장했습니다. 환경 설정의 저장/적용 후 실제 요청을 다시 검사해야 하며, 이 초안이 Streamlit Community Cloud나 현재 프록시에 자동 적용된 것은 아닙니다. 응답을 주입한 브라우저 검사는 실제 외부 연결 성공과 구분합니다.

현재 개발 환경에서 새 Yahoo·Google News 요청은 프록시 CONNECT 403으로 실제 응답을 확인하지 못했습니다. 기존 허용 목록을 보존하고 `query1.finance.yahoo.com`, `news.google.com`을 환경 설정 초안에 추가했습니다. 환경 설정에서 검토·저장하고 환경을 게시한 뒤 차단된 실제 요청만 다시 확인합니다. 이 초안은 Streamlit Community Cloud나 방문자 네트워크에 자동 적용되지 않습니다. 결정적인 외부 시세 수신·뉴스 기사 제공은 호스팅에서 별도로 확인해야 합니다. 테스트용 응답의 숫자와 기사를 운영 데이터로 사용하지 않습니다.

분석 서버는 공개 REST에 접근할 수 있어야 하고, 방문자 브라우저는 자신의 네트워크에서 시세 API에 접근할 수 있어야 합니다. 연결 제한이나 인증서 오류를 숨기거나 검증을 끄지 않습니다. WebSocket이 불가능하면 REST 조회로 전환하며 오래된 가격은 지연 상태로 표시합니다. Live 오류를 합성 가격으로 대체하지 않습니다.

무료 호스팅은 유휴 상태에서 잠들 수 있어 첫 접속에 시간이 걸립니다. 실시간 시세 위젯은 분석 수집과 별도로 시작하고 이후 틱 수신은 Python 계산을 유발하지 않습니다. 분석 봉은 접속 중 60초마다 확인합니다.

## 데이터 보관

웹 화면에서 모의계좌·백테스트·신호 기록·설정 저장을 제거했습니다. 방문자별 계좌 DB나 임시 세션 저장 폴더를 생성하지 않습니다. 공개 가격 캐시에는 OHLCV만 저장하며 기존 개인 DB는 읽거나 삭제하지 않습니다. 모바일 경량화를 위해 과거 예측 성적·세부 유사도 footer와 모든 CSV/JSON 다운로드도 제거했습니다.

차트의 드래그 확대·팬·더블탭·축 변경 도구는 꺼져 있습니다. 기존 코인 iframe의 작은 터치 처리기가 부모 Plotly 차트에 가격 표시를 전달합니다. 별도 컴포넌트나 Python 이벤트·네트워크 요청을 추가하지 않습니다. 차트 위 세로 스와이프는 페이지 스크롤로 전달하고 마우스 가격 조회는 유지합니다.

공개 배포에 기존 개인 DB, `.env`, `.streamlit/secrets.toml`을 올리지 않습니다. 실제 주문 기능은 없습니다.

## 기존 서버 또는 Docker

Python 호스팅에서는 저장소 루트에서 아래 두 명령을 사용합니다.

```bash
python -m pip install -r requirements.txt
sh scripts/start_web.sh
```

서버가 제공하는 `PORT`를 사용하며 기본값은 8501입니다. HTTPS 도메인과 WebSocket을 지원하는 서비스의 프록시를 연결해야 외부 접속이 가능합니다. XSRF/CORS 검증은 켠 상태로 유지합니다.

Docker를 지원하는 호스팅에서는 저장소의 `Dockerfile`을 사용합니다.

```bash
docker build -t btc-trading-analyzer:web .
docker run --rm -p 8501:8501 btc-trading-analyzer:web
```

컨테이너는 일반 사용자로 실행하며 healthcheck는 `/_stcore/health`를 확인합니다. Docker 실행만으로 HTTPS 도메인이 생기지는 않습니다. 호스팅 서비스에서 제공한 주소를 사용하세요.

관리자가 설정할 수 있는 선택적 환경 변수는 다음과 같습니다.

| 변수 | 기본값 / 용도 |
|---|---|
| `PORT` | `8501` · 호스팅 포트 |
| `BTC_WEB_DATA_DIR` | `data/web` · 쓰기 가능한 임시 데이터 루트 |
| `BTC_LOG_LEVEL` | `INFO` · 서버 로그 |

두 진입점 모두 개인 DB와 분리된 시장 캐시를 사용합니다. 로컬 실행은 `python -m streamlit run app.py`입니다. `BTC_DEFAULT_SOURCE`·`BTC_DEFAULT_EXCHANGE`는 웹 앱에서 더 이상 사용하지 않습니다. `BTC_DB_PATH`는 기존 CLI용이며 웹 화면의 시장 캐시 위치를 바꾸지 않습니다.
