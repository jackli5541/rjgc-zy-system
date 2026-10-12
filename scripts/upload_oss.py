"""把前端构建产物 dist/assets 上传到 OSS。

凭据只从环境变量读取：OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET。
文件名带内容哈希，OSS 上已存在同名文件即视为相同，直接跳过；不会删除旧文件。
"""
import argparse
import mimetypes
import os
import sys
from pathlib import Path

import oss2

CACHE_CONTROL = 'public, max-age=31536000, immutable'
EXTRA_TYPES = {'.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.svg': 'image/svg+xml'}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, help='本地 assets 目录')
    parser.add_argument('--bucket', required=True)
    parser.add_argument('--region', required=True, help='如 cn-hangzhou')
    parser.add_argument('--prefix', required=True, help='Bucket 内目录，如 lab')
    parser.add_argument('--endpoint', default='')
    args = parser.parse_args()

    key_id = os.environ.get('OSS_ACCESS_KEY_ID')
    key_secret = os.environ.get('OSS_ACCESS_KEY_SECRET')
    if not key_id or not key_secret:
        print('请先设置环境变量 OSS_ACCESS_KEY_ID 和 OSS_ACCESS_KEY_SECRET', file=sys.stderr)
        return 1

    source = Path(args.source)
    if not source.is_dir():
        print(f'未找到目录：{source}', file=sys.stderr)
        return 1

    endpoint = args.endpoint or f'https://oss-{args.region}.aliyuncs.com'
    bucket = oss2.Bucket(oss2.Auth(key_id, key_secret), endpoint, args.bucket)
    prefix = args.prefix.strip('/')

    uploaded = skipped = 0
    for path in sorted(p for p in source.rglob('*') if p.is_file()):
        key = f'{prefix}/assets/{path.relative_to(source).as_posix()}'
        if bucket.object_exists(key):
            skipped += 1
            continue
        content_type = EXTRA_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        bucket.put_object_from_file(key, str(path), headers={'Content-Type': content_type, 'Cache-Control': CACHE_CONTROL})
        uploaded += 1
        print(f'上传 {key}')

    print(f'完成：上传 {uploaded} 个，跳过 {skipped} 个')
    return 0


if __name__ == '__main__':
    sys.exit(main())
