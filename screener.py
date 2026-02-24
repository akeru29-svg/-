"""
株式スクリーニングエンジン

スクリーニング条件:
1. 過去2年間で直近に最高値を更新した銘柄（カップウィズハンドルパターン検出付き）
2. PER 10倍〜30倍（赤字→黒字転換銘柄はPER制限なし）
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed


# 日本の主要銘柄（東証プライム中心）のティッカーリスト
# yfinanceでは日本株は ".T" サフィックス
DEFAULT_TICKERS = [
    # 大型株
    "7203.T", "6758.T", "9984.T", "8306.T", "6861.T",
    "7741.T", "6098.T", "4063.T", "6954.T", "9433.T",
    "8035.T", "6367.T", "7974.T", "4519.T", "6501.T",
    "9432.T", "6902.T", "7267.T", "4568.T", "6594.T",
    "3382.T", "8058.T", "8031.T", "8001.T", "8002.T",
    # 中型成長株
    "6920.T", "6526.T", "4385.T", "3769.T", "6532.T",
    "4483.T", "7342.T", "4180.T", "6254.T", "3697.T",
    "4478.T", "7071.T", "4443.T", "6035.T", "3923.T",
    "2413.T", "4684.T", "6857.T", "7735.T", "6146.T",
    # 半導体・テック
    "6723.T", "6981.T", "6762.T", "6503.T", "6752.T",
    "4689.T", "4755.T", "3659.T", "2371.T", "9613.T",
    # 製造・素材
    "5401.T", "5411.T", "3407.T", "4188.T", "4005.T",
    "7011.T", "7012.T", "6301.T", "6302.T", "7013.T",
    # 金融・保険
    "8316.T", "8411.T", "8766.T", "8630.T", "8795.T",
    # 小売・サービス
    "9983.T", "3099.T", "7532.T", "2670.T", "3092.T",
    "7453.T", "2782.T", "3038.T", "9843.T", "2930.T",
    # 不動産・建設
    "8801.T", "8802.T", "1925.T", "1928.T", "1878.T",
    # ヘルスケア
    "4503.T", "4502.T", "4523.T", "4578.T", "2269.T",
    # その他注目銘柄
    "6976.T", "6273.T", "6645.T", "9468.T", "4307.T",
]


def fetch_stock_data(ticker: str, period_years: int = 2) -> dict | None:
    """個別銘柄のデータを取得する"""
    try:
        stock = yf.Ticker(ticker)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_years * 365)

        hist = stock.history(start=start_date.strftime("%Y-%m-%d"),
                            end=end_date.strftime("%Y-%m-%d"))
        if hist.empty or len(hist) < 60:
            return None

        info = stock.info
        return {
            "ticker": ticker,
            "info": info,
            "history": hist,
        }
    except Exception:
        return None


def check_two_year_high(hist: pd.DataFrame, lookback_days: int = 20) -> dict:
    """
    過去2年間の最高値を直近で更新しているかチェック

    Args:
        hist: 株価履歴データ
        lookback_days: 直近何営業日以内に最高値をつけたか

    Returns:
        dict: is_near_high, high_price, current_price, pct_from_high
    """
    high_prices = hist["High"]
    two_year_high = high_prices.max()
    recent_high = high_prices.iloc[-lookback_days:].max()
    current_price = hist["Close"].iloc[-1]

    # 直近の高値が2年最高値の98%以上なら「最高値圏」と判定
    is_near_high = recent_high >= two_year_high * 0.98
    pct_from_high = (current_price / two_year_high - 1) * 100

    return {
        "is_near_high": is_near_high,
        "high_price": float(two_year_high),
        "current_price": float(current_price),
        "pct_from_high": round(pct_from_high, 2),
    }


def detect_cup_with_handle(hist: pd.DataFrame) -> dict:
    """
    カップウィズハンドル（CWH）パターンを検出する

    条件:
    - カップ：高値→下落（15%〜50%）→回復で元の高値付近に戻る (U字型)
    - ハンドル：カップの右側リムから小さな下落（5%〜15%）→再上昇
    - カップの期間：7週〜65週（35〜325営業日）
    """
    if len(hist) < 60:
        return {"has_pattern": False}

    closes = hist["Close"].values
    highs = hist["High"].values

    best_score = 0
    best_pattern = None

    # 複数のウィンドウサイズでカップを探索
    for cup_len in range(50, min(len(closes) - 20, 326), 10):
        for start_idx in range(max(0, len(closes) - cup_len - 30),
                               max(0, len(closes) - cup_len), 5):
            end_idx = start_idx + cup_len
            if end_idx >= len(closes) - 5:
                continue

            cup_segment = closes[start_idx:end_idx]
            left_rim = np.max(cup_segment[:len(cup_segment) // 5])
            right_rim = np.max(cup_segment[-len(cup_segment) // 5:])
            cup_bottom = np.min(cup_segment[len(cup_segment) // 5:
                                            -len(cup_segment) // 5])

            # カップの深さチェック（15%〜50%下落）
            depth_from_left = (left_rim - cup_bottom) / left_rim
            if depth_from_left < 0.12 or depth_from_left > 0.55:
                continue

            # 左右のリムが近い高さか（許容差20%）
            rim_diff = abs(right_rim - left_rim) / left_rim
            if rim_diff > 0.20:
                continue

            # U字型チェック: ボトムがカップの中央付近にあるか
            bottom_idx = np.argmin(cup_segment) / len(cup_segment)
            if bottom_idx < 0.2 or bottom_idx > 0.8:
                continue

            # ハンドル検出（カップ右側リム以降）
            handle_segment = closes[end_idx:]
            if len(handle_segment) < 5:
                continue

            handle_high = np.max(handle_segment[:5])
            handle_low = np.min(handle_segment)
            handle_depth = (handle_high - handle_low) / handle_high

            has_handle = 0.03 <= handle_depth <= 0.18

            # スコアリング
            score = 0
            # カップの対称性
            score += max(0, 1 - rim_diff * 5) * 30
            # カップの深さが理想範囲（20-35%）に近いほど高スコア
            ideal_depth = 0.25
            score += max(0, 1 - abs(depth_from_left - ideal_depth) * 5) * 25
            # ボトムが中央に近いほど高スコア
            score += max(0, 1 - abs(bottom_idx - 0.5) * 3) * 20
            # ハンドルがあれば加点
            if has_handle:
                score += 25

            if score > best_score:
                best_score = score
                best_pattern = {
                    "has_pattern": True,
                    "has_handle": has_handle,
                    "cup_depth_pct": round(depth_from_left * 100, 1),
                    "handle_depth_pct": round(handle_depth * 100, 1) if has_handle else 0,
                    "cup_duration_days": cup_len,
                    "score": round(score, 1),
                    "left_rim": float(left_rim),
                    "right_rim": float(right_rim),
                    "cup_bottom": float(cup_bottom),
                }

    if best_pattern and best_score >= 40:
        return best_pattern
    return {"has_pattern": False}


def check_per_criteria(info: dict) -> dict:
    """
    PER条件をチェック

    条件:
    - 基本: PER 10倍〜30倍
    - 例外: 赤字→黒字転換銘柄はPER制限なし
    """
    per = info.get("trailingPE") or info.get("forwardPE")
    earnings = info.get("netIncomeToCommon")
    prev_earnings = info.get("previousEarnings")
    revenue_growth = info.get("revenueGrowth")
    earnings_growth = info.get("earningsGrowth")

    # 赤字→黒字転換の判定
    is_turnaround = False
    if earnings_growth is not None and earnings_growth > 1.0:
        # 利益成長率100%超 = 大幅改善（赤字→黒字含む）
        is_turnaround = True
    if per is not None and per < 0:
        # 現在赤字の場合はスクリーニング対象外
        return {
            "passes": False,
            "per": per,
            "is_turnaround": False,
            "reason": "現在赤字",
        }

    if per is None:
        return {
            "passes": False,
            "per": None,
            "is_turnaround": False,
            "reason": "PER情報なし",
        }

    # 赤字→黒字転換ならPER制限なし
    if is_turnaround:
        return {
            "passes": True,
            "per": round(per, 2),
            "is_turnaround": True,
            "reason": "黒字転換銘柄（PER制限免除）",
        }

    # 通常のPER範囲チェック
    passes = 10 <= per <= 30
    reason = "PER適正範囲" if passes else f"PER {per:.1f}倍は範囲外"

    return {
        "passes": passes,
        "per": round(per, 2),
        "is_turnaround": False,
        "reason": reason,
    }


def screen_stock(ticker: str) -> dict | None:
    """個別銘柄のスクリーニングを実行"""
    data = fetch_stock_data(ticker)
    if data is None:
        return None

    info = data["info"]
    hist = data["history"]

    # 条件1: 2年高値チェック
    high_result = check_two_year_high(hist)
    if not high_result["is_near_high"]:
        return None

    # 条件2: PERチェック
    per_result = check_per_criteria(info)
    if not per_result["passes"]:
        return None

    # カップウィズハンドル検出（オプション、フィルタではない）
    cwh_result = detect_cup_with_handle(hist)

    name = info.get("longName") or info.get("shortName") or ticker
    sector = info.get("sector", "N/A")
    industry = info.get("industry", "N/A")
    market_cap = info.get("marketCap")

    return {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "industry": industry,
        "market_cap": market_cap,
        "current_price": high_result["current_price"],
        "two_year_high": high_result["high_price"],
        "pct_from_high": high_result["pct_from_high"],
        "per": per_result["per"],
        "is_turnaround": per_result["is_turnaround"],
        "per_reason": per_result["reason"],
        "cwh": cwh_result,
    }


def run_screening(tickers: list[str] | None = None,
                   max_workers: int = 5) -> list[dict]:
    """
    スクリーニングを並列実行

    Args:
        tickers: スクリーニング対象のティッカーリスト
        max_workers: 並列ワーカー数

    Returns:
        条件を満たした銘柄のリスト
    """
    if tickers is None:
        tickers = DEFAULT_TICKERS

    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(screen_stock, t): t for t in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
            except Exception:
                pass

    # CWHスコア→高値近接度でソート
    results.sort(key=lambda x: (
        x["cwh"].get("score", 0) if x["cwh"]["has_pattern"] else 0,
        -abs(x["pct_from_high"]),
    ), reverse=True)

    return results


def format_market_cap(value: float | None) -> str:
    """時価総額を読みやすい形式に変換"""
    if value is None:
        return "N/A"
    if value >= 1e12:
        return f"{value / 1e12:.1f}兆円"
    if value >= 1e8:
        return f"{value / 1e8:.0f}億円"
    return f"{value / 1e4:.0f}万円"
