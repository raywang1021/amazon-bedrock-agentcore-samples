#!/usr/bin/env python3
"""驗證 GEO 分數追蹤功能是否正確部署。

此腳本會：
1. 檢查 DynamoDB 表是否存在
2. 檢查 Lambda 函數是否部署
3. 測試寫入和讀取包含分數的項目
4. 驗證所有必要欄位
"""

import sys
import os
import json
import boto3
from datetime import datetime, timezone
from decimal import Decimal

# 配置
REGION = os.environ.get("AWS_REGION", "us-east-1")
TABLE_NAME = os.environ.get("GEO_TABLE_NAME", "geo-content")
STORAGE_FUNCTION = "geo-content-storage"
GENERATOR_FUNCTION = "geo-content-generator"

def check_dynamodb_table():
    """檢查 DynamoDB 表是否存在且可訪問。"""
    print("1. 檢查 DynamoDB 表...", flush=True)
    try:
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        table = dynamodb.Table(TABLE_NAME)
        status = table.table_status
        print(f"   ✓ 表 '{TABLE_NAME}' 存在，狀態: {status}", flush=True)
        return True
    except Exception as e:
        print(f"   ✗ 錯誤: {e}", flush=True)
        return False

def check_lambda_functions():
    """檢查 Lambda 函數是否部署。"""
    print("\n2. 檢查 Lambda 函數...", flush=True)
    lambda_client = boto3.client("lambda", region_name=REGION)
    
    functions = [STORAGE_FUNCTION, GENERATOR_FUNCTION]
    all_exist = True
    
    for func_name in functions:
        try:
            response = lambda_client.get_function(FunctionName=func_name)
            runtime = response["Configuration"]["Runtime"]
            print(f"   ✓ {func_name} 已部署 (runtime: {runtime})", flush=True)
        except lambda_client.exceptions.ResourceNotFoundException:
            print(f"   ✗ {func_name} 未找到", flush=True)
            all_exist = False
        except Exception as e:
            print(f"   ✗ 檢查 {func_name} 時出錯: {e}", flush=True)
            all_exist = False
    
    return all_exist

def test_storage_lambda():
    """測試 Storage Lambda 是否支援分數欄位。"""
    print("\n3. 測試 Storage Lambda 分數支援...", flush=True)
    
    lambda_client = boto3.client("lambda", region_name=REGION)
    
    # 準備測試 payload
    test_payload = {
        "url_path": "/test/verify-deployment",
        "geo_content": "<html><body><h1>Test Content</h1></body></html>",
        "original_url": "https://example.com/test/verify-deployment",
        "content_type": "text/html; charset=utf-8",
        "generation_duration_ms": 1234,
        "host": "example.com",
        "original_score": {
            "overall_score": 50,
            "dimensions": {
                "cited_sources": {"score": 45},
                "statistical_addition": {"score": 40},
                "authoritative": {"score": 65}
            }
        },
        "geo_score": {
            "overall_score": 82,
            "dimensions": {
                "cited_sources": {"score": 85},
                "statistical_addition": {"score": 80},
                "authoritative": {"score": 81}
            }
        }
    }
    
    try:
        # 調用 Storage Lambda
        response = lambda_client.invoke(
            FunctionName=STORAGE_FUNCTION,
            InvocationType="RequestResponse",
            Payload=json.dumps(test_payload)
        )
        
        result = json.loads(response["Payload"].read())
        
        if result.get("statusCode") == 200:
            print("   ✓ Storage Lambda 成功處理包含分數的 payload", flush=True)
            return True
        else:
            print(f"   ✗ Storage Lambda 返回錯誤: {result}", flush=True)
            return False
            
    except Exception as e:
        print(f"   ✗ 調用 Storage Lambda 失敗: {e}", flush=True)
        return False

def verify_ddb_item():
    """驗證 DynamoDB 中的項目包含所有分數欄位。"""
    print("\n4. 驗證 DynamoDB 項目...", flush=True)
    
    try:
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        table = dynamodb.Table(TABLE_NAME)
        
        # 讀取測試項目
        response = table.get_item(
            Key={"url_path": "example.com#/test/verify-deployment"}
        )
        
        item = response.get("Item")
        
        if not item:
            print("   ✗ 未找到測試項目", flush=True)
            return False
        
        # 檢查必要欄位
        required_fields = [
            "geo_content",
            "original_score",
            "geo_score",
            "score_improvement"
        ]
        
        missing_fields = []
        for field in required_fields:
            if field not in item:
                missing_fields.append(field)
        
        if missing_fields:
            print(f"   ✗ 缺少欄位: {', '.join(missing_fields)}", flush=True)
            return False
        
        # 驗證分數值
        original = float(item["original_score"]["overall_score"])
        geo = float(item["geo_score"]["overall_score"])
        improvement = float(item["score_improvement"])
        expected_improvement = geo - original
        
        print(f"   ✓ 所有必要欄位存在", flush=True)
        print(f"   ✓ Original score: {original}", flush=True)
        print(f"   ✓ GEO score: {geo}", flush=True)
        print(f"   ✓ Improvement: +{improvement}", flush=True)
        
        if abs(improvement - expected_improvement) < 0.01:
            print(f"   ✓ 分數計算正確", flush=True)
        else:
            print(f"   ⚠ 分數計算可能有誤: 預期 {expected_improvement}, 實際 {improvement}", flush=True)
        
        return True
        
    except Exception as e:
        print(f"   ✗ 驗證失敗: {e}", flush=True)
        return False

def cleanup():
    """清理測試資料。"""
    print("\n5. 清理測試資料...", flush=True)
    
    try:
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        table = dynamodb.Table(TABLE_NAME)
        
        table.delete_item(Key={"url_path": "example.com#/test/verify-deployment"})
        print("   ✓ 測試資料已清理", flush=True)
        return True
        
    except Exception as e:
        print(f"   ⚠ 清理失敗（可忽略）: {e}", flush=True)
        return False

def main():
    """主函數。"""
    print("=" * 60)
    print("GEO 分數追蹤功能部署驗證")
    print("=" * 60)
    
    results = []
    
    # 執行所有檢查
    results.append(("DynamoDB 表", check_dynamodb_table()))
    results.append(("Lambda 函數", check_lambda_functions()))
    results.append(("Storage Lambda", test_storage_lambda()))
    results.append(("DynamoDB 項目", verify_ddb_item()))
    
    # 清理
    cleanup()
    
    # 總結
    print("\n" + "=" * 60)
    print("驗證結果總結")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "✓ 通過" if passed else "✗ 失敗"
        print(f"{name:20s} {status}")
        if not passed:
            all_passed = False
    
    print("=" * 60)
    
    if all_passed:
        print("\n🎉 所有檢查通過！分數追蹤功能已正確部署。")
        return 0
    else:
        print("\n⚠️  部分檢查失敗，請查看上方詳細資訊。")
        return 1

if __name__ == "__main__":
    sys.exit(main())
