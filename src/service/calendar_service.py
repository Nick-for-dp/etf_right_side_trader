"""A 股交易日历服务，基于 exchange_calendars 库。"""

import exchange_calendars as xcals
import pandas as pd

from datetime import date as date_type, datetime, timedelta
from typing import Any, List, Optional


class TradingCalendarService:
    """A 股交易日历服务，支持上交所 (XSHG) 和深交所 (XSHE)。"""

    def __init__(self, exchange: str = "XSHG", cache_years: int = 5):
        """初始化交易日历并预加载缓存。

        Args:
            exchange: 交易所代码，'XSHG'（上交所）或 'XSHE'（深交所）
            cache_years: 预加载未来/过去几年的日历数据到缓存
        """
        self.exchange = exchange
        self.cal = xcals.get_calendar(exchange)

        current_year = datetime.now().year
        self._cache_start_year = current_year - cache_years
        self._cache_end_year = current_year

        self._trading_days_set: set[str] = set()
        self._trading_days_list: list[str] = []
        self._load_sessions(self._cache_start_year, self._cache_end_year)

    def _load_sessions(self, start_year: int, end_year: int) -> None:
        """加载指定年份区间的交易日到缓存。"""
        sessions = self.cal.sessions_in_range(
            pd.Timestamp(f"{start_year}-01-01"),
            pd.Timestamp(f"{end_year}-12-31")
        )
        self._trading_days_set = set(sessions.strftime('%Y-%m-%d').tolist())
        self._trading_days_list = sorted(self._trading_days_set)
        
    def _to_date_str(self, date) -> str:
        """统一日期格式为 'YYYY-MM-DD' 字符串"""
        if isinstance(date, pd.Timestamp):
            return date.strftime('%Y-%m-%d')
        elif isinstance(date, (datetime, date_type)):
            return date.strftime('%Y-%m-%d')
        elif isinstance(date, str):
            return date
        else:
            raise ValueError(f"不支持的日期类型：{type(date)}")
    
    def _to_timestamp(self, date) -> pd.Timestamp:
        """统一转换为 pandas Timestamp"""
        return pd.Timestamp(self._to_date_str(date))

    def _ensure_cache_covers(self, date_str: str) -> None:
        """若 date_str 年份超出缓存范围，增量刷新缓存。

        调度器跨年长期运行时，新年份的交易日不在初始化缓存中，
        此方法在 is_trading_day / get_recent_trading_days 查询前自动补齐。
        """
        year = int(date_str[:4])
        if year < self._cache_start_year or year > self._cache_end_year:
            new_start = min(year, self._cache_start_year)
            new_end = max(year, self._cache_end_year)
            self._load_sessions(new_start, new_end)
            self._cache_start_year = new_start
            self._cache_end_year = new_end
    
    # ================= 功能 1: 判断是否为交易日 =================
    def is_trading_day(self, date=None) -> bool:
        """判断指定日期是否为交易日。

        Args:
            date: 日期，支持 str/datetime/Timestamp，默认为今天

        Returns:
            True 为交易日，False 为非交易日

        Example:
            >>> calendar = TradingCalendarService()
            >>> calendar.is_trading_day("2026-04-28")
            True
        """
        date_str = self._to_date_str(date if date else datetime.now())
        self._ensure_cache_covers(date_str)
        return date_str in self._trading_days_set
    
    # ================= 功能 2: 获取最近 N 个交易日 =================
    def get_recent_trading_days(self, n: int = 1, end_date=None) -> List[str]:
        """获取最近 N 个交易日。

        Args:
            n: 需要获取的交易日数量
            end_date: 截止日期（不含），默认为昨天

        Returns:
            交易日列表，按时间从近到远排列

        Example:
            >>> calendar = TradingCalendarService()
            >>> calendar.get_recent_trading_days(3)
            ['2026-04-28', '2026-04-27', '2026-04-26']
        """
        # 截止日期不纳入考虑范围，因此真实的end_date是end_date的前一个交易日
        if end_date is None:
            end_date = datetime.now() - timedelta(days=1)

        end_date_str = self._to_date_str(end_date)
        self._ensure_cache_covers(end_date_str)
            
        end_ts = self._to_timestamp(end_date)
        
        # 找到 end_date 之前的最近一个交易日作为起点
        # 如果 end_date 本身就是交易日，则从它开始往前推
        # 如果 end_date 不是交易日，则从上一个交易日开始往前推
        if self.is_trading_day(end_date):
            current_start = end_ts
        else:
            try:
                current_start = self.cal.previous_session(end_ts)
            except:
                return []
        
        # 向前查找 N 个交易日
        trading_days = []
        current = current_start
        
        for _ in range(n):
            date_str = current.strftime('%Y-%m-%d')
            if date_str in self._trading_days_set:
                trading_days.append(date_str)
                # 继续往前找
                try:
                    current = self.cal.previous_session(current)
                except:
                    break
            else:
                break
        
        return trading_days
    
    # ================= 功能 3: 获取日期范围内的所有交易日 =================
    def get_trading_days_in_range(self, start_date, end_date) -> List[str]:
        """获取日期范围内的所有交易日。

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            交易日列表 ['YYYY-MM-DD', ...]

        Example:
            >>> calendar = TradingCalendarService()
            >>> calendar.get_trading_days_in_range("2026-04-01", "2026-04-30")
            ['2026-04-01', '2026-04-02', ...]
        """
        start_ts = self._to_timestamp(start_date)
        end_ts = self._to_timestamp(end_date)
        
        if start_ts > end_ts:
            raise ValueError("开始日期不能晚于结束日期")
        
        # 使用库函数直接获取范围内的交易日
        sessions = self.cal.sessions_in_range(start_ts, end_ts)
        return sessions.strftime('%Y-%m-%d').tolist()
    
    # ================= 功能 4: 获取日期范围内的所有非交易日 =================
    def get_non_trading_days_in_range(self, start_date, end_date) -> List[str]:
        """获取日期范围内的所有非交易日（周末、节假日）。

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            非交易日列表 ['YYYY-MM-DD', ...]

        Example:
            >>> calendar = TradingCalendarService()
            >>> calendar.get_non_trading_days_in_range("2026-04-01", "2026-04-07")
            ['2026-04-04', '2026-04-05', ...]
        """
        start_ts = self._to_timestamp(start_date)
        end_ts = self._to_timestamp(end_date)

        if start_ts > end_ts:
            raise ValueError("开始日期不能晚于结束日期")

        # 获取交易日集合
        trading_days = set(self.get_trading_days_in_range(start_date, end_date))

        # 遍历所有自然日，找出非交易日
        non_trading_days = []
        current = start_ts
        while current <= end_ts:
            date_str = current.strftime('%Y-%m-%d')
            if date_str not in trading_days:
                non_trading_days.append(date_str)
            current += timedelta(days=1)

        return non_trading_days

    # ================= 功能 5: 获取下一个交易日 =================
    def get_next_trading_day(self, date=None) -> Optional[str]:
        """获取下一个交易日。

        Args:
            date: 基准日期，默认为今天

        Returns:
            下一个交易日 'YYYY-MM-DD'，超出日历范围返回 None

        Example:
            >>> calendar = TradingCalendarService()
            >>> calendar.get_next_trading_day("2026-04-28")
            '2026-04-29'
        """
        if date is None:
            date = datetime.now()
            
        current_ts = self._to_timestamp(date)
        
        try:
            next_session = self.cal.next_session(current_ts)
            return next_session.strftime('%Y-%m-%d')
        except:
            # 超出日历范围（如查询太远的未来）
            return None
    
    # ================= 附加功能：获取上一个交易日 =================
    def get_previous_trading_day(self, date=None) -> Optional[str]:
        """获取上一个交易日（用于 T-1 信号日）。

        Args:
            date: 基准日期，默认为今天

        Returns:
            上一个交易日 'YYYY-MM-DD'，超出日历范围返回 None

        Example:
            >>> calendar = TradingCalendarService()
            >>> calendar.get_previous_trading_day("2026-04-28")
            '2026-04-27'
        """
        if date is None:
            date = datetime.now()
            
        current_ts = self._to_timestamp(date)
        
        try:
            prev_session = self.cal.previous_session(current_ts)
            return prev_session.strftime('%Y-%m-%d')
        except:
            return None


if __name__ == "__main__":
    # 测试代码
    calendar = TradingCalendarService()
    print(calendar.get_previous_trading_day())
    print(calendar.get_next_trading_day())
    print(calendar.get_recent_trading_days(n=5))
    print(calendar.get_trading_days_in_range("2026-03-01", "2026-03-26"))
    print(calendar.get_non_trading_days_in_range("2026-03-01", "2026-03-26"))
    print(calendar.is_trading_day("2026-03-22"))
