"""
JSON测试用例迁移脚本
将 test_cases/*.json 文件中的用例数据迁移到 SQLite 数据库

特性：
1. 迁移前自动备份所有JSON到 data/backups/json_cases_backup_<timestamp>/
2. 幂等：重复运行不会重复插入（通过name唯一索引检查）
3. 不删除旧JSON文件
4. 事务保护：每个用例独立事务，失败回滚不影响其他
"""
import json
import shutil
from datetime import datetime
from pathlib import Path


def backup_json_cases(test_cases_dir: Path, backups_dir: Path) -> Path:
    """备份所有JSON用例文件到备份目录"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = backups_dir / f'json_cases_backup_{timestamp}'

    if test_cases_dir.exists() and any(test_cases_dir.glob('*.json')):
        shutil.copytree(test_cases_dir, backup_dir, dirs_exist_ok=True)

    return backup_dir


def migrate_json_cases(db, test_cases_dir: Path, backups_dir: Path) -> dict:
    """
    执行JSON用例迁移

    Args:
        db: SQLAlchemy实例
        test_cases_dir: JSON用例目录
        backups_dir: 备份目录

    Returns:
        dict: {migrated, skipped, failed, backup_dir, errors: []}
    """
    from backend.models.test_case import TestCase, TestStep
    from backend.models.app import App

    result = {
        'migrated': 0,
        'skipped': 0,
        'failed': 0,
        'backup_dir': None,
        'errors': []
    }

    if not test_cases_dir.exists():
        return result

    # 先扫描哪些需要迁移，仅在有新用例时才创建备份
    json_files = sorted(test_cases_dir.glob('*.json'))
    if not json_files:
        return result

    # 预检查：是否有需要迁移的新用例
    needs_migration = False
    to_migrate = []
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            case_name = data.get('name', json_file.stem)
            existing = TestCase.query.filter_by(name=case_name).first()
            if not existing:
                needs_migration = True
                to_migrate.append((json_file, data))
            else:
                result['skipped'] += 1
        except Exception as e:
            result['failed'] += 1
            result['errors'].append(f'{json_file.name}: 预检查失败 {str(e)}')

    if not needs_migration:
        return result

    # 1. 仅在确实需要迁移时创建备份
    try:
        backup_dir = backup_json_cases(test_cases_dir, backups_dir)
        result['backup_dir'] = str(backup_dir)
    except Exception as e:
        result['errors'].append(f'备份失败: {e}')
        return result

    # 2. 确保有默认APP
    default_app = App.query.filter_by(package_name='default').first()
    if not default_app:
        default_app = App(
            package_name='default',
            app_name='默认应用',
            is_active=True
        )
        db.session.add(default_app)
        db.session.flush()

    # 3. 迁移需要的用例（data已在预检查中加载，无需重复读取文件）
    for json_file, data in to_migrate:
        try:
            case_name = data.get('name', json_file.stem)

            # 解析saved_at
            saved_at_str = data.get('saved_at', '')
            try:
                saved_at = datetime.strptime(saved_at_str, '%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError):
                saved_at = datetime.now()

            # 创建TestCase
            steps_data = data.get('steps', [])
            case = TestCase(
                app_id=default_app.id,
                name=case_name,
                description=f'从 {json_file.name} 迁移',
                step_count=len(steps_data),
                priority='P1',
                timeout=300,
                continue_on_failure=False,
                created_at=saved_at
            )
            db.session.add(case)
            db.session.flush()

            # 创建TestSteps
            for step_data in steps_data:
                elem = step_data.get('element')
                step = TestStep(
                    case_id=case.id,
                    step_order=step_data.get('step_order', 1),
                    action=step_data.get('action', ''),
                    action_params=json.dumps(step_data.get('action_params', {}), ensure_ascii=False),
                    description=step_data.get('description', ''),
                    elem_snapshot_data=json.dumps(elem, ensure_ascii=False) if elem else None,
                    timeout=30,
                    retry_count=1,
                    is_enabled=True,
                    created_at=saved_at
                )
                db.session.add(step)

            db.session.commit()
            result['migrated'] += 1

        except Exception as e:
            db.session.rollback()
            result['failed'] += 1
            result['errors'].append(f'{json_file.name}: {str(e)}')

    return result
