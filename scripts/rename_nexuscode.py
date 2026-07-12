"""
Reasonix → NexusCode 项目重命名脚本
=====================================
用法:
    uv run scripts\rename_reasonix.py          # 预览模式（只打印不改）
    uv run scripts\rename_reasonix.py --apply  # 实际执行修改
    uv run scripts\rename_reasonix.py --apply --no-backup  # 执行且不备份

工作流程:
    1. 扫描所有文件，替换内容中的 reasonix → nexuscode
    2. 重命名包含 reasonix 的文件/目录
    3. 生成 backup 目录，方便回滚
"""

import os
import re
import json
import shutil
import argparse
from pathlib import Path
from collections import defaultdict

# ─── 忽略的目录 ───
IGNORE_DIRS = {
    '.git', 'node_modules', '__pycache__', '.idea', '.vscode',
    'dist', 'build', 'target', 'bin', '.reasonix',
    '.signpath', '.githooks',
}

# ─── 要扫描的扩展名 ───
SCAN_EXTENSIONS = {
    '.go', '.md', '.toml', '.json', '.yaml', '.yml',
    '.mod', '.sum', '.sh', '.ps1', '.bat', '.cmd',
    '.html', '.js', '.ts', '.jsx', '.tsx',
    '.css', '.scss', '.svelte', '.vue',
    '.env', '.env.example', '.gitignore', '.gitattributes',
}

SCAN_FILENAMES = {
    'Makefile', 'go.mod', 'go.sum',
}


# ─── 替换规则 ───
# 顺序重要：先长后短，避免部分重叠
REPLACE_RULES = [
    # 全大写（环境变量、常量）
    ('REASONIX', 'NEXUSCODE'),

    # 首字母大写（品牌名、标题、包名）
    ('Reasonix', 'NexusCode'),

    # 全小写（import 路径、模块名、二进制名）
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


def replace_content(text: str) -> tuple[str, int]:
    """替换文本内容中的所有 reasonix 变体，返回(新文本,替换次数)"""
    count = 0
    for old, new in REPLACE_RULES:
        new_text, c = re.subn(re.escape(old), new, text)
        count += c
        text = new_text
    # 二次处理：确保 "nexuscode" 没有被错误替换为 "nexusCode" 或类似
    # 这个正则修复 "Reasonix" → "NexusCode" 后可能遗留的问题
    return text, count


def count_matches(text: str) -> int:
    """统计文本中 reasonix 的出现次数（用于对比）"""
    return len(re.findall(r'reasonix', text, re.IGNORECASE))


def backup_file(filepath: Path, backup_root: Path) -> Path | None:
    """备份文件到 backup 目录"""
    try:
        rel = filepath.relative_to(backup_root.parent if backup_root.parent.name == 'scripts' else backup_root)
    except ValueError:
        rel = filepath.name
    backup_path = backup_root / rel
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(filepath, backup_path)
    return backup_path


def rename_file_or_dir(path: Path, dry_run: bool, rename_log: list) -> Path | None:
    """重命名包含 reasonix 的文件/目录"""
    name = path.name
    new_name = name
    for old, new in REPLACE_RULES:
        if old in new_name:
            new_name = new_name.replace(old, new)

    if new_name == name:
        return None

    new_path = path.parent / new_name

    if not dry_run:
        try:
            # 如果目标已存在，先删掉（避免冲突）
            if new_path.exists():
                if new_path.is_dir():
                    shutil.rmtree(new_path)
                else:
                    new_path.unlink()
            path.rename(new_path)
        except Exception as e:
            print(f"  ⚠️  重命名失败: {path.name} → {new_name}: {e}")
            return None

    rename_log.append({'old': str(path), 'new': str(new_path)})
    return new_path


def collect_all_files(root: Path) -> list[Path]:
    """收集所有需要处理的文件"""
    files = []
    for filepath in sorted(root.rglob('*')):
        if not filepath.is_file():
            continue
        if should_skip_dir(filepath):
            continue
        if should_scan_file(filepath):
            files.append(filepath)
    return files


def process(root: Path, dry_run: bool, no_backup: bool, verify: bool):
    """主处理流程"""
    root = root.resolve()
    backup_root = root / 'scripts' / '.rename_backup'

    if not dry_run and not no_backup:
        if backup_root.exists():
            shutil.rmtree(backup_root)
        backup_root.mkdir(parents=True, exist_ok=True)
        print(f"📦 备份目录: {backup_root}")

    # ─── 第一阶段：扫描所有文件 ───
    print(f"\n🔍 扫描文件...")
    all_files = collect_all_files(root)
    print(f"   共 {len(all_files)} 个文件")

    # ─── 第二阶段：内容替换 ───
    print(f"\n📝 内容替换...")
    content_changes = []
    content_total = 0

    for filepath in all_files:
        if should_skip_dir(filepath):
            continue

        result = read_file_safe(filepath)
        if result is None:
            print(f"  ⚠️  无法读取: {filepath.relative_to(root)}")
            continue

        content, encoding = result

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
            content_changes.append({'file': str(rel), 'count': c})
            content_total += c
            print(f"  {'🔧' if not dry_run else '🔍'} {rel}: {c} 处替换")
        elif c > 0 and after_count > 0:
            rel = filepath.relative_to(root)
            print(f"  ⚠️  替换后仍有残留: {rel} (剩余 {after_count} 处)")

    print(f"\n  内容替换总计: {content_total} 处 ({len(content_changes)} 个文件)")

    # ─── 第三阶段：文件/目录重命名 ───
    print(f"\n📁 文件/目录重命名...")

    # 先收集所有路径，从深层到浅层排序
    rename_candidates = []
    for filepath in sorted(root.rglob('*'), key=lambda p: -len(p.parts)):
        if should_skip_dir(filepath):
            continue
        # 检查路径中任何部分是否包含 reasonix
        if any('reasonix' in part.lower() for part in filepath.parts):
            rename_candidates.append(filepath)

    rename_log = []
    rename_count = 0
    for path in rename_candidates:
        new_path = rename_file_or_dir(path, dry_run, rename_log)
        if new_path:
            rename_count += 1
            rel_old = path.relative_to(root)
            rel_new = new_path.relative_to(root.parent)  # 相对父级显示
            print(f"  {'📎' if not dry_run else '🔍'} {rel_old} → {new_path.name}")

    print(f"\n  重命名总计: {rename_count} 项")

    # ─── 第四阶段：go.sum 清理（需要重新生成） ───
    go_sum = root / 'go.sum'
    if go_sum.exists() and not dry_run:
        os.remove(go_sum)
        print(f"\n🗑️  已删除 go.sum（下次 go build 时会重新生成）")

    desktop_go_sum = root / 'desktop' / 'go.sum'
    if desktop_go_sum.exists() and not dry_run:
        os.remove(desktop_go_sum)
        print(f"🗑️  已删除 desktop/go.sum（下次 go build 时会重新生成）")

    # ─── 第五阶段：总结 ───
    print(f"\n{'='*60}")
    if dry_run:
        print(f"  🔍 预览模式完成（未做任何修改）")
        print(f"  加上 --apply 执行实际修改")
    else:
        print(f"  ✅ 重命名完成！")
        print(f"  备份目录: {backup_root}")
    print(f"  内容替换: {content_total} 处 ({len(content_changes)} 个文件)")
    print(f"  文件重命名: {rename_count} 项")
    print(f"{'='*60}")

    if not dry_run and verify:
        print(f"\n🔎 运行验证扫描...")
        os.system(f'uv run scripts\\scan_reasonix.py --old scripts\\scan_before.json')

    return {
        'content_changes': content_changes,
        'content_total': content_total,
        'rename_log': rename_log,
        'rename_count': rename_count,
    }


def main():
    parser = argparse.ArgumentParser(description='Reasonix → NexusCode 项目重命名')
    parser.add_argument('--apply', action='store_true',
                        help='执行修改（缺省为预览模式，只打印不改）')
    parser.add_argument('--no-backup', action='store_true',
                        help='不创建备份（默认会自动备份）')
    parser.add_argument('--root', default=None,
                        help='项目根目录（缺省自动检测）')
    parser.add_argument('--verify', action='store_true',
                        help='改完后自动运行 --old 对比验证')
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
    print(f"  {mode}: Reasonix → NexusCode")
    print(f"  项目路径: {root}")
    if not args.apply:
        print(f"  不会修改任何文件，加上 --apply 执行")
    print(f"{'='*60}")

    process(root, dry_run=not args.apply, no_backup=args.no_backup, verify=args.verify)

    return 0


if __name__ == '__main__':
    exit(main())
