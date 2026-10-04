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

이 검사는 오프라인 Demo로 공개 화면의 9개 탭·백테스트·모의거래·설정 저장을 실행합니다. CI에서도 개발 패키지 설치와 별개로 검증합니다.

무료 호스팅은 유휴 상태에서 잠들 수 있으며 첫 접속에 시간이 걸립니다. 무중단 서비스나 백그라운드 모의거래 실행을 보장하지 않습니다. Binance가 호스팅 지역에서 HTTP 451을 반환하면 Upbit 또는 명시적인 Demo 모드를 이용하세요. Live 오류는 화면에 표시하며 합성 가격으로 대체하지 않습니다.

## 방문자 기록

- 개인 기록은 서버가 만든 임시 세션 디렉터리에 분리합니다. 브라우저가 보내는 이름·URL로 다른 세션을 선택하지 않습니다.
- 공개 가격 캐시에는 OHLCV만 저장합니다. 개인 모의계좌·백테스트·설정 테이블은 포함하지 않습니다.
- 접속 세션이 끝나면 개인 기록의 유지가 보장되지 않습니다. 필요한 결과는 화면의 CSV/JSON 다운로드를 사용하세요. 기기 간 기록 동기화에는 추후 로그인과 영구 DB가 필요합니다.
- 웹 진입점은 로컬 `BTC_DB_PATH`를 개인 기록으로 사용하지 않습니다. 공개 배포에 기존 개인 DB나 `.env`, `.streamlit/secrets.toml`을 올리지 않습니다.
- 자동 업데이트는 브라우저 접속이 유지되는 동안 작동합니다. 실제 주문 기능은 없습니다.

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
| `BTC_DEFAULT_SOURCE` | `live` · `demo`로 바꾸면 오프라인 시작 |
| `BTC_DEFAULT_EXCHANGE` | `Upbit` · 지원 값 `Upbit` / `Binance` |
| `BTC_LOG_LEVEL` | `INFO` · 서버 로그 |

공개 진입점 `web_app.py`는 항상 사용자 기록을 분리합니다. 일반 개인 연구용 실행은 `python -m streamlit run app.py`를 사용합니다.
