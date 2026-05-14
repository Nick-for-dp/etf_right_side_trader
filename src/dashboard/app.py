"""Streamlit 仪表盘入口。

启动方法: python main.py dashboard  或  streamlit run src/dashboard/app.py
"""

import sys
from pathlib import Path

# Streamlit 会切换工作目录到脚本所在目录，需把项目根目录加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from src.config import load_config
from src.database import init_engine
from src.service import TradingCalendarService


def main():
    st.set_page_config(
        page_title="ETF 右侧交易助手",
        page_icon="📈",
        layout="wide",
    )

    config = load_config()
    init_engine(config.db_url)

    calendar = TradingCalendarService()
    latest_trading_day = calendar.get_previous_trading_day()

    with st.sidebar:
        st.title("ETF 右侧交易助手")
        st.caption(f"最新交易日：{latest_trading_day}")
        st.divider()

    pages = st.navigation([
        st.Page("overview.py", title="市场总览", icon="📊"),
        st.Page("positions.py", title="我的持仓", icon="💼"),
        st.Page("detail.py", title="ETF 详情", icon="🔍"),
        st.Page("pnl.py", title="盈亏分析", icon="💰"),
        st.Page("comparison.py", title="策略对比", icon="⚖️"),
    ])
    pages.run()


if __name__ == "__main__":
    main()
