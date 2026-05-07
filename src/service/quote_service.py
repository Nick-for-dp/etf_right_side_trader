"""行情查询业务编排：在 repo 单表 CRUD 之上提供业务级查询。"""

from datetime import date

from src.database import quote_repo


class QuoteService:
    """行情查询服务，封装跨 repo 的数据聚合逻辑。"""

    @staticmethod
    def find_max_close_between(code: str, start: date, end: date) -> float | None:
        """查询区间最高收盘价。

        Args:
            code:  ETF 代码
            start: 起始日期（含）
            end:   结束日期（含）

        Returns:
            区间最高收盘价，无数据时返回 None
        """
        quotes = quote_repo.find_by_code_between(code, start, end)
        if not quotes:
            return None
        return max(q.close for q in quotes)
