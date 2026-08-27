import uuid
from typing import Optional, List, Dict, Any, Tuple
from app.utils.timezone import now_tz
from app.models.strategy import (
    Strategy,
    StrategyVersion,
    StrategyStatus,
    StrategyType,
    UniverseSnapshot
)
from app.repositories.strategy_repository import (
    StrategyRepository,
    StrategyNotFoundError,
    StrategyVersionNotFoundError,
    StrategyForbiddenError
)


class VersionService:
    """策略版本管理服务：处理草稿更新、递增发布不可变版本、模板克隆与来源追踪"""

    def __init__(self, repo: Optional[StrategyRepository] = None):
        self.repo = repo or StrategyRepository()

    async def create_strategy(
        self,
        user_id: str,
        name: str,
        description: str = "",
        strategy_type: StrategyType = StrategyType.FACTOR_MODEL,
        parameters: Optional[Dict[str, Any]] = None,
        rules: Optional[Dict[str, Any]] = None,
        universe: Optional[UniverseSnapshot] = None,
        is_system_template: bool = False
    ) -> Tuple[Strategy, StrategyVersion]:
        """新建策略并创建初始 v1 版本的草稿 (Draft)"""
        now = now_tz()
        strat_id = f"strat_{uuid.uuid4().hex[:12]}"
        version_id = f"v_{uuid.uuid4().hex[:12]}"

        if universe is None:
            universe = UniverseSnapshot(universe_id=f"univ_{uuid.uuid4().hex[:8]}", user_id=user_id)

        strategy = Strategy(
            strategy_id=strat_id,
            user_id=user_id,
            name=name,
            description=description,
            strategy_type=strategy_type,
            status=StrategyStatus.DRAFT,
            latest_version_num=1,
            published_version_num=None,
            is_system_template=is_system_template,
            created_at=now,
            updated_at=now
        )

        initial_version = StrategyVersion(
            version_id=version_id,
            strategy_id=strat_id,
            version_num=1,
            is_published=False,
            parameters=parameters or {},
            rules=rules or {},
            universe=universe,
            created_at=now
        )

        created_strat = await self.repo.create_strategy(strategy)
        created_ver = await self.repo.save_version(initial_version)
        return created_strat, created_ver

    async def update_draft(
        self,
        strategy_id: str,
        user_id: str,
        parameters: Optional[Dict[str, Any]] = None,
        rules: Optional[Dict[str, Any]] = None,
        universe: Optional[UniverseSnapshot] = None,
        commit_message: Optional[str] = None
    ) -> StrategyVersion:
        """更新当前最新的草稿版本；若最新版本已发布，则自动递增版本号创建新草稿"""
        strat = await self.repo.get_strategy(strategy_id)
        if not strat:
            raise StrategyNotFoundError(f"Strategy {strategy_id} not found")
        if strat.user_id != user_id and not strat.is_system_template:
            raise StrategyForbiddenError(f"User {user_id} cannot edit strategy {strategy_id}")
        if strat.is_system_template:
            raise StrategyForbiddenError("System templates are read-only and cannot be edited directly")

        latest_ver = await self.repo.get_latest_version(strategy_id)
        if not latest_ver:
            raise StrategyVersionNotFoundError(f"No version found for strategy {strategy_id}")

        now = now_tz()

        if not latest_ver.is_published:
            # 修改已有草稿
            params = parameters if parameters is not None else latest_ver.parameters
            rls = rules if rules is not None else latest_ver.rules
            univ = universe if universe is not None else latest_ver.universe
            msg = commit_message if commit_message is not None else latest_ver.commit_message

            updated_ver = StrategyVersion(
                version_id=latest_ver.version_id,
                strategy_id=strategy_id,
                version_num=latest_ver.version_num,
                is_published=False,
                parameters=params,
                rules=rls,
                universe=univ,
                parent_strategy_id=latest_ver.parent_strategy_id,
                parent_version_num=latest_ver.parent_version_num,
                commit_message=msg,
                created_at=latest_ver.created_at
            )

            saved_ver = await self.repo.save_version(updated_ver)
            await self.repo.update_strategy(strategy_id, {"status": StrategyStatus.DRAFT, "updated_at": now})
            return saved_ver
        else:
            # 最新版本已发布，递增创建新草稿
            new_version_num = strat.latest_version_num + 1
            new_version = StrategyVersion(
                version_id=f"v_{uuid.uuid4().hex[:12]}",
                strategy_id=strategy_id,
                version_num=new_version_num,
                is_published=False,
                parameters=parameters if parameters is not None else latest_ver.parameters,
                rules=rules if rules is not None else latest_ver.rules,
                universe=universe if universe is not None else latest_ver.universe,
                commit_message=commit_message or f"Draft for v{new_version_num}",
                created_at=now
            )
            saved_ver = await self.repo.save_version(new_version)
            await self.repo.update_strategy(
                strategy_id,
                {"latest_version_num": new_version_num, "status": StrategyStatus.DRAFT, "updated_at": now}
            )
            return saved_ver

    async def publish_version(
        self,
        strategy_id: str,
        user_id: str,
        version_num: Optional[int] = None,
        commit_message: Optional[str] = None
    ) -> StrategyVersion:
        """冻结并发布指定版本（默认发布最新草稿），标记为 published"""
        strat = await self.repo.get_strategy(strategy_id)
        if not strat:
            raise StrategyNotFoundError(f"Strategy {strategy_id} not found")
        if strat.user_id != user_id and not strat.is_system_template:
            raise StrategyForbiddenError(f"User {user_id} cannot publish strategy {strategy_id}")
        if strat.is_system_template:
            raise StrategyForbiddenError("System templates cannot be published")

        if version_num is None:
            target_ver = await self.repo.get_latest_version(strategy_id)
        else:
            versions = await self.repo.list_versions(strategy_id)
            target_ver = next((v for v in versions if v.version_num == version_num), None)

        if not target_ver:
            raise StrategyVersionNotFoundError(f"Target version for strategy {strategy_id} not found")

        if target_ver.is_published:
            return target_ver

        now = now_tz()
        published_ver = StrategyVersion(
            version_id=target_ver.version_id,
            strategy_id=target_ver.strategy_id,
            version_num=target_ver.version_num,
            is_published=True,
            parameters=target_ver.parameters,
            rules=target_ver.rules,
            universe=target_ver.universe,
            parent_strategy_id=target_ver.parent_strategy_id,
            parent_version_num=target_ver.parent_version_num,
            commit_message=commit_message or target_ver.commit_message,
            published_at=now,
            created_at=target_ver.created_at
        )

        saved_ver = await self.repo.save_version(published_ver)
        await self.repo.update_strategy(
            strategy_id,
            {
                "status": StrategyStatus.PUBLISHED,
                "published_version_num": published_ver.version_num,
                "updated_at": now
            }
        )
        return saved_ver

    async def clone_strategy(
        self,
        strategy_id: str,
        user_id: str,
        new_name: Optional[str] = None,
        version_num: Optional[int] = None
    ) -> Tuple[Strategy, StrategyVersion]:
        """克隆策略（系统模板或他人策略），自动记录 parent_strategy_id / parent_version_num 来源"""
        src_strat = await self.repo.get_strategy(strategy_id)
        if not src_strat:
            raise StrategyNotFoundError(f"Source strategy {strategy_id} not found")

        if version_num is None:
            src_ver = await self.repo.get_latest_version(strategy_id)
        else:
            versions = await self.repo.list_versions(strategy_id)
            src_ver = next((v for v in versions if v.version_num == version_num), None)

        if not src_ver:
            raise StrategyVersionNotFoundError(f"Source version for strategy {strategy_id} not found")

        now = now_tz()
        new_strat_id = f"strat_{uuid.uuid4().hex[:12]}"
        new_version_id = f"v_{uuid.uuid4().hex[:12]}"
        name = new_name or f"Copy of {src_strat.name}"

        new_strat = Strategy(
            strategy_id=new_strat_id,
            user_id=user_id,
            name=name,
            description=src_strat.description,
            strategy_type=src_strat.strategy_type,
            status=StrategyStatus.DRAFT,
            latest_version_num=1,
            published_version_num=None,
            is_system_template=False,
            created_at=now,
            updated_at=now
        )

        new_ver = StrategyVersion(
            version_id=new_version_id,
            strategy_id=new_strat_id,
            version_num=1,
            is_published=False,
            parameters=dict(src_ver.parameters),
            rules=dict(src_ver.rules),
            universe=UniverseSnapshot(**src_ver.universe.model_dump()),
            parent_strategy_id=strategy_id,
            parent_version_num=src_ver.version_num,
            commit_message=f"Cloned from {strategy_id} (v{src_ver.version_num})",
            created_at=now
        )

        created_strat = await self.repo.create_strategy(new_strat)
        created_ver = await self.repo.save_version(new_ver)
        return created_strat, created_ver
