from typing import Dict, Any, Optional
from app.models.strategy import StrategyVersion, Strategy
from app.repositories.strategy_repository import StrategyRepository, StrategyNotFoundError, StrategyVersionNotFoundError, StrategyForbiddenError
from app.services.strategies.version_service import VersionService
from app.utils.timezone import now_tz


class StrategyDiffService:
    """策略版本结构化 Diff 与回滚服务"""

    def __init__(self, repo: Optional[StrategyRepository] = None):
        self.repo = repo or StrategyRepository()

    def diff_versions(self, v1: StrategyVersion, v2: StrategyVersion) -> Dict[str, Any]:
        """
        对比两个策略版本的 parameters, rules, universe 异同。
        """
        diff_res = {
            "strategy_id": v1.strategy_id,
            "v1_num": v1.version_num,
            "v2_num": v2.version_num,
            "parameter_diffs": self._dict_diff(v1.parameters, v2.parameters),
            "rule_diffs": self._dict_diff(v1.rules, v2.rules),
            "universe_diffs": {
                "v1_symbols": v1.universe.symbols if v1.universe else [],
                "v2_symbols": v2.universe.symbols if v2.universe else [],
                "added_symbols": list(set(v2.universe.symbols) - set(v1.universe.symbols)) if v1.universe and v2.universe else [],
                "removed_symbols": list(set(v1.universe.symbols) - set(v2.universe.symbols)) if v1.universe and v2.universe else []
            }
        }
        return diff_res

    async def rollback_to_version(
        self,
        strategy_id: str,
        target_version_num: int,
        user_id: str,
        commit_message: Optional[str] = None
    ) -> StrategyVersion:
        """
        安全回滚至历史指定版本：递增创建新版本并复用目标版本的 parameters/rules/universe 配置。
        """
        strat = await self.repo.get_strategy(strategy_id)
        if not strat:
            raise StrategyNotFoundError(f"Strategy {strategy_id} not found")
        if strat.user_id != user_id and not strat.is_system_template:
            raise StrategyForbiddenError(f"User {user_id} cannot rollback strategy {strategy_id}")
        if strat.is_system_template:
            raise StrategyForbiddenError("System templates cannot be rolled back")

        versions = await self.repo.list_versions(strategy_id)
        target_ver = next((v for v in versions if v.version_num == target_version_num), None)
        if not target_ver:
            raise StrategyVersionNotFoundError(f"Version {target_version_num} not found for strategy {strategy_id}")

        version_service = VersionService(repo=self.repo)
        msg = commit_message or f"Rolled back to version v{target_version_num}"

        # 通过 update_draft 递增版本创建回滚副本
        new_ver = await version_service.update_draft(
            strategy_id=strategy_id,
            user_id=user_id,
            parameters=target_ver.parameters,
            rules=target_ver.rules,
            universe=target_ver.universe,
            commit_message=msg
        )
        return new_ver

    def _dict_diff(self, d1: Dict[str, Any], d2: Dict[str, Any]) -> Dict[str, Any]:
        added = {k: d2[k] for k in d2 if k not in d1}
        removed = {k: d1[k] for k in d1 if k not in d2}
        modified = {k: {"v1": d1[k], "v2": d2[k]} for k in d1 if k in d2 and d1[k] != d2[k]}
        return {"added": added, "removed": removed, "modified": modified}
