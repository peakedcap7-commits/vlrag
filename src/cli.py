"""CLI 交互入口"""
import sys

from src.config import CHROMA_PERSIST_DIR
from src.vectordb.text_store import load_text_store
from src.data.augmentation import load_augmented
from src.chatbot.chain import ShoppingChatbot, RetrieverType


def main():
    print("=" * 50)
    print("  Shopping QnA - 多模态 RAG 购物助手 (百炼版)")
    print("=" * 50)

    print("\n加载文本向量库...")
    try:
        text_db = load_text_store(CHROMA_PERSIST_DIR)
    except Exception as e:
        print(f"向量库加载失败: {e}")
        print("请先运行数据准备流程")
        sys.exit(1)

    print("加载增强数据...")
    try:
        products = load_augmented()
    except FileNotFoundError:
        print("增强数据不存在，请先运行 M2 数据增强")
        sys.exit(1)

    # 纯文本启动，不加载 OpenCLIP
    chatbot = ShoppingChatbot(text_db=text_db, products=products)

    print(f"\n当前检索器: text（纯文本模式，OpenCLIP 未加载）")
    print("上传图片时会自动切换 multimodal/hybrid")
    print("命令: /quit\n")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue

        if user_input == "/quit":
            print("再见！")
            break

        try:
            response = chatbot.chat(user_input)
            print(f"\n助手: {response}\n")
        except Exception as e:
            print(f"错误: {e}")


if __name__ == "__main__":
    main()
