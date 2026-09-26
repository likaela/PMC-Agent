from config import get_llm

from langchain.agents import create_agent


# 获取DeepSeek
llm = get_llm()


# 注册工具
from tools.agent_tools import (
    bom_check,
    inventory_check,
    purchase_check
)


tools=[

    bom_check,

    inventory_check,

    purchase_check

]

# 创建Agent

agent = create_agent(
    model=llm,
    tools=tools,
    system_prompt="""

你是制造业PMC智能助手。

你的工作流程：

1. 用户提出生产需求
2. 必须先调用BOM工具计算物料需求
3. 调用库存工具检查库存
4. 如果存在缺料：
   必须调用采购建议工具
5. 输出完整PMC分析报告


注意：

- 所有数量计算必须调用工具
- 不允许自行估算


"""
)



result = agent.invoke(
    {
        "messages": [
            {
                "role": "user",
                "content": "我要生产1000台ABC-1000，现在库存够不够？如果缺料，请给出采购建议。"
            }
        ]
    }
)


answer = result["messages"][-1].content


print("\n")
print("="*60)
print("        PMC智能生产分析报告")
print("="*60)

print(answer)

print("="*60)
