#!/usr/bin/env python3
"""
AWS EC2 动态 DNS 更新脚本（阿里云 DNS）
自动获取EC2实例公网IP, 并更新到阿里云DNS记录
"""
import json
import sys
import subprocess
import os
import shutil
from datetime import datetime
from alibabacloud_alidns20150109.client import Client as Alidns20150109Client
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_alidns20150109 import models as alidns_models

# ======================== 配置区域 ========================
# 从环境变量读取
ACCESS_KEY_ID = os.environ.get('ALIYUN_ACCESS_KEY_ID', 'LTAI5XXXXX')
ACCESS_KEY_SECRET = os.environ.get('ALIYUN_ACCESS_KEY_SECRET', 'PCLxYYYYY')

DOMAIN_NAME = 'goodgood.top'  # 主域名
RR = '@'                          # 根域名使用 @，子域名如 www
RECORD_TYPE = 'A'                 # 记录类型
TTL = 600                         # TTL 值（秒）
# ==========================================================


def get_public_ip():
    """
    获取 AWS EC2 当前公网 IPv4（使用 IMDSv2）

    Returns:
        str: 公网 IP 地址，失败返回 None
    """
    # 检查 curl 命令是否存在
    if not shutil.which('curl'):
        print("错误: 未找到 curl 命令，请先安装 curl", file=sys.stderr)
        return None

    try:
        # 步骤1: 获取 IMDSv2 token
        token = subprocess.check_output([
            'curl', '-s', '-X', 'PUT',
            'http://169.254.169.254/latest/api/token',
            '-H', 'X-aws-ec2-metadata-token-ttl-seconds: 21600'
        ], timeout=5).decode().strip()

        if not token:
            print("错误: 无法获取 IMDS token", file=sys.stderr)
            return None

        # 步骤2: 使用 token 获取公网 IP
        ip = subprocess.check_output([
            'curl', '-s',
            '-H', f'X-aws-ec2-metadata-token: {token}',
            'http://169.254.169.254/latest/meta-data/public-ipv4'
        ], timeout=5).decode().strip()

        # 简单验证 IP 格式
        if ip and ip.count('.') == 3:
            return ip
        else:
            print(f"错误: 获取到的 IP 格式不正确: {ip}", file=sys.stderr)
            return None

    except subprocess.TimeoutExpired:
        print("错误: 获取公网 IP 超时（可能不在 AWS EC2 环境中）", file=sys.stderr)
        return None
    except subprocess.CalledProcessError as e:
        print(f"错误: curl 命令执行失败: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"错误: 获取公网 IP 失败: {e}", file=sys.stderr)
        return None


def main():
    """主函数：执行 DDNS 更新流程"""

    # 打印开始执行时间
    start_time = datetime.now()
    print(">" * 5)
    print(f"开始执行时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # 验证配置
    if not ACCESS_KEY_ID or ACCESS_KEY_ID == 'LTAIxxxxxxx':
        print("错误: 请配置有效的 ACCESS_KEY_ID", file=sys.stderr)
        sys.exit(1)

    if not ACCESS_KEY_SECRET or ACCESS_KEY_SECRET == 'PCLxyyyyy':
        print("错误: 请配置有效的 ACCESS_KEY_SECRET", file=sys.stderr)
        sys.exit(1)

    # 获取当前公网 IP
    current_ip = get_public_ip()
    if not current_ip:
        print("无法获取当前实例的公网 IP，退出")
        sys.exit(1)

    print(f"当前实例公网 IP: {current_ip}")

    # 初始化阿里云 DNS 客户端
    try:
        config = open_api_models.Config(
            access_key_id=ACCESS_KEY_ID,
            access_key_secret=ACCESS_KEY_SECRET  # 修正：使用正确的参数名
        )
        config.endpoint = 'alidns.aliyuncs.com'
        client = Alidns20150109Client(config)
    except Exception as e:
        print(f"错误: 初始化阿里云客户端失败: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        # 步骤1: 查询当前 DNS 记录
        print(f"\n正在查询 {RR}.{DOMAIN_NAME} 的 DNS 记录...")
        describe_request = alidns_models.DescribeDomainRecordsRequest(
            domain_name=DOMAIN_NAME,
        )
        describe_response = client.describe_domain_records(describe_request)

        # 检查是否找到记录
        records = describe_response.body.domain_records.record
        if not records:
            print(f"未找到 {RR}.{DOMAIN_NAME} 的 {RECORD_TYPE} 记录")
            print("提示: 请先在阿里云 DNS 控制台手动创建该记录")
            sys.exit(1)

        # 取第一个匹配的记录
        record = records[0]
        record_id = record.record_id
        current_dns_ip = record.value

        print(f"当前 DNS 记录 IP: {current_dns_ip}")
        print(f"记录 ID: {record_id}")
        print(f"TTL: {record.ttl}秒")

        # 步骤2: 判断是否需要更新
        if current_ip == current_dns_ip:
            print("IP 地址未变化，无需更新")
            sys.exit(0)

        # 步骤3: 更新 DNS 记录
        print(f"检测到 IP 变化: {current_dns_ip} → {current_ip}")
        print("正在更新 DNS 记录...")

        update_request = alidns_models.UpdateDomainRecordRequest(
            record_id=record_id,
            rr=RR,
            type_=RECORD_TYPE,
            value=current_ip,
            ttl=TTL
        )

        update_response = client.update_domain_record(update_request)

        print("DNS 更新成功！")
        print(f"新IP: {current_ip}")
        print(f"记录ID: {update_response.body.record_id}")
        print(f"生效时间: 约 {TTL} 秒")

        # 输出详细响应（可选）
        if os.environ.get('DEBUG'):
            print("\n详细响应:")
            print(json.dumps(update_response.body.to_map(), indent=2, ensure_ascii=False))

    except Exception as e:
        print(f"\n阿里云 API 调用失败: {str(e)}", file=sys.stderr)

        # 提供更详细的错误信息
        if 'InvalidAccessKeyId' in str(e):
            print("提示: ACCESS_KEY_ID 无效，请检查配置", file=sys.stderr)
        elif 'SignatureDoesNotMatch' in str(e):
            print("提示: ACCESS_KEY_SECRET 错误，请检查配置", file=sys.stderr)
        elif 'Forbidden.RAM' in str(e):
            print("提示: RAM 权限不足，需要 AliyunDNSFullAccess 权限", file=sys.stderr)

        sys.exit(1)


if __name__ == '__main__':
    main()