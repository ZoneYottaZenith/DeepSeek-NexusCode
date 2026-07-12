"""
Reasonix 项目名称扫描器
======================
扫描项目中所有 "reasonix" 相关引用，分类输出详细报告。
可在改名前后各跑一次，比较结果确保没有漏改。

用法:
    python scripts\scan_reasonix.py                    # 输出完整报告
    python scripts\scan_reasonix.py --summary          # 只输出汇总
    python scripts\scan_reasonix.py --json             # 输出 JSON（便于 diff）
    python scripts\scan_reasonix.py --old snapshot.json # 跟旧快照对比
"""

import os
import re
import json
import argparse
from collections import defaultdict
from pathlib import Path

# 忽略的目录模式
IGNORE_DIRS = {
    '.git', 'node_modules', '__pycache__', '.idea', '.vscode',
    'dist', 'build', 'target', 'bin',
}

# 只扫描这些扩展名
SCAN_EXTENSIONS = {
    '.go', '.md', '.toml', '.json', '.yaml', '.yml',
    '.mod', '.sum', '.sh', '.ps1', '.bat', '.cmd',
    'Makefile', 'makefile', 'Dockerfile', 'dockerfile',
    '.yml', '.yaml', '.html', '.js', '.ts', '.jsx', '.tsx',
    '.css', '.scss', '.svelte', '.vue',
    '.env', '.env.example', '.gitignore', '.gitattributes',
    '.goreleaser.yaml', '.golangci.yml',
}

# 不扫描扩展名但文件名本身要查的文件（如 Makefile 无扩展名）
SCAN_FILENAMES = {
    'Makefile', 'makefile', 'Dockerfile', 'dockerfile',
    'go.mod', 'go.sum',
}


def should_scan_file(filepath: Path) -> bool:
    """判断文件是否应该被扫描"""
    # 检查父目录是否在忽略列表中
    for part in filepath.parts:
        if part in IGNORE_DIRS:
            return False

    # 检查扩展名
    ext = filepath.suffix.lower()
    if ext in SCAN_EXTENSIONS:
        return True

    # 检查文件名（无扩展名的特殊文件）
    if filepath.name in SCAN_FILENAMES:
        return True

    return False


def read_file_safe(filepath: Path) -> str:
    """安全读取文件，处理编码问题"""
    encodings = ['utf-8', 'utf-16', 'latin-1', 'gbk']
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    return ""


def scan_file(filepath: Path, content: str, root: Path):
    """扫描单个文件中的 reasonix 引用"""
    results = []
    rel_path = filepath.relative_to(root).as_posix()

    # --- 模式 1: 大小写敏感匹配 reasonix ---
    for i, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith('//') or stripped.startswith('#'):
            continue

        # 查找所有 reasonix 匹配
        for m in re.finditer(r'(reasonix)', line, re.IGNORECASE):
            raw = m.group(0)
            start = m.start()
            end = m.end()

            # 获取前后上下文（用于分类）
            prefix = line[:start].strip()
            suffix = line[end:].strip()

            # 分类
            category = classify_match(line, raw, start, end, prefix, suffix, rel_path)

            results.append({
                'file': rel_path,
                'line': i,
                'column': start + 1,
                'raw': raw,
                'case': 'exact' if raw == 'reasonix' else (
                    'title' if raw == 'Reasonix' else (
                        'upper' if raw == 'REASONIX' else (
                            'pascal' if raw == 'Reasonix' else 'mixed'
                        )
                    )
                ),
                'category': category,
                'context': line.strip()[:120],
            })

    return results


def classify_match(line: str, raw: str, start: int, end: int, prefix: str, suffix: str, rel_path: str) -> str:
    """将匹配分类"""
    # Go import 路径: "reasonix/internal/..."
    if re.search(r'["\'`]reasonix/', line) or re.search(r'["\'`]reasonix/',
                                                         line[max(0, start - 20):end + 20]):
        return 'go_import'

    # Go module: module reasonix
    if re.match(r'module\s+reasonix', line.strip()):
        return 'go_module'

    # Go replace: replace reasonix => ...
    if re.match(r'replace\s+reasonix', line.strip()):
        return 'go_replace'

    # Go require: require reasonix
    if re.match(r'require\s+reasonix', line.strip()):
        return 'go_require'

    # 环境变量: REASONIX_*
    if '_REASONIX' in line or raw == 'REASONIX':
        return 'env_var'

    # 路径: reasonix.toml, .reasonix/
    if 'reasonix.' in line or '.reasonix' in line:
        return 'config_path'

    # URL/链接
    if 'github.com' in line or 'http' in line:
        return 'url'

    # NPM 包名
    if 'npm' in line or 'package' in line:
        return 'npm'

    # 包声明: package reasonix
    if re.match(r'package\s+reasonix\b', line.strip()):
        return 'go_package_decl'

    # 二进制安装路径/命令
    if rel_path.endswith('README.md') or rel_path.endswith('README.zh-CN.md'):
        return 'readme'

    # 在双引号/反引号字符串中
    if raw in line and ('"' in line or '`' in line or "'" in line):
        return 'string_literal'

    # 默认
    if rel_path.endswith('.go'):
        return 'go_other'
    return 'other'


def scan_directory(root: Path) -> dict:
    """扫描整个项目目录"""
    summary = {
        'project_root': str(root),
        'total_files_scanned': 0,
        'total_files_with_hits': 0,
        'total_matches': 0,
        'by_category': defaultdict(int),
        'by_case': defaultdict(int),
        'by_extension': defaultdict(int),
        'by_directory': defaultdict(int),
        'files_with_hits': [],
        'results': [],
    }

    for filepath in sorted(root.rglob('*')):
        # 只处理文件
        if not filepath.is_file():
            continue
        if not should_scan_file(filepath):
            continue

        rel_path = filepath.relative_to(root).as_posix()
        ext = filepath.suffix.lower() or filepath.name

        content = read_file_safe(filepath)
        if not content:
            continue

        # 快速过滤：不含 reasonix 的文件直接跳过
        if 'reasonix' not in content.lower():
            continue

        summary['total_files_scanned'] += 1
        hits = scan_file(filepath, content, root)

        if hits:
            summary['total_files_with_hits'] += 1
            summary['total_matches'] += len(hits)
            summary['files_with_hits'].append({
                'file': rel_path,
                'count': len(hits),
            })

            for h in hits:
                summary['results'].append(h)
                summary['by_category'][h['category']] += 1
                summary['by_case'][h['case']] += 1
                summary['by_extension'][ext] += 1

                # 按顶层目录归类
                top_dir = rel_path.split('/')[0] if '/' in rel_path else '(root)'
                summary['by_directory'][top_dir] += 1

    return summary


def print_report(summary: dict, old_snapshot: dict = None):
    """打印格式化的报告"""
    root = summary['project_root']
    print(f"{'='*70}")
    print(f"  Reasonix 引用扫描报告")
    print(f"  项目路径: {root}")
    print(f"{'='*70}\n")

    # 总览
    print(f"📊 总览")
    print(f"  ├─ 扫描文件数:       {summary['total_files_scanned']}")
    print(f"  ├─ 含引用的文件数:    {summary['total_files_with_hits']}")
    print(f"  └─ 总匹配数:         {summary['total_matches']}")
    print()

    # 分类统计
    print(f"📂 按分类")
    cat_order = sorted(summary['by_category'].items(), key=lambda x: -x[1])
    for cat, count in cat_order:
        label = {
            'go_import': 'Go import 路径 (reasonix/internal/...)',
            'go_module': 'Go module 声明 (module reasonix)',
            'go_replace': 'Go replace 指令',
            'go_require': 'Go require 指令',
            'go_package_decl': 'Go package 声明',
            'go_other': 'Go 文件其他引用',
            'string_literal': '字符串常量',
            'env_var': '环境变量 (REASONIX_*)',
            'config_path': '配置路径 (reasonix.toml 等)',
            'url': 'URL/链接',
            'npm': 'NPM 包引用',
            'readme': 'README 文档',
            'other': '其他',
        }.get(cat, cat)
        arrow = '├─' if count != cat_order[-1][1] else '└─'
        print(f"  {arrow} {label}: {count}")
    print()

    # 大小写分布
    print(f"🔤 按大小写")
    for case, count in sorted(summary['by_case'].items(), key=lambda x: -x[1]):
        label = {'exact': 'reasonix (全小写)', 'title': 'Reasonix (首字母大写)',
                 'upper': 'REASONIX (全大写)', 'pascal': 'Reasonix',
                 'mixed': '混合大小写'}.get(case, case)
        arrow = '├─' if case != list(summary['by_case'].keys())[-1] else '└─'
        print(f"  {arrow} {label}: {count}")
    print()

    # 按文件类型
    print(f"📁 按文件类型")
    for ext, count in sorted(summary['by_extension'].items(), key=lambda x: -x[1]):
        arrow = '├─' if ext != list(summary['by_extension'].keys())[-1] else '└─'
        print(f"  {arrow} {ext}: {count}")
    print()

    # 按目录分布
    print(f"📁 按顶层目录分布")
    for d, count in sorted(summary['by_directory'].items(), key=lambda x: -x[1]):
        arrow = '├─' if d != list(summary['by_directory'].keys())[-1] else '└─'
        print(f"  {arrow} {d}: {count}")
    print()

    # 含引用的文件列表
    print(f"📄 含引用的文件（按匹配数排序）")
    sorted_files = sorted(summary['files_with_hits'], key=lambda x: -x['count'])
    for i, f in enumerate(sorted_files[:30]):
        arrow = '├─' if i < len(sorted_files[:30]) - 1 else '└─'
        print(f"  {arrow} {f['file']}: {f['count']} 处")
    if len(sorted_files) > 30:
        print(f"  ... 还有 {len(sorted_files) - 30} 个文件")
    print()

    # 与旧快照对比
    if old_snapshot:
        print(f"🔄 与旧快照对比")
        old_total = old_snapshot.get('total_matches', 0)
        new_total = summary['total_matches']
        diff = old_total - new_total
        if diff == 0:
            print(f"  ✅ 匹配数一致: {old_total} → {new_total}")
        else:
            print(f"  ⚠️ 匹配数变化: {old_total} → {new_total} (差 {diff:+d})")

        # 对比分类变化
        print(f"  分类变化:")
        all_cats = set(list(summary['by_category'].keys()) + list(old_snapshot.get('by_category', {}).keys()))
        for cat in sorted(all_cats):
            old_c = old_snapshot.get('by_category', {}).get(cat, 0)
            new_c = summary['by_category'].get(cat, 0)
            if old_c != new_c:
                print(f"    {cat}: {old_c} → {new_c}")

        # 对比文件变化
        old_files = {f['file'] for f in old_snapshot.get('files_with_hits', [])}
        new_files = {f['file'] for f in summary['files_with_hits']}
        removed = old_files - new_files
        added = new_files - old_files
        if removed:
            print(f"  ❌ 减少的文件:")
            for f in sorted(removed):
                print(f"    - {f}")
        if added:
            print(f"  🆕 新增的文件:")
            for f in sorted(added):
                print(f"    + {f}")
    print()

    # 详细结果（按文件分组）
    print(f"🔍 详细匹配列表（按文件）")
    by_file = defaultdict(list)
    for r in summary['results']:
        by_file[r['file']].append(r)

    for filepath, hits in sorted(by_file.items()):
        print(f"\n  📄 {filepath} ({len(hits)} 处)")
        for h in hits:
            print(f"    L{h['line']}:{h['column']} "
                  f"[{h['raw']}] [{h['case']}] [{h['category']}] "
                  f"→ {h['context'][:80]}")


def main():
    parser = argparse.ArgumentParser(description='Reasonix 项目名称引用扫描器')
    parser.add_argument('--root', default=None,
                        help='项目根目录（默认自动向上查找）')
    parser.add_argument('--summary', action='store_true',
                        help='只输出汇总')
    parser.add_argument('--json', action='store_true',
                        help='输出 JSON（便于程序处理）')
    parser.add_argument('--output', '-o', default=None,
                        help='将快照保存到文件')
    parser.add_argument('--old', default=None,
                        help='与旧快照 JSON 文件对比')
    args = parser.parse_args()

    # 确定项目根目录
    if args.root:
        root = Path(args.root).resolve()
    else:
        # 从脚本位置向上查找
        script_dir = Path(__file__).resolve().parent
        root = script_dir.parent  # 项目根目录

    if not root.exists():
        print(f"错误: 目录不存在 {root}")
        return 1

    # 扫描
    print(f"正在扫描 {root} ...")
    summary = scan_directory(root)

    # 加载旧快照
    old_snapshot = None
    if args.old:
        try:
            with open(args.old, 'r', encoding='utf-8') as f:
                old_snapshot = json.load(f)
            print(f"已加载旧快照: {args.old}")
        except Exception as e:
            print(f"警告: 无法加载旧快照 {args.old}: {e}")

    # 输出
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif args.summary:
        print(f"文件数: {summary['total_files_with_hits']}/{summary['total_files_scanned']}")
        print(f"匹配总数: {summary['total_matches']}")
        for cat, cnt in sorted(summary['by_category'].items(), key=lambda x: -x[1]):
            print(f"  {cat}: {cnt}")
    else:
        print_report(summary, old_snapshot)

    # 保存快照
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"快照已保存: {args.output}")

    return 0


if __name__ == '__main__':
    exit(main())
