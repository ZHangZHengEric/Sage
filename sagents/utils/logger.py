import os
import logging
import inspect
import sys
import traceback
import glob
import threading
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from typing import Dict, Optional


class BoundLogger:
    def __init__(self, base_logger: "Logger", context: Optional[Dict[str, object]] = None):
        self.base_logger = base_logger
        self.context = context or {}

    def bind(self, **kwargs):
        merged = {**self.context, **kwargs}
        return BoundLogger(self.base_logger, merged)

    def _format_message(self, message: str):
        if not self.context:
            return message, None

        explicit_session_id = self.context.get("session_id")
        extra_pairs = []
        for key, value in self.context.items():
            if key == "session_id":
                continue
            extra_pairs.append(f"{key}={value}")

        prefix = f"[{' '.join(extra_pairs)}] " if extra_pairs else ""
        return f"{prefix}{message}", explicit_session_id

    def debug(self, message, **kwargs):
        final_message, session_id = self._format_message(message)
        self.base_logger.debug(final_message, session_id=session_id, **kwargs)

    def info(self, message, **kwargs):
        final_message, session_id = self._format_message(message)
        self.base_logger.info(final_message, session_id=session_id, **kwargs)

    def warning(self, message, **kwargs):
        final_message, session_id = self._format_message(message)
        self.base_logger.warning(final_message, session_id=session_id, **kwargs)

    def error(self, message, **kwargs):
        final_message, session_id = self._format_message(message)
        self.base_logger.error(final_message, session_id=session_id, **kwargs)

    def critical(self, message, **kwargs):
        final_message, session_id = self._format_message(message)
        self.base_logger.critical(final_message, session_id=session_id, **kwargs)

    def exception(self, message, **kwargs):
        final_message, session_id = self._format_message(message)
        self.base_logger.error(final_message, session_id=session_id, **kwargs)

    def success(self, message, **kwargs):
        final_message, session_id = self._format_message(message)
        self.base_logger.info(final_message, session_id=session_id, **kwargs)

class Logger:
    _instance = None
    _initialized = False
    _cleanup_timer = None
    _cleanup_interval = 24 * 60 * 60  # 24小时（秒）

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
        return cls._instance

    def __init__(self, log_dir=None):
        if Logger._initialized:
            return

        if log_dir is None:
            # Use absolute path relative to project root to avoid creating logs in CWD
            # .../Sage/sagents/utils/logger.py -> .../Sage
            current_file = os.path.abspath(__file__)
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
            log_dir = os.path.join(project_root, 'logs')

        self.log_dir = log_dir
        
        # Create main logger
        self.logger = logging.getLogger('sage')
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False

        # Clear existing handlers to avoid duplicate logs
        if self.logger.handlers:
            self._close_handlers(self.logger)

        # Console handler - 只显示INFO及以上级别
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter('%(asctime)s - %(levelname)s - [%(session_id)s] - [%(caller_filename)s:%(caller_lineno)d] - %(message)s')
        console_handler.setFormatter(console_format)
        self.logger.addHandler(console_handler)

        try:
            os.makedirs(log_dir, exist_ok=True)

            # 文件日志格式
            file_format = logging.Formatter('%(asctime)s - %(levelname)s - [%(session_id)s] - [%(caller_filename)s:%(caller_lineno)d] - %(message)s')

            # 创建四个不同级别的文件日志处理器，按天分割
            log_levels = [
                ('debug', logging.DEBUG),
                ('info', logging.INFO), 
                ('warning', logging.WARNING),
                ('error', logging.ERROR)
            ]

            for level_name, level_value in log_levels:
                # 使用TimedRotatingFileHandler按天分割日志
                # 基础文件名不包含日期，日期通过suffix添加
                log_file = os.path.join(log_dir, f'sage_{level_name}.log')
                file_handler = TimedRotatingFileHandler(
                    log_file, 
                    when='midnight',  # 每天午夜分割
                    interval=1,       # 每1天
                    backupCount=30,   # 保留30天的日志
                    encoding='utf-8'
                )
                file_handler.setLevel(level_value)
                file_handler.setFormatter(file_format)

                # 设置日志文件名后缀格式，轮转时会变成 sage_info.log._20241024 格式
                # 但我们需要 sage_info_20241024.log 格式，所以需要自定义
                file_handler.suffix = "_%Y%m%d"
                # 设置namer函数来自定义轮转后的文件名格式
                def custom_namer(default_name):
                    # default_name 格式: sage_info.log._20241024
                    # 我们要转换为: sage_info_20241024.log
                    if '._' in default_name:
                        # 处理 sage_info.log._20241024 格式
                        base_part, date_part = default_name.split('._')
                        base_name = base_part.replace('.log', '')  # 移除 .log
                        return f"{base_name}_{date_part}.log"
                    return default_name
                file_handler.namer = custom_namer

                self.logger.addHandler(file_handler)
        
        except (PermissionError, OSError) as e:
            # In sandbox or restricted environments, we might not have permission to write to log files
            # Just fallback to console logging
            sys.stderr.write(f"Warning: Could not setup file logging: {e}\n")

        # Session-specific loggers cache
        self.session_loggers: Dict[str, logging.Logger] = {}

        # 清理一个月前的日志文件
        self._cleanup_old_logs()

        # 启动定期清理
        self._start_periodic_cleanup()

        Logger._initialized = True

    def _cleanup_old_logs(self):
        """清理一个月前的日志文件"""
        deleted_count = 0
        total_size_deleted = 0

        try:
            # 计算一个月前的日期
            one_month_ago = datetime.now() - timedelta(days=30)

            # 查找所有日志文件（包括新格式和旧格式）
            log_patterns = [
                # 新格式：sage_level_YYYYMMDD.log
                os.path.join(self.log_dir, 'sage_debug_*.log'),
                os.path.join(self.log_dir, 'sage_info_*.log'),
                os.path.join(self.log_dir, 'sage_warning_*.log'),
                os.path.join(self.log_dir, 'sage_error_*.log'),
                # 旧格式：sage_level.log.* 和 sage_YYYYMMDD.log
                os.path.join(self.log_dir, 'sage_debug.log.*'),
                os.path.join(self.log_dir, 'sage_info.log.*'),
                os.path.join(self.log_dir, 'sage_warning.log.*'),
                os.path.join(self.log_dir, 'sage_error.log.*'),
                os.path.join(self.log_dir, 'sage_*.log.*'),  # 兼容旧格式
                os.path.join(self.log_dir, 'sage_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].log')  # 旧格式日期文件
            ]

            # 收集所有匹配的文件，避免重复
            all_log_files = set()
            for pattern in log_patterns:
                all_log_files.update(glob.glob(pattern))

            for log_file in all_log_files:
                try:
                    # 获取文件信息
                    file_stat = os.stat(log_file)
                    file_mtime = datetime.fromtimestamp(file_stat.st_mtime)
                    file_size = file_stat.st_size

                    # 如果文件超过一个月，删除它
                    if file_mtime < one_month_ago:
                        os.remove(log_file)
                        deleted_count += 1
                        total_size_deleted += file_size

                        # 使用logger记录删除操作（避免循环调用）
                        self._write_stderr(
                            f"[LOG CLEANUP] Deleted old log file: {log_file} "
                            f"(size: {file_size} bytes, modified: {file_mtime.strftime('%Y-%m-%d %H:%M:%S')})"
                        )

                except Exception as e:
                    # 删除单个文件失败不影响整体功能
                    self._write_stderr(f"[LOG CLEANUP] Failed to delete log file {log_file}: {e}")

        except Exception:
            # 清理失败不影响logger的主要功能
            import traceback
            traceback.print_exc()

    def _start_periodic_cleanup(self):
        """启动定期清理任务"""
        try:
            # 如果已经有定时器在运行，先停止它
            if self._cleanup_timer is not None:
                self._cleanup_timer.cancel()

            # 创建新的定时器，24小时后执行清理
            self._cleanup_timer = threading.Timer(self._cleanup_interval, self._periodic_cleanup_task)
            self._cleanup_timer.daemon = True  # 设置为守护线程，主程序退出时自动结束
            self._cleanup_timer.start()

        except Exception as e:
            self._write_stderr(f"[LOG CLEANUP] Failed to start periodic cleanup: {e}")
            import traceback
            traceback.print_exc()

    def _periodic_cleanup_task(self):
        """定期清理任务"""
        try:
            self._write_stderr(
                f"[LOG CLEANUP] Starting periodic cleanup task at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            # 执行清理
            self._cleanup_old_logs()

            # 重新启动下一次定期清理
            self._start_periodic_cleanup()

        except Exception as e:
            self._write_stderr(f"[LOG CLEANUP] Periodic cleanup task failed: {e}")
            import traceback
            traceback.print_exc()

            # 即使失败也要重新启动定期清理
            try:
                self._start_periodic_cleanup()
            except Exception as restart_error:
                self._write_stderr(f"[LOG CLEANUP] Failed to restart periodic cleanup: {restart_error}")

    def stop_periodic_cleanup(self):
        """停止定期清理（用于测试或手动控制）"""
        if self._cleanup_timer is not None:
            self._cleanup_timer.cancel()
            self._cleanup_timer = None

    def _get_current_session_id(self) -> Optional[str]:
        """尝试获取当前session id"""
        try:
            from sagents.session_runtime import get_current_session_id
            session_id = get_current_session_id()
            if session_id:
                return session_id

            return None
        except Exception:
            # 如果获取失败，返回None
            return None

    @staticmethod
    def _close_handlers(target_logger: logging.Logger) -> None:
        """Close file-backed handlers before clearing them to avoid resource leaks."""
        for handler in list(target_logger.handlers):
            try:
                handler.close()
            except Exception:
                pass
        target_logger.handlers.clear()

    def _get_session_logger(self, session_id: str) -> logging.Logger:
        """获取或创建session专用的logger"""
        if session_id in self.session_loggers:
            session_logger = self.session_loggers[session_id]
        else:
            # 创建session专用logger
            session_logger = logging.getLogger(f'sage_session_{session_id}')
            session_logger.setLevel(logging.DEBUG)
            session_logger.propagate = False

            # 清除可能存在的handlers
            if session_logger.handlers:
                self._close_handlers(session_logger)
            
            self.session_loggers[session_id] = session_logger

        # 检查是否已经有FileHandler
        has_file_handler = any(isinstance(h, logging.FileHandler) for h in session_logger.handlers)
        
        # 如果没有FileHandler，尝试添加
        if not has_file_handler:
            try:
                # 获取session workspace路径
                from sagents.session_runtime import get_global_session_manager
                session_manager = get_global_session_manager()
                session = session_manager.get_live_session(session_id) if session_manager else None
                if session and session.session_context:
                    # 检查 session_workspace 属性是否存在（init_more 完成后才有）
                    if hasattr(session.session_context, 'session_workspace'):
                        session_workspace = session.session_context.session_workspace

                        # 创建session专用的日志文件 - 使用普通FileHandler以确保追加模式
                        session_log_file = os.path.join(session_workspace, f'session_{session_id}.log')
                        # 使用FileHandler的追加模式，而不是RotatingFileHandler
                        session_file_handler = logging.FileHandler(session_log_file, mode='a', encoding='utf-8')
                        session_file_handler.setLevel(logging.DEBUG)
                        session_format = logging.Formatter('%(asctime)s - %(levelname)s - [%(caller_filename)s:%(caller_lineno)d] - %(message)s')
                        session_file_handler.setFormatter(session_format)

                        session_logger.addHandler(session_file_handler)
            except Exception as e:
                # 如果无法创建session专用日志文件，记录错误但不影响主要功能
                self._write_stderr(f"Warning: Failed to create session log file for {session_id}: {e}")

        return session_logger

    @staticmethod
    def _write_stderr(message: str) -> None:
        try:
            sys.stderr.write(f"{message}\n")
            sys.stderr.flush()
        except Exception:
            pass

    def _log(self, level, message, explicit_session_id: Optional[str] = None, **kwargs):
        # Get caller frame info to include filename and line number
        # 优化：使用sys._getframe替代inspect.stack，因为inspect.stack在Docker/OverlayFS下非常慢
        try:
            # 0: current frame (_log)
            # 1: caller of _log (debug/info/etc)
            # 2: caller of debug/info/etc (user code)
            f = sys._getframe(2)
            filepath = f.f_code.co_filename
            lineno = f.f_lineno
            
            # 优化路径处理
            try:
                # 缓存cwd避免频繁系统调用
                if not hasattr(self, '_cwd'):
                    self._cwd = os.getcwd()
                
                # 简单的字符串操作替代 os.path.relpath
                if filepath.startswith(self._cwd):
                    rel_path = filepath[len(self._cwd):].lstrip(os.sep)
                else:
                    rel_path = filepath
                
                parts = rel_path.split(os.sep)
                if len(parts) > 2:
                    filename = os.path.join(*parts[-2:])
                else:
                    filename = rel_path
            except Exception:
                filename = os.path.basename(filepath)
                
        except (ValueError, AttributeError):
            filename = 'unknown.py'
            lineno = 0

        # 获取session id：优先使用显式传递的，然后从上下文获取
        session_id = explicit_session_id or self._get_current_session_id() or 'NO_SESSION'

        # 准备extra信息
        extra_info = {
            'caller_filename': filename, 
            'caller_lineno': lineno,
            'session_id': session_id
        }

        # 记录到主logger（包含session id）
        log_method = getattr(self.logger, level)
        log_method(f"{message}", extra=extra_info, **kwargs)

        # 如果有session id，同时记录到session专用日志
        if session_id != 'NO_SESSION':
            try:
                session_logger = self._get_session_logger(session_id)
                session_log_method = getattr(session_logger, level)
                session_log_method(f"{message}", extra={'caller_filename': filename, 'caller_lineno': lineno}, **kwargs)
            except Exception:
                # 如果session日志记录失败，不影响主要功能
                pass

    def debug(self, message, session_id: Optional[str] = None, **kwargs):
        self._log('debug', message, session_id, **kwargs)

    def info(self, message, session_id: Optional[str] = None, **kwargs):
        self._log('info', message, session_id, **kwargs)

    def warning(self, message, session_id: Optional[str] = None, **kwargs):
        self._log('warning', message, session_id, **kwargs)

    def bind(self, **kwargs):
        return BoundLogger(self, kwargs)

    def error(self, message, session_id: Optional[str] = None, **kwargs):
        # 在错误日志中自动添加traceback
        try:
            # 获取当前异常信息
            exc_info = sys.exc_info()
            if exc_info[0] is not None:
                # 如果当前有异常，添加traceback
                tb_str = ''.join(traceback.format_exception(*exc_info))
                message = f"{message}\nTraceback:\n{tb_str}"
        except Exception:
            # 如果获取traceback失败，不影响日志记录
            pass

        self._log('error', message, session_id, **kwargs)

    def exception(self, message, session_id: Optional[str] = None, **kwargs):
        self.error(message, session_id=session_id, **kwargs)

    def success(self, message, session_id: Optional[str] = None, **kwargs):
        self.info(message, session_id=session_id, **kwargs)

    def critical(self, message, session_id: Optional[str] = None, **kwargs):
        # 在严重错误日志中自动添加traceback
        try:
            # 获取当前异常信息
            exc_info = sys.exc_info()
            if exc_info[0] is not None:
                # 如果当前有异常，添加traceback
                tb_str = ''.join(traceback.format_exception(*exc_info))
                message = f"{message}\nTraceback:\n{tb_str}"
        except Exception:
            # 如果获取traceback失败，不影响日志记录
            pass

        self._log('critical', message, session_id, **kwargs)

    def cleanup_session_logger(self, session_id: str):
        """清理session专用的logger"""
        if session_id in self.session_loggers:
            session_logger = self.session_loggers[session_id]
            self._close_handlers(session_logger)
            # 从缓存中移除
            del self.session_loggers[session_id]

# Create a global logger instance for easy import
logger = Logger()
