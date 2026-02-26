"""
株式スクリーニング Webアプリケーション

Flask + SSE でリアルタイム進捗表示付きスクリーニングを提供する。
"""

import json
import numpy as np
from flask import Flask, render_template, request, Response, stream_with_context
from flask_cors import CORS


class NumpyEncoder(json.JSONEncoder):
    """numpy型をJSON化できるようにするエンコーダー"""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def _dumps(obj):
    """numpy型対応のJSON直列化"""
    return json.dumps(obj, cls=NumpyEncoder, ensure_ascii=False)


from screener import (
    run_screening,
    fetch_stock_data,
    check_two_year_high,
    check_per_criteria,
    detect_cup_with_handle,
    format_market_cap,
    DEFAULT_TICKERS,
)

app = Flask(__name__)
CORS(app)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/screen")
def screen():
    """SSEでリアルタイム進捗を返しながらスクリーニングを実行"""
    tickers_param = request.args.get("tickers", "").strip()
    if tickers_param:
        tickers = [t.strip().upper() for t in tickers_param.split(",") if t.strip()]
        # .Tサフィックスがない場合は付与
        tickers = [t if "." in t else t + ".T" for t in tickers]
    else:
        tickers = DEFAULT_TICKERS

    # 適用する条件を取得（デフォルトは全条件ON）
    criteria_param = request.args.get("criteria", "high,per,cwh").strip()
    active_criteria = set(c.strip() for c in criteria_param.split(",") if c.strip())
    use_high = "high" in active_criteria
    use_per = "per" in active_criteria
    use_cwh = "cwh" in active_criteria

    def generate():
        total = len(tickers)
        found = 0

        for i, ticker in enumerate(tickers):
            # 進捗通知
            yield f"data: {_dumps({'type': 'progress', 'current': i + 1, 'total': total, 'found': found, 'ticker': ticker})}\n\n"

            try:
                data = fetch_stock_data(ticker)
                if data is None:
                    continue

                info = data["info"]
                hist = data["history"]

                # 条件1: 2年高値チェック（常に算出、フィルタはON時のみ）
                high_result = check_two_year_high(hist)
                if use_high and not high_result["is_near_high"]:
                    continue

                # 条件2: PERチェック（常に算出、フィルタはON時のみ）
                per_result = check_per_criteria(info)
                if use_per and not per_result["passes"]:
                    continue

                # CWH検出（ONの場合のみ実行）
                if use_cwh:
                    cwh_result = detect_cup_with_handle(hist)
                else:
                    cwh_result = {"has_pattern": False}

                name = info.get("longName") or info.get("shortName") or ticker
                sector = info.get("sector", "N/A")
                industry = info.get("industry", "N/A")
                market_cap = info.get("marketCap")

                stock = {
                    "ticker": ticker,
                    "name": name,
                    "sector": sector,
                    "industry": industry,
                    "market_cap": market_cap,
                    "market_cap_str": format_market_cap(market_cap),
                    "current_price": high_result["current_price"],
                    "two_year_high": high_result["high_price"],
                    "pct_from_high": high_result["pct_from_high"],
                    "per": per_result["per"],
                    "is_turnaround": per_result["is_turnaround"],
                    "per_reason": per_result["reason"],
                    "cwh": cwh_result,
                }

                found += 1
                yield f"data: {_dumps({'type': 'result', 'stock': stock})}\n\n"

            except Exception:
                continue

        yield f"data: {_dumps({'type': 'complete', 'total_found': found, 'total_screened': total})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
