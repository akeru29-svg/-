# Stock Screener - 株式スクリーニングツール

2年高値更新 × PER × カップウィズハンドル検出による日本株スクリーナー。

## スクリーニング条件

1. **2年高値更新**: 過去2年間の最高値に対し、直近20営業日以内に98%以上まで到達した銘柄
2. **PER 10〜30倍**: 基本はPER 10〜30倍。赤字→黒字転換銘柄（利益成長率100%超）はPER制限免除
3. **カップウィズハンドル (CWH)**: パターンを自動検出しスコアリング（フィルタではなく加点方式）

## セットアップ

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 起動

```bash
source venv/bin/activate
python app.py
```

ブラウザで `http://localhost:5000` にアクセス。

## 使い方

- **デフォルト銘柄**: 入力欄を空のまま「スクリーニング実行」→ プリセット約100銘柄をスクリーニング
- **カスタム銘柄**: ティッカーをカンマ区切りで入力（例: `7203.T, 9984.T, 6758.T`）
- SSEによるリアルタイム進捗表示。該当銘柄は即座にカードとして表示される

## 技術スタック

- Python 3.11+
- Flask (Web フレームワーク)
- yfinance (株価データ取得)
- pandas / numpy (データ分析)
- Server-Sent Events (リアルタイム進捗)
