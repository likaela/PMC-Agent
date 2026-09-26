import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


# 加载.env文件
load_dotenv()


# 获取当前模型选择
provider = os.getenv("LLM_PROVIDER")


def get_llm():

    if provider == "deepseek":

        llm = ChatOpenAI(
            model="deepseek-chat",
            api_key=os.getenv(
                "DEEPSEEK_API_KEY"
            ),
            base_url=os.getenv(
                "DEEPSEEK_BASE_URL"
            ),
            temperature=0
        )

        return llm


    elif provider == "mimo":

        llm = ChatOpenAI(
            model="MiMo-V2.5",
            api_key=os.getenv(
                "MIMO_API_KEY"
            ),
            base_url=os.getenv(
                "MIMO_BASE_URL"
            ),
            temperature=0
        )

        return llm


    else:

        raise Exception(
            "没有配置LLM模型"
        )