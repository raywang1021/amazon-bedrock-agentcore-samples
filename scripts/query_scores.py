#!/usr/bin/env python3
"""查詢和分析 GEO 分數追蹤資料的工具腳本。

使用範例:
  python scripts/query_scores.py --stats          # 顯示統計資訊
  python scripts/query_scores.py --top 10         # 顯示改善最大的前 10 項
  python scripts/query_scores.py --url /path     # 查詢特定 URL 的分數
  python scripts/query_scores.py --export scores.json  # 匯出所有分數資料
"""

import argparse
import json
import sys
import boto3
from decimal import Decimal
from typing import List, Dict, Any

REGION = "us-east-1"
TABLE_NAME = "geo-content"


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder for Decimal types."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def get_all_items_with_scores(region: str = None, table_name: str = None) -> List[Dict[str, Any]]:
    """掃描 DynamoDB 並返回所有包含分數的項目。"""
    region = region or REGION
    table_name = table_name or TABLE_NAME
    
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)
    
    items = []
    scan_kwargs = {
        "ProjectionExpression": "url_path, original_score, geo_score, score_improvement, created_at, generation_duration_ms"
    }
    
    try:
        response = table.scan(**scan_kwargs)
        items.extend([
            item for item in response.get("Items", [])
            if "score_improvement" in item
        ])
        
        # 處理分頁
        while "LastEvaluatedKey" in response:
            scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            response = table.scan(**scan_kwargs)
            items.extend([
                item for item in response.get("Items", [])
                if "score_improvement" in item
            ])
    except Exception as e:
        print(f"錯誤: 無法掃描 DynamoDB 表: {e}", file=sys.stderr)
        sys.exit(1)
    
    return items


def show_statistics(items: List[Dict[str, Any]]):
    """顯示分數統計資訊。"""
    if not items:
        print("沒有找到包含分數的項目。")
        return
    
    improvements = [float(item["score_improvement"]) for item in items]
    original_scores = [
        float(item["original_score"]["overall_score"])
        for item in items
        if "original_score" in item and "overall_score" in item["original_score"]
    ]
    geo_scores = [
        float(item["geo_score"]["overall_score"])
        for item in items
        if "geo_score" in item and "overall_score" in item["geo_score"]
    ]
    
    print("=" * 60)
    print("GEO 分數追蹤統計")
    print("=" * 60)
    print(f"總項目數: {len(items)}")
    print()
    
    if improvements:
        print("分數改善:")
        print(f"  平均: +{sum(improvements) / len(improvements):.1f}")
        print(f"  最大: +{max(improvements):.1f}")
        print(f"  最小: +{min(improvements):.1f}")
        print()
    
    if original_scores:
        print("原始分數:")
        print(f"  平均: {sum(original_scores) / len(original_scores):.1f}")
        print(f"  範圍: {min(original_scores):.0f} - {max(original_scores):.0f}")
        print()
    
    if geo_scores:
        print("GEO 優化後分數:")
        print(f"  平均: {sum(geo_scores) / len(geo_scores):.1f}")
        print(f"  範圍: {min(geo_scores):.0f} - {max(geo_scores):.0f}")
        print()
    
    # 維度分析 (auto-detect dimensions)
    dimensions = _detect_dimensions(items)
    if dimensions:
        print("各維度平均改善:")
        for dim in dimensions:
            original_dim = []
            geo_dim = []
            for item in items:
                o = _get_dim_score(item.get("original_score"), dim)
                g = _get_dim_score(item.get("geo_score"), dim)
                if o is not None:
                    original_dim.append(o)
                if g is not None:
                    geo_dim.append(g)
            
            if original_dim and geo_dim:
                avg_original = sum(original_dim) / len(original_dim)
                avg_geo = sum(geo_dim) / len(geo_dim)
                improvement = avg_geo - avg_original
                label = DIM_LABELS.get(dim, dim)
                print(f"  {label:10s} ({dim:20s}): {avg_original:5.1f} → {avg_geo:5.1f} (+{improvement:5.1f})")


def _get_dim_score(score_obj, dim_key):
    """Extract a dimension score from a score object (supports both old and new formats)."""
    if not score_obj or "dimensions" not in score_obj:
        return None
    d = score_obj["dimensions"].get(dim_key)
    if d is None:
        return None
    if isinstance(d, dict) and "score" in d:
        return float(d["score"])
    if isinstance(d, (int, float, Decimal)):
        return float(d)
    return None


def _detect_dimensions(items):
    """Return the 5 scoring dimensions (fixed order)."""
    return ["authority", "freshness", "relevance", "structure", "readability"]


# Short labels for dimension names
DIM_LABELS = {
    "authority": "auth",
    "freshness": "fresh",
    "relevance": "rel",
    "structure": "struct",
    "readability": "read",
    "cited_sources": "cite",
    "statistical_addition": "stat",
    "authoritative": "auth",
}


def show_top_improvements(items: List[Dict[str, Any]], limit: int = 10):
    """顯示改善最大的項目，含各維度分拆。"""
    if not items:
        print("沒有找到包含分數的項目。")
        return
    
    sorted_items = sorted(
        items,
        key=lambda x: float(x.get("score_improvement", 0)),
        reverse=True
    )
    
    dims = _detect_dimensions(items)
    
    print("=" * 140)
    print(f"改善最大的前 {limit} 項")
    print("=" * 140)
    
    # Header
    dim_header = "  ".join(f"{DIM_LABELS.get(d, d[:5]):>5s}" for d in dims)
    print(f"{'Orig':<6} {'GEO':<6} {'Δ':<6} │ {dim_header}  │ URL Path")
    print("-" * 140)
    
    for item in sorted_items[:limit]:
        url_path = item["url_path"]
        original = float(item.get("original_score", {}).get("overall_score", 0))
        geo = float(item.get("geo_score", {}).get("overall_score", 0))
        improvement = float(item.get("score_improvement", 0))
        
        # Dimension breakdown: orig→geo(Δ)
        dim_parts = []
        for d in dims:
            o = _get_dim_score(item.get("original_score"), d)
            g = _get_dim_score(item.get("geo_score"), d)
            if o is not None and g is not None:
                delta = g - o
                sign = "+" if delta > 0 else ""
                dim_parts.append(f"{sign}{delta:>3.0f}")
            else:
                dim_parts.append("   -")
        dim_str = "  ".join(f"{p:>5s}" for p in dim_parts)
        
        sign = "+" if improvement > 0 else ""
        print(f"{original:<6.0f} {geo:<6.0f} {sign}{improvement:<5.0f} │ {dim_str}  │ {url_path}")


def show_url_details(items: List[Dict[str, Any]], url_path: str):
    """顯示特定 URL 的詳細分數資訊。"""
    matching = [item for item in items if url_path in item["url_path"]]
    
    if not matching:
        print(f"未找到包含 '{url_path}' 的項目。")
        return
    
    for item in matching:
        print("=" * 60)
        print(f"URL: {item['url_path']}")
        print("=" * 60)
        
        if "created_at" in item:
            print(f"建立時間: {item['created_at']}")
        
        if "generation_duration_ms" in item:
            print(f"生成時間: {float(item['generation_duration_ms'])}ms")
        
        print()
        
        # 原始分數
        if "original_score" in item:
            orig = item["original_score"]
            print(f"原始分數: {orig.get('overall_score', 'N/A')}")
            if "dimensions" in orig:
                for dim, data in orig["dimensions"].items():
                    print(f"  - {dim}: {data.get('score', 'N/A')}")
        
        print()
        
        # GEO 分數
        if "geo_score" in item:
            geo = item["geo_score"]
            print(f"GEO 分數: {geo.get('overall_score', 'N/A')}")
            if "dimensions" in geo:
                for dim, data in geo["dimensions"].items():
                    print(f"  - {dim}: {data.get('score', 'N/A')}")
        
        print()
        
        if "score_improvement" in item:
            print(f"改善幅度: +{float(item['score_improvement']):.1f}")
        
        print()


def export_scores(items: List[Dict[str, Any]], output_file: str):
    """匯出所有分數資料到 JSON 檔案。"""
    if not items:
        print("沒有找到包含分數的項目。")
        return
    
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2, cls=DecimalEncoder)
        print(f"✓ 已匯出 {len(items)} 個項目到 {output_file}")
    except Exception as e:
        print(f"錯誤: 無法寫入檔案: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="查詢和分析 GEO 分數追蹤資料",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  %(prog)s --stats                    # 顯示統計資訊
  %(prog)s --top 10                   # 顯示改善最大的前 10 項
  %(prog)s --url /world/3149600       # 查詢特定 URL
  %(prog)s --export scores.json       # 匯出所有資料
        """
    )
    
    parser.add_argument("--stats", action="store_true", help="顯示統計資訊")
    parser.add_argument("--top", type=int, metavar="N", help="顯示改善最大的前 N 項")
    parser.add_argument("--url", type=str, metavar="PATH", help="查詢特定 URL 的詳細資訊")
    parser.add_argument("--export", type=str, metavar="FILE", help="匯出所有分數資料到 JSON 檔案")
    parser.add_argument("--region", type=str, default=REGION, help=f"AWS region (預設: {REGION})")
    parser.add_argument("--table", type=str, default=TABLE_NAME, help=f"DynamoDB 表名稱 (預設: {TABLE_NAME})")
    
    args = parser.parse_args()
    
    # 如果沒有指定任何選項，顯示統計資訊
    if not any([args.stats, args.top, args.url, args.export]):
        args.stats = True
    
    # 獲取資料
    print("正在從 DynamoDB 讀取資料...", flush=True)
    items = get_all_items_with_scores(args.region, args.table)
    print(f"找到 {len(items)} 個包含分數的項目\n", flush=True)
    
    # 執行請求的操作
    if args.stats:
        show_statistics(items)
    
    if args.top:
        show_top_improvements(items, args.top)
    
    if args.url:
        show_url_details(items, args.url)
    
    if args.export:
        export_scores(items, args.export)


if __name__ == "__main__":
    main()
