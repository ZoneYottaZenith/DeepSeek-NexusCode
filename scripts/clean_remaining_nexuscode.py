"""
清理项目中所有残留的 reasonix 引用（第二轮）
=========================================
处理上一轮改名脚本遗漏的文件：
  - site/ 网站页面
  - npm/ NPM 发布脚本
  - workers/ Cloudflare Workers SQL
  - .gitignore / LICENSE / .env.example
  - 辅助脚本中的说明文字

用法:
    uv run scripts\clean_remaining_nexuscode.py          # 预览
    uv run scripts\clean_remaining_nexuscode.py --apply  # 执行
    uv run scripts\clean_remaining_nexuscode.py --apply --no-backup
"""

import os
import re
import shutil
import argparse
from pathlib import Path
from collections import defaultdict

# ─── 忽略的目录 ───
IGNORE_DIRS = {
    '.git', 'node_modules', '__pycache__', '.idea', '.vscode',
    'dist', 'target', 'bin', '.reasonix',
    '.signpath', '.githooks', '.rename_backup', '.clean_backup',
}
# 'build' 故意不在其中——desktop/build/ 下的安装包配置也需要处理

# ─── 要处理的扩展名 ───
SCAN_EXTENSIONS = {
    '.go', '.md', '.toml', '.json', '.yaml', '.yml',
    '.mod', '.sum', '.sh', '.ps1', '.bat', '.cmd',
    '.html', '.js', '.ts', '.jsx', '.tsx', '.mjs',
    '.css', '.scss', '.svelte', '.vue', '.astro',
    '.env', '.env.example', '.gitignore', '.gitattributes',
    '.sql', '.txt', '.example',
    '.svg', '.desktop', '.nsi', '.m', '.nsis', '.yaml',
}

SCAN_FILENAMES = {
    'Makefile', 'go.mod', 'go.sum', 'LICENSE',
    'prod_test', 'prod_fast_test', 'dev',
    '.env.example',  # Python suffix 只取最后一段，.env.example 的 suffix 是 .example
}

# ─── 替换规则（按优先级排序） ───
#  这些规则专门处理文件名/路径中的 reasonix，以及第一轮漏掉的引用
REPLACE_RULES = [
    # 特定域名
    ('reasonix.io', 'nexuscode.io'),
    ('reasonix-crash', 'nexuscode-crash'),
    ('reasonix-forum', 'nexuscode-forum'),
    ('reasonix-accounts', 'nexuscode-accounts'),

    # NPM 包名
    ('@reasonix/cli', '@nexuscode/cli'),

    # GitHub 仓库
    ('esengine/DeepSeek-Reasonix', '你的仓库/DeepSeek-NexusCode'),
    ('esengine/nexuscode', '你的仓库/nexuscode'),

    # 大小写变体（顺序重要：先长后短）
    ('REASONIX', 'NEXUSCODE'),
    ('Reasonix', 'NexusCode'),
    ('reasonix', 'nexuscode'),
]


def should_skip_dir(path: Path) -> bool:
    for part in path.parts:
        if part in IGNORE_DIRS:
            return True
    return False


def should_scan_file(filepath: Path) -> bool:
    ext = filepath.suffix.lower()
    if ext in SCAN_EXTENSIONS:
        return True
    if filepath.name in SCAN_FILENAMES:
        return True
    return False


def read_file_safe(filepath: Path) -> tuple[str, str] | None:
    encodings = [('utf-8', 'utf-8'), ('utf-8-sig', 'utf-8-sig'),
                 ('utf-16', 'utf-16'), ('gbk', 'gbk'), ('latin-1', 'latin-1')]
    for enc_name, _ in encodings:
        try:
            with open(filepath, 'r', encoding=enc_name, newline='') as f:
                return f.read(), enc_name
        except (UnicodeDecodeError, UnicodeError):
            continue
    return None


def count_matches(text: str) -> int:
    """统计文本中 reasonix 的出现次数"""
    return len(re.findall(r'reasonix', text, re.IGNORECASE))


def replace_content(text: str) -> tuple[str, int]:
    """替换文本内容中的所有 reasonix 变体"""
    count = 0
    for old, new in REPLACE_RULES:
        new_text, c = re.subn(re.escape(old), new, text, flags=re.IGNORECASE)
        count += c
        text = new_text
    return text, count


def backup_file(filepath: Path, backup_root: Path) -> Path | None:
    try:
        rel = filepath.relative_to(backup_root.parent.parent)
    except ValueError:
        rel = filepath.name
    backup_path = backup_root / rel
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(filepath, backup_path)
    return backup_path


def process(root: Path, dry_run: bool, no_backup: bool):
    root = root.resolve()
    backup_root = root / 'scripts' / '.clean_backup'

    if not dry_run and not no_backup:
        if backup_root.exists():
            shutil.rmtree(backup_root)
        backup_root.mkdir(parents=True, exist_ok=True)
        print(f"📦 备份目录: {backup_root}")

    # ─── 第一阶段：扫描所有文件 ───
    print(f"\n🔍 扫描文件...")
    all_files = []
    for filepath in sorted(root.rglob('*')):
        if not filepath.is_file():
            continue
        if should_skip_dir(filepath):
            continue
        # 跳过脚本自己的备份目录
        if '.clean_backup' in filepath.parts:
            continue
        if should_scan_file(filepath):
            all_files.append(filepath)

    print(f"   共 {len(all_files)} 个文件")

    # ─── 第二阶段：内容替换 ───
    print(f"\n📝 内容替换...")
    content_total = 0
    content_files = 0

    for filepath in all_files:
        result = read_file_safe(filepath)
        if result is None:
            continue

        content, _ = result

        before_count = count_matches(content)
        if before_count == 0:
            continue

        new_content, c = replace_content(content)
        after_count = count_matches(new_content)

        if c > 0 and after_count == 0:
            if not dry_run:
                if not no_backup:
                    backup_file(filepath, backup_root)
                with open(filepath, 'w', encoding='utf-8', newline='') as f:
                    f.write(new_content)

            rel = filepath.relative_to(root)
            content_total += c
            content_files += 1
            print(f"  {'🔧' if not dry_run else '🔍'} {rel}: {c} 处替换")
        elif c > 0 and after_count > 0:
            rel = filepath.relative_to(root)
            print(f"  ⚠️  替换后仍有残留: {rel} ({before_count}→{after_count})")

    print(f"\n  内容替换总计: {content_total} 处 ({content_files} 个文件)")

    # ─── 第三阶段：重命名仍含 reasonix 的文件 ───
    print(f"\n📁 文件重命名...")
    rename_count = 0

    for filepath in sorted(root.rglob('*'), key=lambda p: -len(p.parts)):
        if should_skip_dir(filepath) or not filepath.is_file():
            continue
        if '.clean_backup' in filepath.parts:
            continue

        name = filepath.name
        new_name = name
        for old, new in REPLACE_RULES:
            if old.lower() in new_name.lower():
                # 保持大小写风格
                if old == 'reasonix' and new == 'nexuscode':
                    new_name = new_name.replace('reasonix', 'nexuscode')
                    new_name = new_name.replace('Reasonix', 'NexusCode')
                    new_name = new_name.replace('REASONIX', 'NEXUSCODE')
                elif old in new_name:
                    new_name = new_name.replace(old, new)

        if new_name == name:
            continue

        new_path = filepath.parent / new_name

        if not dry_run:
            if new_path.exists():
                new_path.unlink()
            filepath.rename(new_path)

        rename_count += 1
        print(f"  {'📎' if not dry_run else '🔍'} {name} → {new_name}")

    print(f"\n  文件重命名总计: {rename_count} 项")

    # ─── 总结 ───
    print(f"\n{'='*60}")
    if dry_run:
        print(f"  🔍 预览模式完成（未做任何修改）")
        print(f"  加上 --apply 执行实际修改")
    else:
        print(f"  ✅ 清理完成！")
        if not no_backup:
            print(f"  备份目录: {backup_root}")
    print(f"  内容替换: {content_total} 处 ({content_files} 个文件)")
    print(f"  文件重命名: {rename_count} 项")
    print(f"{'='*60}")

    # ─── 验证：跑扫描脚本对比 ───
    if not dry_run:
        scan_script = root / 'scripts' / 'scan_nexuscode.py'
        before_snapshot = root / 'scripts' / 'scan_before.json'
        if scan_script.exists() and before_snapshot.exists():
            print(f"\n🔎 运行验证扫描...")
            import subprocess
            subprocess.run([
                'uv', 'run', str(scan_script),
                '--old', str(before_snapshot),
                '--summary'
            ], cwd=root)

    return content_total, rename_count


def main():
    parser = argparse.ArgumentParser(description='清理项目中残留的 reasonix 引用')
    parser.add_argument('--apply', action='store_true',
                        help='执行修改（缺省为预览模式）')
    parser.add_argument('--no-backup', action='store_true',
                        help='不创建备份')
    parser.add_argument('--root', default=None,
                        help='项目根目录')
    args = parser.parse_args()

    if args.root:
        root = Path(args.root).resolve()
    else:
        root = Path(__file__).resolve().parent.parent

    if not root.exists():
        print(f"错误: 目录不存在 {root}")
        return 1

    mode = "🔍 预览模式" if not args.apply else "⚡ 执行模式"
    print(f"{'='*60}")
    print(f"  {mode}: 清理残留 reasonix 引用")
    print(f"  项目路径: {root}")
    print(f"{'='*60}")

    process(root, dry_run=not args.apply, no_backup=args.no_backup)

    return 0


if __name__ == '__main__':
    exit(main())
