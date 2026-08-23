import sys
import time
import math
import uuid
import json
import datetime
from typing import Dict, Any, Optional
import numpy as np
import pandas as pd

from app.models.skill import SkillExecutionResult
from app.utils.timezone import now_tz


class SecuritySandboxError(Exception):
    """Sandbox 安全违规异常"""
    pass


class PythonSandboxEngine:
    """隔离沙箱引擎：安全受限地执行 Skill Python 代码"""

    def __init__(self, max_execution_time_sec: float = 5.0):
        self.max_execution_time_sec = max_execution_time_sec

    def execute_skill(
        self,
        skill_id: str,
        version_num: int,
        code: str,
        kwargs: Dict[str, Any]
    ) -> SkillExecutionResult:
        """
        在受限全局作用域中执行入口函数 `run(inputs)`。
        受限名单：禁止 import os, sys, subprocess, eval, exec, open, __import__。
        白名单库：math, numpy, pandas, json, datetime。
        """
        exec_id = f"exec_skill_{uuid.uuid4().hex[:12]}"
        start_time = time.time()

        # 代码安全检查
        forbidden_tokens = ["import os", "import sys", "import subprocess", "__import__", "eval(", "exec(", "open("]
        for token in forbidden_tokens:
            if token in code:
                return SkillExecutionResult(
                    execution_id=exec_id,
                    skill_id=skill_id,
                    version_num=version_num,
                    success=False,
                    error_message=f"Security Exception: Forbidden token '{token}' detected in code",
                    execution_time_ms=(time.time() - start_time) * 1000,
                    executed_at=now_tz()
                )

        # 构建白名单 globals
        allowed_globals: Dict[str, Any] = {
            "__builtins__": {
                "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
                "float": float, "int": int, "len": len, "list": list, "max": max,
                "min": min, "round": round, "set": set, "str": str, "sum": sum,
                "tuple": tuple, "zip": zip, "isinstance": isinstance, "isSubclass": issubclass
            },
            "math": math,
            "np": np,
            "numpy": np,
            "pd": pd,
            "pandas": pd,
            "json": json,
            "datetime": datetime
        }

        local_vars: Dict[str, Any] = {}

        try:
            exec(code, allowed_globals, local_vars)
            if "run" not in local_vars or not callable(local_vars["run"]):
                raise ValueError("Skill code must define a callable function named 'run(inputs)'")

            res = local_vars["run"](kwargs)
            exec_time = (time.time() - start_time) * 1000

            if exec_time > (self.max_execution_time_sec * 1000):
                return SkillExecutionResult(
                    execution_id=exec_id,
                    skill_id=skill_id,
                    version_num=version_num,
                    success=False,
                    error_message=f"Timeout Exception: Skill execution exceeded limit of {self.max_execution_time_sec}s",
                    execution_time_ms=exec_time,
                    executed_at=now_tz()
                )

            return SkillExecutionResult(
                execution_id=exec_id,
                skill_id=skill_id,
                version_num=version_num,
                success=True,
                result=res if isinstance(res, dict) else {"output": res},
                execution_time_ms=round(exec_time, 2),
                executed_at=now_tz()
            )

        except Exception as e:
            return SkillExecutionResult(
                execution_id=exec_id,
                skill_id=skill_id,
                version_num=version_num,
                success=False,
                error_message=f"Runtime Exception: {str(e)}",
                execution_time_ms=(time.time() - start_time) * 1000,
                executed_at=now_tz()
            )
