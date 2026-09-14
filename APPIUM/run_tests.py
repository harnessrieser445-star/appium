#!/usr/bin/env python3
"""
测试运行脚本
用法:
  python run_tests.py              # 运行全部测试
  python run_tests.py unit         # 仅运行单元测试
  python run_tests.py integration  # 仅运行集成测试
  python run_tests.py -v           # 详细输出
"""
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
VENV_PYTHON = PROJECT_ROOT / 'venv' / 'Scripts' / 'python.exe'


def main():
    args = sys.argv[1:]
    verbose = '-v' in args
    args = [a for a in args if a != '-v']

    cmd = [str(VENV_PYTHON), '-m', 'pytest']

    if not args:
        cmd.append('tests/')
    elif 'unit' in args:
        cmd.append('tests/unit/')
    elif 'integration' in args:
        cmd.append('tests/integration/')
    else:
        cmd.extend(args)

    if verbose:
        cmd.extend(['-v', '--tb=short'])
    else:
        cmd.extend(['-v', '--tb=short'])

    print(f'运行命令: {" ".join(cmd)}')
    print('=' * 60)
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
