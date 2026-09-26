"""生成真实数据适配质量报告。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from repositories.real_data_quality import write_real_data_quality_report


if __name__ == "__main__":
    report = write_real_data_quality_report()
    print(
        "已生成质量报告："
        f"BOM关系 {report['bom_relationship_count']} 条，"
        f"库存匹配 {report['inventory_match_count']} 项。"
    )
