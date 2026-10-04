# 로컬 검증 기록

검증 환경: Python 3.12.14 / Linux / dependency versions in requirements.lock.

| 검증 | 결과 |
|---|---|
| lock 의존성 설치 / 재실행 | 성공; scripts/install_cloud.sh 반복 실행 |
| dependency imports / pip check | 성공; 충돌 없음 |
| pytest | 83 passed; skipped/xfail 없음 |
| Ruff lint / formatting / compileall | 성공 |
| Streamlit HTTP health / 앱 shell | 실제 서버 실행 후 200 및 ok 확인 |
| Streamlit AppTest | 9개 탭, 백테스트, Monte Carlo, 모의 활성/중지, 설정 저장 버튼 검증 |
| Offline integration | 지표·분석·다중 타임프레임·백테스트·SQLite·모의 재시작 성공 |
| Demo 전체 Robustness | IS/Validation/OOS, 파라미터 27개, 비용 3개, Walk Forward 5개, Monte Carlo 1000회 실행 |
| Upbit 공개 API | 5m/15m/1h/4h/1d 실제 확정 봉 수집 성공 |
| Upbit 실데이터 분석/백테스트 | 2026-09-20~2026-10-04 UTC, 1h와 15m/4h/1d 분석 실행 성공; 평가 거래 0회 명시 |
| Binance 공개 API | 현재 머신 지역에서 거래소 HTTP 451; 어댑터 pagination/normalization은 mock unit test 통과 |

수치 시나리오 테스트는 실제 포지션을 생성하고 다음 봉 진입·부분 익절·손절·갭·정확한 비용/슬리피지 및 SQLite 거래 저장을 검사합니다. 실행 가능한 백테스트라는 사실이 전략 수익성을 입증하지 않습니다.

최근 600개 합성 1h 봉 전체 안정성 실행은 완료 거래 1회였습니다. 원래 표본에 승리 거래 한 개만 있으면 Monte Carlo 결과가 동일할 수 있으며 이를 낮은 실제 위험이라는 증거로 해석하지 않습니다. Robustness는 표본 부족을 반영해 `Needs Improvement`, OOS `Warning`, 과최적화 위험 `High`로 분류했습니다.

환경 초안에 install_script, start_skill 및 api.binance.com/api.upbit.com을 저장했습니다. 초안 저장 성공은 환경 게시/새 머신 복원 완료나 공개 웹 배포를 의미하지 않습니다. 실제 거래 기능은 없습니다. 새 환경에서 복원 검증과 현재 위치의 Binance 서비스 가능 여부는 별도로 확인해야 합니다.

재현:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests app.py web_app.py scripts
.venv/bin/python scripts/smoke.py
.venv/bin/python -m btc_analyzer.cli --source demo --bars 600 --robustness --paper-tick
.venv/bin/python scripts/check_live.py --exchange both
```

마지막 live smoke는 Binance 제한이 해결되지 않으면 종료 코드 1을 반환합니다. Upbit만 재검증하려면 `--exchange Upbit`을 사용하세요. 생성된 실제 보고서는 Git 제외 경로 data/reports/와 data/analyzer.sqlite3에 저장되어 있습니다. CI 워크플로는 Python 3.11/3.12를 선언했지만 GitHub Actions 실행은 이 로컬 검증에 포함되지 않습니다.

## 실행 오류 재검증과 수정

사용자 재점검 요청 후 기존 52개 테스트를 재실행하고 실제 오류 사례를 추가로 재현했습니다.

- 잘못된 Binance 심볼의 CCXT 예외를 DataError로 통일해 화면에 오류를 표시합니다.
- CCXT가 환경 프록시를 기본적으로 무시하는 문제를 수정했습니다. 제공된 HTTPS 프록시와 CA 설정을 사용하며 TLS 검증은 유지합니다. 실제 Binance 요청은 HTTP 451 지역 제한을 명확히 표시하고 같은 요청을 불필요하게 반복하지 않습니다.
- 설정 JSON의 최상위/섹션 타입, 알 수 없는 섹션과 잘못된 값은 ValueError로 검증합니다. 배열 JSON이나 오타가 앱 예외 또는 묵시적인 기본값 대체를 일으키지 않습니다.
- 누락된 상위 타임프레임은 확보율에 포함하지 않습니다. 1h만 있으면 확보율 0%, 4h만 추가되면 50%이며 일봉 누락을 숨기지 않습니다. 현재 봉이 비어 있으면 명확한 데이터 부족 오류를 반환합니다.
- 손상된 SQLite 파일을 지정하면 파일을 보존하고 복구/경로 안내를 표시한 뒤 중지합니다.

최종 회귀 테스트는 77개입니다. 실제 Streamlit 서버를 새로 시작해 HTTP health/app shell을 확인했고, Demo의 다섯 타임프레임과 오류 입력 UI를 검증했습니다. 공개 데이터 smoke는 Upbit 확정 봉 수집 성공, Binance HTTP 451을 확인했습니다. Offline integration은 정상 완료했습니다.

## 공개 웹 배포 준비 검증

- `web_app.py`의 기본 Live / Upbit / KRW-BTC 화면을 실제 API 응답으로 실행했습니다. 9개 탭과 10개 지표, 세션별 임시 DB를 확인했습니다.
- `scripts/start_web.sh`를 호스팅의 `PORT`와 함께 실행하고 HTTP health `200 / ok` 및 앱 HTML `200`을 확인한 뒤 검증용 프로세스를 종료했습니다.
- 2개의 실제 Streamlit 테스트 세션을 열어 한 방문자의 활성 모의계좌·백테스트·저장 설정이 다른 방문자에게 공유되지 않는 것을 확인했습니다. 로컬 개인 DB도 그대로 보존했습니다.
- `requirements-runtime.lock`으로 새 가상환경을 설치하고 공개 UI를 실행했습니다. 런타임 환경에는 pytest/ruff가 설치되지 않습니다.
- 전체 테스트 **83 passed**, Ruff lint/format, offline integration 및 클라우드 설치 스크립트 재실행이 통과했습니다.
- Docker 기본 이미지 다운로드는 성공했으나 내부 빌드 컨테이너가 DNS를 사용할 수 없어 PyPI 설치가 실패했습니다. 호스트 네트워크/제공된 프록시 적용 후에도 컨테이너의 프록시 DNS 해석이 실패했습니다. Docker 이미지 전체 빌드와 컨테이너 구동은 검증되지 않았습니다. Streamlit 런타임 설치 및 서버 구동 검증과 구분합니다.
- 공개 호스팅 계정은 이 환경에 연결되어 있지 않습니다. 여기서 수행한 서버 검증은 인터넷 공개 배포 또는 공개 HTTPS 주소 발급을 의미하지 않습니다.
