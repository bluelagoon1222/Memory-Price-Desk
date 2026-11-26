# Memory-Price-Desk

DRAM·NAND 현물가/계약가 일일 기록 + HBM 전망 보드 + 메모리 주가 비교.

- `fetch.py`: TrendForce 공개 가격표(하루 1~2회) + Yahoo Finance 주가 수집 → `data/prices.json`, `data/stocks.json`
- `data/hbm.json`, `data/outlook.json`: 수기 관리(새 전망 발표 시 한 줄 추가)
- `.github/workflows/update.yml`: 평일 19:40 KST, 매일 07:00 KST 실행
