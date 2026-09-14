#!/usr/bin/env python
"""
环境自检脚本（Phase 0 基础版）
检测项目运行所需的基础环境是否就绪

检测项:
1. Python版本
2. pip依赖（requirements.txt中声明的包）
3. 项目目录结构
4. ADB是否存在
5. ADB设备连接状态
"""
import sys
import subprocess
from pathlib import Path
from importlib import metadata


# 颜色输出（Windows终端兼容）
class Color:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_ok(msg: str):
    print(f'  {Color.GREEN}[OK]{Color.END} {msg}')


def print_warn(msg: str):
    print(f'  {Color.YELLOW}[WARN]{Color.END} {msg}')


def print_fail(msg: str):
    print(f'  {Color.RED}[FAIL]{Color.END} {msg}')


def print_info(msg: str):
    print(f'  {Color.BLUE}[INFO]{Color.END} {msg}')


def check_python_version() -> bool:
    """检查Python版本 >= 3.10"""
    print(f'\n{Color.BOLD}[1] Python版本检查{Color.END}')
    version = sys.version_info
    version_str = f'{version.major}.{version.minor}.{version.micro}'
    print_info(f'当前Python版本: {version_str}')
    print_info(f'Python路径: {sys.executable}')

    if version.major >= 3 and version.minor >= 10:
        print_ok(f'Python版本满足要求 (>= 3.10)')
        return True
    else:
        print_fail(f'Python版本过低，需要 >= 3.10，当前 {version_str}')
        return False


def check_pip_dependencies() -> bool:
    """检查requirements.txt中的依赖是否已安装"""
    print(f'\n{Color.BOLD}[2] pip依赖检查{Color.END}')
    root_dir = Path(__file__).resolve().parent
    req_file = root_dir / 'requirements.txt'

    if not req_file.exists():
        print_warn('requirements.txt 不存在，跳过依赖检查')
        return True

    all_ok = True
    with open(req_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # 解析包名（去掉版本号）
            pkg_name = line.split('>=')[0].split('==')[0].split('~=')[0].split('<')[0].split('>')[0].strip()

            try:
                dist = metadata.distribution(pkg_name)
                print_ok(f'{pkg_name} == {dist.version}')
            except metadata.PackageNotFoundError:
                print_fail(f'{pkg_name} 未安装 (需要: {line})')
                all_ok = False

    return all_ok


def check_project_directories() -> bool:
    """检查项目必要目录是否存在"""
    print(f'\n{Color.BOLD}[3] 项目目录检查{Color.END}')
    root_dir = Path(__file__).resolve().parent
    all_ok = True

    required_dirs = [
        ('templates', '前端模板目录'),
        ('static', '前端静态资源目录'),
        ('static/css', 'CSS目录'),
        ('static/js', 'JavaScript目录'),
        ('bin', 'ADB工具目录'),
        ('drivers', '驱动层代码目录'),
        ('services', '服务层代码目录'),
        ('backend', '后端代码目录（重构后）'),
        ('backend/utils', '工具模块目录（重构后）'),
    ]

    required_files = [
        ('app.py', 'Flask主入口'),
        ('config.yaml', '配置文件'),
        ('requirements.txt', '依赖清单'),
    ]

    for dirname, desc in required_dirs:
        p = root_dir / dirname
        if p.exists() and p.is_dir():
            print_ok(f'{dirname}/ - {desc}')
        else:
            print_warn(f'{dirname}/ - {desc} 不存在')
            # 非关键目录不标记为失败

    for filename, desc in required_files:
        p = root_dir / filename
        if p.exists() and p.is_file():
            print_ok(f'{filename} - {desc}')
        else:
            print_fail(f'{filename} - {desc} 不存在')
            all_ok = False

    # data目录（自动创建）
    data_dir = root_dir / 'data'
    if not data_dir.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        print_info(f'data/ 目录已自动创建')
    else:
        print_ok('data/ - 数据目录')

    for sub in ['screenshots', 'test_screenshots', 'generated_scripts', 'logs', 'backups', 'exports']:
        sub_dir = data_dir / sub
        if not sub_dir.exists():
            sub_dir.mkdir(parents=True, exist_ok=True)

    return all_ok


def check_adb() -> bool:
    """检查ADB是否存在"""
    print(f'\n{Color.BOLD}[4] ADB检查{Color.END}')
    root_dir = Path(__file__).resolve().parent
    adb_path = root_dir / 'bin' / 'adb.exe'

    if not adb_path.exists():
        print_fail(f'ADB不存在: {adb_path}')
        return False

    print_ok(f'ADB路径: {adb_path}')

    try:
        result = subprocess.run(
            [str(adb_path), 'version'],
            capture_output=True, text=True, timeout=10, encoding='utf-8'
        )
        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0] if result.stdout else 'unknown'
            print_ok(f'ADB版本: {version_line}')
            return True
        else:
            print_fail(f'ADB执行失败: {result.stderr}')
            return False
    except Exception as e:
        print_fail(f'ADB执行异常: {e}')
        return False


def check_adb_devices() -> bool:
    """检查ADB设备连接状态"""
    print(f'\n{Color.BOLD}[5] ADB设备连接检查{Color.END}')
    root_dir = Path(__file__).resolve().parent
    adb_path = root_dir / 'bin' / 'adb.exe'

    if not adb_path.exists():
        print_warn('ADB不存在，跳过设备检查')
        return True  # 不阻塞，因为支持模拟模式

    try:
        result = subprocess.run(
            [str(adb_path), 'devices'],
            capture_output=True, text=True, timeout=10, encoding='utf-8'
        )
        if result.returncode != 0:
            print_warn(f'adb devices 执行失败: {result.stderr}')
            return True

        lines = result.stdout.strip().split('\n')
        devices = []
        for line in lines[1:]:  # 跳过第一行 "List of devices attached"
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                devices.append((parts[0], parts[1]))

        if not devices:
            print_warn('未检测到已连接的Android设备（可使用模拟模式）')
            print_info('如需连接设备，请使用USB连接并开启USB调试，或通过WiFi配对')
            return True  # 无设备不视为失败
        else:
            online_devices = [(udid, status) for udid, status in devices if status == 'device']
            offline_devices = [(udid, status) for udid, status in devices if status != 'device']

            for udid, status in online_devices:
                print_ok(f'设备已连接: {udid} ({status})')
            for udid, status in offline_devices:
                print_warn(f'设备状态异常: {udid} ({status})')

            if online_devices:
                return True
            else:
                print_warn('无在线设备，但ADB正常')
                return True

    except Exception as e:
        print_warn(f'设备检查异常: {e}')
        return True


def main():
    """主入口"""
    print(f'\n{Color.BOLD}{"="*60}{Color.END}')
    print(f'{Color.BOLD}  Appium自动化测试平台 - 环境自检{Color.END}')
    print(f'{Color.BOLD}{"="*60}{Color.END}')

    results = []
    results.append(('Python版本', check_python_version()))
    results.append(('pip依赖', check_pip_dependencies()))
    results.append(('项目目录', check_project_directories()))
    results.append(('ADB工具', check_adb()))
    results.append(('ADB设备', check_adb_devices()))

    # 汇总
    print(f'\n{Color.BOLD}{"="*60}{Color.END}')
    print(f'{Color.BOLD}  检查结果汇总{Color.END}')
    print(f'{Color.BOLD}{"="*60}{Color.END}')

    passed = sum(1 for _, ok in results if ok)
    total = len(results)

    for name, ok in results:
        if ok:
            print(f'  {Color.GREEN}PASS{Color.END}  {name}')
        else:
            print(f'  {Color.RED}FAIL{Color.END}  {name}')

    print(f'\n{Color.BOLD}总计: {passed}/{total} 项通过{Color.END}')

    if passed == total:
        print(f'\n{Color.GREEN}{Color.BOLD}环境检查全部通过！可以启动应用。{Color.END}')
        print_info('启动命令: venv\\Scripts\\python.exe app.py')
        return 0
    else:
        print(f'\n{Color.RED}{Color.BOLD}存在 {total - passed} 项未通过，请修复后再启动。{Color.END}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
